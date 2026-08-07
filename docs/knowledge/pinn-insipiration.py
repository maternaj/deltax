#!/usr/bin/env python3
"""One-shot anonymous Pinnacle live-odds query tool."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from argparse import Namespace
from dataclasses import dataclass, field
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlencode, urlsplit

from curl_cffi import requests


PA_ORIGINS = (
    "https://www.p4578.com",
    "https://www.pin1188.com",
    "https://www.part567.com",
    "https://www.zephyrveil57.xyz",
)
PA_ORIGIN = PA_ORIGINS[0]
ORIGINS_WITHOUT_CF_CACHE_STATUS = {"https://www.pin1188.com"}
REQUEST_TIMEOUT_SECONDS = 20.0
FRESH_CF_STATUSES = {"MISS", "BYPASS", "DYNAMIC", "REVALIDATED"}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_OUTPUT = SCRIPT_DIR / "pinnacle_odds_raw.json"
DEFAULT_PARSED_OUTPUT = SCRIPT_DIR / "pinnacle_odds_parsed.json"
SAFE_RESPONSE_HEADERS = {
    "age",
    "cache-control",
    "cf-cache-status",
    "cf-ray",
    "content-encoding",
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "server",
    "vary",
    "via",
}


class PinnacleQueryError(RuntimeError):
    """A live query could not produce a usable current response."""


class FreshnessError(PinnacleQueryError):
    """Every response attempt carried known-stale cache evidence."""


class PinnacleProtocolError(PinnacleQueryError):
    """The compact response did not have the expected public shape."""


class SelectionError(PinnacleQueryError):
    """A sport, league, or event selector was missing or ambiguous."""


def _header(headers: Mapping[str, Any], wanted: str) -> str | None:
    wanted = wanted.casefold()
    for name, value in headers.items():
        if str(name).casefold() == wanted:
            return str(value)
    return None


class FreshTokenFactory:
    """Return strictly increasing nanosecond cache-busters within a process."""

    def __init__(self, clock_ns: Callable[[], int] = time.time_ns) -> None:
        self._clock_ns = clock_ns
        self._last = -1

    def next(self) -> str:
        candidate = int(self._clock_ns())
        if candidate <= self._last:
            candidate = self._last + 1
        self._last = candidate
        return str(candidate)


def _api_root(origin: str) -> str:
    return f"{origin.rstrip('/')}/sports-service/sv/compact"


def build_sports_url(token: str, *, origin: str = PA_ORIGIN) -> str:
    query = urlencode((("c", ""), ("v", "0"), ("wm", ""), ("_", token)))
    return f"{_api_root(origin)}/sports-markets?{query}"


def build_events_url(
    sport_id: int,
    token: str,
    *,
    market_kind: int = 3,
    event_id: int | None = None,
    origin: str = PA_ORIGIN,
) -> str:
    if market_kind not in {0, 1, 2, 3}:
        raise ValueError("market_kind must be 0, 1, 2, or 3")
    query: list[tuple[str, str]] = [
        ("mk", str(market_kind)),
        ("sp", str(sport_id)),
        ("v", "0"),
        ("lv", "0"),
    ]
    if event_id is not None:
        query.extend((("more", "true"), ("me", str(event_id))))
    query.append(("_", token))
    return f"{_api_root(origin)}/events?{urlencode(query)}"


def _http_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def freshness_rejection_reason(
    status_code: int,
    headers: Mapping[str, Any],
    max_origin_age_seconds: float,
    *,
    received_unix_ns: int | None = None,
    allow_missing_cf_status: bool = False,
) -> str | None:
    if status_code != 200:
        return f"HTTP {status_code}"

    cf_status = (_header(headers, "cf-cache-status") or "").upper()
    if not cf_status and allow_missing_cf_status:
        if _http_date(_header(headers, "date")) is None:
            return "both CF-Cache-Status and a valid Date header are missing"
    elif cf_status not in FRESH_CF_STATUSES:
        return f"CF-Cache-Status {cf_status or 'missing'} is not fresh"

    raw_age = _header(headers, "age")
    if raw_age:
        try:
            age = float(raw_age)
        except ValueError:
            return f"invalid Age header {raw_age!r}"
        if age > 0:
            return f"Age is {age:g} seconds"

    response_date = _http_date(_header(headers, "date"))
    last_modified = _http_date(_header(headers, "last-modified"))
    if response_date is not None and received_unix_ns is not None:
        received_at = dt.datetime.fromtimestamp(
            received_unix_ns / 1_000_000_000, tz=dt.timezone.utc
        )
        response_age = (received_at - response_date).total_seconds()
        if response_age > max_origin_age_seconds:
            return (
                f"Date trails local receipt by {response_age:g} seconds "
                f"(limit {max_origin_age_seconds:g})"
            )
        if response_age < -max_origin_age_seconds:
            return (
                f"Date is {-response_age:g} seconds ahead of local receipt "
                f"(limit {max_origin_age_seconds:g})"
            )
    if response_date is not None and last_modified is not None:
        origin_age = max(0.0, (response_date - last_modified).total_seconds())
        if origin_age > max_origin_age_seconds:
            return (
                f"Last-Modified trails Date by {origin_age:g} seconds "
                f"(limit {max_origin_age_seconds:g})"
            )
    return None


@dataclass
class CapturedResponse:
    purpose: str
    url: str
    status_code: int
    headers: dict[str, str]
    body: Any
    raw_body: bytes
    started_unix_ns: int
    received_unix_ns: int
    started_monotonic_ns: int
    received_monotonic_ns: int
    freshness: dict[str, Any]
    rejected_attempts: list[dict[str, Any]] = field(default_factory=list)


def fetch_fresh_json(
    session: Any,
    url_factory: Callable[[str], str],
    *,
    purpose: str,
    token_factory: FreshTokenFactory,
    attempts: int,
    max_origin_age_seconds: float,
    allow_missing_cf_status: bool = False,
) -> CapturedResponse:
    rejected: list[dict[str, Any]] = []
    last_reason = "no request attempted"
    for attempt_number in range(1, attempts + 1):
        token = token_factory.next()
        url = url_factory(token)
        started_unix_ns = time.time_ns()
        started_monotonic_ns = time.monotonic_ns()
        try:
            parts = urlsplit(url)
            request_origin = f"{parts.scheme}://{parts.netloc}"
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers=build_api_headers(request_origin),
            )
        except Exception as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
            rejected.append(
                {"attempt": attempt_number, "url": url, "reason": last_reason}
            )
            continue
        received_unix_ns = time.time_ns()
        received_monotonic_ns = time.monotonic_ns()
        status_code = int(response.status_code)
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        reason = freshness_rejection_reason(
            status_code,
            headers,
            max_origin_age_seconds,
            received_unix_ns=received_unix_ns,
            allow_missing_cf_status=allow_missing_cf_status,
        )
        if reason is not None:
            last_reason = reason
            rejected.append(
                {"attempt": attempt_number, "url": url, "reason": reason}
            )
            continue
        raw_body = bytes(response.content)
        try:
            body = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            last_reason = f"invalid JSON: {exc}"
            rejected.append(
                {"attempt": attempt_number, "url": url, "reason": last_reason}
            )
            continue
        response_url = str(getattr(response, "url", None) or url)
        return CapturedResponse(
            purpose=purpose,
            url=response_url,
            status_code=status_code,
            headers=headers,
            body=body,
            raw_body=raw_body,
            started_unix_ns=started_unix_ns,
            received_unix_ns=received_unix_ns,
            started_monotonic_ns=started_monotonic_ns,
            received_monotonic_ns=received_monotonic_ns,
            freshness={
                "accepted": True,
                "cache_buster": token,
                "cf_cache_status": (_header(headers, "cf-cache-status") or "").upper(),
                "cache_validation": (
                    "explicit_cf_cache_status"
                    if _header(headers, "cf-cache-status")
                    else "current_date_and_unique_url"
                ),
                "age_seconds": _header(headers, "age"),
                "response_date": _header(headers, "date"),
                "last_modified": _header(headers, "last-modified"),
                "requested_full_snapshot": True,
                "requested_versions": {"v": 0, "lv": 0},
            },
            rejected_attempts=rejected,
        )
    raise FreshnessError(
        f"Could not obtain fresh {purpose} after {attempts} attempts: {last_reason}"
    )


class OriginFailover:
    """Try public mirrors in order and remain on the first working origin."""

    def __init__(self, origins: tuple[str, ...] = PA_ORIGINS) -> None:
        if not origins:
            raise ValueError("at least one origin is required")
        self.origins = origins
        self.active_index = 0

    @property
    def active_origin(self) -> str:
        return self.origins[self.active_index]

    def fetch(
        self,
        session: Any,
        url_factory: Callable[[str, str], str],
        *,
        purpose: str,
        token_factory: FreshTokenFactory,
        attempts: int,
        max_origin_age_seconds: float,
    ) -> CapturedResponse:
        origin_failures: list[dict[str, Any]] = []
        last_error = "no origin attempted"
        for index in range(self.active_index, len(self.origins)):
            origin = self.origins[index]
            try:
                capture = fetch_fresh_json(
                    session,
                    lambda token, selected=origin: url_factory(selected, token),
                    purpose=purpose,
                    token_factory=token_factory,
                    attempts=attempts,
                    max_origin_age_seconds=max_origin_age_seconds,
                    allow_missing_cf_status=(
                        origin in ORIGINS_WITHOUT_CF_CACHE_STATUS
                    ),
                )
            except FreshnessError as exc:
                last_error = str(exc)
                origin_failures.append(
                    {
                        "scope": "origin_failover",
                        "origin": origin,
                        "reason": last_error,
                    }
                )
                continue

            self.active_index = index
            capture.freshness.update(
                {
                    "origin": origin,
                    "origin_priority": index + 1,
                    "fallback_used": index > 0,
                }
            )
            capture.rejected_attempts[:0] = origin_failures
            return capture

        raise FreshnessError(
            f"All Pinnacle public origins failed for {purpose}: {last_error}"
        )


def _at(values: Any, index: int, default: Any = None) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return default


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def parse_sports_menu(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("sports"), list):
        raise PinnacleProtocolError("sports menu is not a compact sports object")
    parsed: list[dict[str, Any]] = []
    for outer in body["sports"]:
        summary = _at(outer, 1)
        sport_id = _integer(_at(summary, 0))
        sport_name = _text(_at(summary, 1))
        event_count = _integer(_at(summary, 2))
        market_count = _integer(_at(summary, 3))
        if (
            sport_id is None
            or not sport_name
            or event_count is None
            or market_count is None
            or event_count <= 0
            or market_count <= 0
        ):
            continue
        parsed.append(
            {
                "sport_id": sport_id,
                "sport_name": sport_name,
                "live_event_count": event_count,
                "live_market_count": market_count,
            }
        )
    return parsed


def _candidate_summary(items: list[dict[str, Any]], id_key: str, name_key: str) -> str:
    return ", ".join(f"{item[id_key]}={item[name_key]}" for item in items[:12])


def resolve_sport(sports: list[dict[str, Any]], selector: str) -> dict[str, Any]:
    wanted = selector.strip()
    if not wanted:
        raise SelectionError("sport selector is empty")
    if wanted.isdecimal():
        matches = [item for item in sports if item["sport_id"] == int(wanted)]
    else:
        folded = wanted.casefold()
        exact = [item for item in sports if item["sport_name"].casefold() == folded]
        matches = exact or [
            item for item in sports if folded in item["sport_name"].casefold()
        ]
    if not matches:
        raise SelectionError(
            f"sport {selector!r} was not live; available: "
            f"{_candidate_summary(sports, 'sport_id', 'sport_name') or 'none'}"
        )
    if len(matches) > 1:
        raise SelectionError(
            f"sport {selector!r} is ambiguous: "
            f"{_candidate_summary(matches, 'sport_id', 'sport_name')}"
        )
    return matches[0]


def _utc_from_epoch_ms(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        stamp = dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_score(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and len(value) >= 2:
        return {"home": value[0], "away": value[1]}
    return None


def _normalize_spread_line(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(value) < 8:
        return None
    return {
        "away_spread": _at(value, 0),
        "home_spread": _at(value, 1),
        "handicap_label": _at(value, 2),
        "home_odds": _at(value, 3),
        "away_odds": _at(value, 4),
        "home_favorite": _at(value, 5),
        "away_favorite": _at(value, 6),
        "line_id": _at(value, 7),
        "alternate": _at(value, 8),
        "max_bet": _at(value, 9),
        "indicator": _at(value, 10),
    }


def _normalize_total_line(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(value) < 5:
        return None
    return {
        "handicap_label": _at(value, 0),
        "points": _at(value, 1),
        "over_odds": _at(value, 2),
        "under_odds": _at(value, 3),
        "line_id": _at(value, 4),
        "alternate": _at(value, 5),
        "max_bet": _at(value, 6),
        "indicator": _at(value, 7),
    }


def _normalize_moneyline(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    return {
        "home_odds": _at(value, 1),
        "away_odds": _at(value, 0),
        "draw_odds": _at(value, 2),
        "line_id": _at(value, 3),
        "alternate": _at(value, 4),
        "max_bet": _at(value, 5),
        "indicator": _at(value, 6),
    }


def _normalized_lines(value: Any, normalizer: Callable[[Any], Any]) -> list[Any]:
    if not isinstance(value, list):
        return []
    normalized = [normalizer(line) for line in value]
    return [line for line in normalized if line is not None]


def normalize_period(period_key: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {"period_key": str(period_key), "layout": "unknown", "raw": value}

    detailed = len(value) >= 14
    if detailed:
        team_totals, specials = _at(value, 0), _at(value, 1)
        spreads, totals, moneyline = _at(value, 2), _at(value, 3), _at(value, 4)
        period_number, name = _at(value, 5), _at(value, 6)
        home_favorite, away_favorite = _at(value, 7), _at(value, 8)
        main_line_index, more_bets = _at(value, 9), _at(value, 10)
        score, red_cards, status = _at(value, 11), _at(value, 12), _at(value, 13)
        layout = "match_detail"
    else:
        team_totals, specials = None, None
        spreads, totals, moneyline = _at(value, 0), _at(value, 1), _at(value, 2)
        period_number, name = _at(value, 3), _at(value, 4)
        home_favorite, away_favorite = _at(value, 5), _at(value, 6)
        main_line_index, more_bets = _at(value, 7), _at(value, 8)
        score, red_cards, status = _at(value, 9), _at(value, 10), _at(value, 11)
        layout = "sport_snapshot"

    parsed: dict[str, Any] = {
        "period_key": str(period_key),
        "layout": layout,
        "period_number": period_number,
        "name": name,
        "home_favorite": home_favorite,
        "away_favorite": away_favorite,
        "main_line_index": main_line_index,
        "more_bets": more_bets,
        "score": _normalize_score(score),
        "red_cards": _normalize_score(red_cards),
        "status": status,
        "spreads": _normalized_lines(spreads, _normalize_spread_line),
        "totals": _normalized_lines(totals, _normalize_total_line),
        "moneyline": _normalize_moneyline(moneyline),
    }
    if detailed:
        parsed["team_totals_raw"] = team_totals
        parsed["specials_raw"] = specials
    return parsed


def normalize_event(value: Any, *, market_section: str = "live") -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 9:
        raise PinnacleProtocolError("event row is malformed")
    event_id = _integer(_at(value, 0))
    home = _text(_at(value, 1))
    away = _text(_at(value, 2))
    if event_id is None or home is None or away is None:
        raise PinnacleProtocolError("event row has no ID or participant names")
    period_body = _at(value, 8)
    periods = (
        [normalize_period(str(key), item) for key, item in period_body.items()]
        if isinstance(period_body, dict)
        else []
    )
    result: dict[str, Any] = {
        "event_id": event_id,
        "home": home,
        "away": away,
        "match_name": f"{home} vs {away}",
        "market_section": market_section,
        "line_count": _at(value, 3),
        "start_time_unix_ms": _at(value, 4),
        "start_time_utc": _utc_from_epoch_ms(_at(value, 4)),
        "running": _at(value, 5),
        "live": _at(value, 6),
        "more_bet_count": _at(value, 7),
        "score": _normalize_score(_at(value, 9)),
        "red_cards": _normalize_score(_at(value, 10)),
        "team_type": _at(value, 11),
        "running_time": _at(value, 15),
        "running_period": _at(value, 16),
        "status": _at(value, 17),
        "total_markets": _at(value, 21),
        "parlay_restriction": _at(value, 22),
        "rotation_number": _at(value, 26),
        "grading_unit": _at(value, 27),
        "parent_event_id": _at(value, 28),
        "periods": periods,
    }
    if len(value) > 31:
        result["unparsed_tail"] = value[31:]
    return result


def normalize_sport_feed(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise PinnacleProtocolError("event response is not a compact object")
    if not any(isinstance(body.get(key), list) for key in ("l", "n")):
        raise PinnacleProtocolError("event response has no compact 'l' or 'n' rows")

    sports: list[dict[str, Any]] = []
    sports_by_id: dict[int, dict[str, Any]] = {}
    for response_key, market_section in (("l", "live"), ("n", "normal")):
        rows = body.get(response_key)
        if not isinstance(rows, list):
            continue
        for sport_row in rows:
            sport_id = _integer(_at(sport_row, 0))
            sport_name = _text(_at(sport_row, 1))
            league_rows = _at(sport_row, 2)
            if (
                sport_id is None
                or sport_name is None
                or not isinstance(league_rows, list)
            ):
                continue
            sport = sports_by_id.get(sport_id)
            if sport is None:
                sport = {
                    "sport_id": sport_id,
                    "sport_name": sport_name,
                    "live_cursor": _at(sport_row, 3),
                    "group": _at(sport_row, 4),
                    "section_cursors": {},
                    "market_sections": [],
                    "leagues": [],
                }
                sports_by_id[sport_id] = sport
                sports.append(sport)
            sport["section_cursors"][market_section] = _at(sport_row, 3)
            if market_section not in sport["market_sections"]:
                sport["market_sections"].append(market_section)

            leagues_by_id = {
                league["league_id"]: league for league in sport["leagues"]
            }
            for league_row in league_rows:
                league_id = _integer(_at(league_row, 0))
                league_name = _text(_at(league_row, 1))
                event_rows = _at(league_row, 2)
                if (
                    league_id is None
                    or league_name is None
                    or not isinstance(event_rows, list)
                ):
                    continue
                league = leagues_by_id.get(league_id)
                if league is None:
                    league = {
                        "league_id": league_id,
                        "league_name": league_name,
                        "events": [],
                        "display_name": _at(league_row, 4),
                        "max_moneyline": _at(league_row, 5),
                        "max_spread": _at(league_row, 6),
                        "max_total": _at(league_row, 7),
                    }
                    leagues_by_id[league_id] = league
                    sport["leagues"].append(league)
                existing_event_ids = {
                    event["event_id"] for event in league["events"]
                }
                for event_row in event_rows:
                    event = normalize_event(
                        event_row, market_section=market_section
                    )
                    if event["event_id"] not in existing_event_ids:
                        league["events"].append(event)
                        existing_event_ids.add(event["event_id"])
    return sports


def filter_leagues(sport: dict[str, Any], selector: str | None) -> dict[str, Any]:
    if selector is None:
        return {**sport, "leagues": list(sport.get("leagues", []))}
    wanted = selector.strip()
    leagues = list(sport.get("leagues", []))
    if wanted.isdecimal():
        matches = [item for item in leagues if item["league_id"] == int(wanted)]
    else:
        folded = wanted.casefold()
        exact = [item for item in leagues if item["league_name"].casefold() == folded]
        matches = exact or [
            item for item in leagues if folded in item["league_name"].casefold()
        ]
    if not matches:
        raise SelectionError(
            f"league/competition {selector!r} did not match any live league; "
            f"available: {_candidate_summary(leagues, 'league_id', 'league_name') or 'none'}"
        )
    return {**sport, "leagues": matches}


def select_single_event(
    sport: dict[str, Any], selector: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = [
        (league, event)
        for league in sport.get("leagues", [])
        for event in league.get("events", [])
    ]
    wanted = selector.strip()
    if wanted.isdecimal():
        matches = [item for item in candidates if item[1]["event_id"] == int(wanted)]
    else:
        folded = wanted.casefold()
        exact = [
            item
            for item in candidates
            if folded
            in {
                item[1]["home"].casefold(),
                item[1]["away"].casefold(),
                item[1]["match_name"].casefold(),
            }
        ]
        matches = exact or [
            item
            for item in candidates
            if folded in item[1]["home"].casefold()
            or folded in item[1]["away"].casefold()
            or folded in item[1]["match_name"].casefold()
        ]
    if not matches:
        raise SelectionError(f"match {selector!r} did not match any live event")
    if len(matches) > 1:
        choices = ", ".join(
            f"{event['event_id']}={event['match_name']}" for _, event in matches[:12]
        )
        raise SelectionError(f"match {selector!r} is ambiguous: {choices}")
    return matches[0]


def normalize_detail_feed(
    body: Any,
    *,
    sport_name: str,
    league_name: str,
    market_section: str = "detail",
) -> dict[str, Any]:
    detail = body.get("e") if isinstance(body, dict) else None
    if not isinstance(detail, list) or len(detail) < 5:
        raise PinnacleProtocolError("match-detail response has no compact 'e' row")
    sport_id = _integer(_at(detail, 0))
    league_id = _integer(_at(detail, 1))
    event_row = _at(detail, 3)
    if sport_id is None or league_id is None:
        raise PinnacleProtocolError("match-detail response has no sport/league ID")
    event = normalize_event(event_row, market_section=market_section)
    return {
        "sport_id": sport_id,
        "sport_name": sport_name,
        "live_cursor": _at(detail, 4),
        "group": _at(detail, 2),
        "leagues": [
            {
                "league_id": league_id,
                "league_name": league_name,
                "events": [event],
            }
        ],
    }


def _utc_iso_from_ns(unix_ns: int) -> str:
    seconds, nanoseconds = divmod(unix_ns, 1_000_000_000)
    value = dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc).replace(
        microsecond=nanoseconds // 1_000
    )
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _filtered_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(name).lower(): str(value)
        for name, value in headers.items()
        if str(name).lower() in SAFE_RESPONSE_HEADERS
    }


def _capture_document(capture: CapturedResponse) -> dict[str, Any]:
    return {
        "purpose": capture.purpose,
        "origin": capture.freshness.get("origin"),
        "request": {"method": "GET", "url": capture.url},
        "response": {
            "status_code": capture.status_code,
            "headers": _filtered_headers(capture.headers),
        },
        "timing": {
            "started_at_utc": _utc_iso_from_ns(capture.started_unix_ns),
            "started_unix_ns": capture.started_unix_ns,
            "received_at_utc": _utc_iso_from_ns(capture.received_unix_ns),
            "received_unix_ns": capture.received_unix_ns,
            "started_monotonic_ns": capture.started_monotonic_ns,
            "received_monotonic_ns": capture.received_monotonic_ns,
            "elapsed_ms": round(
                (capture.received_monotonic_ns - capture.started_monotonic_ns)
                / 1_000_000,
                6,
            ),
        },
        "freshness": capture.freshness,
        "rejected_attempts": capture.rejected_attempts,
        "body": capture.body,
    }


def _sport_counts(sport: Mapping[str, Any]) -> dict[str, int]:
    leagues = list(sport.get("leagues", []))
    events = [event for league in leagues for event in league.get("events", [])]
    periods = [period for event in events for period in event.get("periods", [])]
    return {
        "leagues": len(leagues),
        "events": len(events),
        "live_events": sum(event.get("market_section") == "live" for event in events),
        "normal_events": sum(
            event.get("market_section") == "normal" for event in events
        ),
        "periods": len(periods),
        "spread_lines": sum(len(period.get("spreads", [])) for period in periods),
        "total_lines": sum(len(period.get("totals", [])) for period in periods),
        "moneylines": sum(period.get("moneyline") is not None for period in periods),
    }


def assemble_outputs(
    captures: list[CapturedResponse],
    selection: Mapping[str, Any],
    sport: dict[str, Any],
    *,
    market_kind: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    captured_unix_ns = captures[-1].received_unix_ns
    request_documents = [_capture_document(capture) for capture in captures]
    origins_used = list(
        dict.fromkeys(
            str(capture.freshness["origin"])
            for capture in captures
            if capture.freshness.get("origin")
        )
    )
    raw = {
        "record_type": "pinnacle_odds_raw_responses",
        "source": "pinnacle_public_mirrors",
        "captured_at_utc": _utc_iso_from_ns(captured_unix_ns),
        "captured_unix_ns": captured_unix_ns,
        "origin_priority": list(PA_ORIGINS),
        "origins_used": origins_used,
        "requests": request_documents,
    }
    parsed = {
        "record_type": "pinnacle_odds_query",
        "source": "pinnacle_public_mirrors",
        "captured_at_utc": _utc_iso_from_ns(captured_unix_ns),
        "captured_unix_ns": captured_unix_ns,
        "freshness": {
            "request_count": len(captures),
            "all_requests_accepted_as_fresh": all(
                bool(capture.freshness.get("accepted")) for capture in captures
            ),
            "cf_cache_statuses": [
                capture.freshness.get("cf_cache_status") for capture in captures
            ],
            "cache_busters": [
                capture.freshness.get("cache_buster") for capture in captures
            ],
            "primary_origin": PA_ORIGIN,
            "origin_priority": list(PA_ORIGINS),
            "origins_used": origins_used,
            "fallback_used": any(
                bool(capture.freshness.get("fallback_used"))
                for capture in captures
            ),
            "requested_full_snapshot": True,
            "requested_parameters": {"mk": market_kind, "v": 0, "lv": 0},
            "local_or_cdn_cache_reuse_allowed": False,
            "server_delay_observable": False,
            "limitation": (
                "The service exposes no Pinnacle odds-emission timestamp; fresh "
                "HTTP/cache evidence cannot prove zero upstream server delay."
            ),
        },
        "selection": dict(selection),
        "counts": _sport_counts(sport),
        "sport": sport,
    }
    return raw, parsed


def build_api_headers(origin: str = PA_ORIGIN) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "Origin": origin,
        "Referer": f"{origin.rstrip('/')}/en/",
        "User-Agent": USER_AGENT,
    }


def create_http_session() -> Any:
    return requests.Session(impersonate="chrome", headers=build_api_headers())


def _one_sport(body: Any, sport_id: int) -> dict[str, Any]:
    sports = normalize_sport_feed(body)
    matches = [sport for sport in sports if sport["sport_id"] == sport_id]
    if not matches:
        raise PinnacleProtocolError(
            f"fresh response did not contain live rows for sport {sport_id}"
        )
    return matches[0]


def run_query(
    args: argparse.Namespace,
    *,
    session: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    http = session or create_http_session()
    tokens = FreshTokenFactory()
    origins = OriginFailover()
    captures: list[CapturedResponse] = []

    menu_capture = origins.fetch(
        http,
        lambda origin, token: build_sports_url(token, origin=origin),
        purpose="live sports menu",
        token_factory=tokens,
        attempts=args.fresh_attempts,
        max_origin_age_seconds=args.max_origin_age,
    )
    captures.append(menu_capture)
    sport_choice = resolve_sport(parse_sports_menu(menu_capture.body), args.sport)
    sport_id = int(sport_choice["sport_id"])
    sport_name = str(sport_choice["sport_name"])

    sport_capture = origins.fetch(
        http,
        lambda origin, token: build_events_url(
            sport_id, token, market_kind=args.mk, origin=origin
        ),
        purpose=f"full market bucket {args.mk} odds for {sport_name}",
        token_factory=tokens,
        attempts=args.fresh_attempts,
        max_origin_age_seconds=args.max_origin_age,
    )
    captures.append(sport_capture)
    selected_sport = filter_leagues(_one_sport(sport_capture.body, sport_id), args.league)
    selection: dict[str, Any] = {
        "requested_sport": args.sport,
        "requested_league": args.league,
        "requested_match": args.match,
        "sport_id": sport_id,
        "sport_name": sport_name,
        "market_kind": args.mk,
        "league_ids": [
            league["league_id"] for league in selected_sport.get("leagues", [])
        ],
    }

    if args.match:
        league, event = select_single_event(selected_sport, args.match)
        detail_capture = origins.fetch(
            http,
            lambda origin, token: build_events_url(
                sport_id,
                token,
                market_kind=args.mk,
                event_id=int(event["event_id"]),
                origin=origin,
            ),
            purpose=f"full match odds for {event['match_name']}",
            token_factory=tokens,
            attempts=args.fresh_attempts,
            max_origin_age_seconds=args.max_origin_age,
        )
        captures.append(detail_capture)
        selected_sport = normalize_detail_feed(
            detail_capture.body,
            sport_name=sport_name,
            league_name=str(league["league_name"]),
            market_section=str(event.get("market_section") or "detail"),
        )
        selection.update(
            {
                "league_ids": [int(league["league_id"])],
                "league_name": league["league_name"],
                "event_id": int(event["event_id"]),
                "match_name": event["match_name"],
            }
        )

    return assemble_outputs(
        captures, selection, selected_sport, market_kind=args.mk
    )


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise PinnacleQueryError(f"could not write {path}: {exc}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one forced-fresh anonymous Pinnacle live-odds snapshot, "
            "then write its raw and normalized JSON."
        )
    )
    parser.add_argument(
        "--sport",
        help="live sport name or numeric ID (for example: tennis or 33)",
    )
    league = parser.add_mutually_exclusive_group()
    league.add_argument(
        "--competition",
        "--comp",
        "--league",
        dest="league",
        help="league/competition name substring or numeric ID",
    )
    parser.add_argument(
        "--match",
        help="participant/match substring or exact numeric event ID",
    )
    parser.add_argument(
        "--mk",
        type=int,
        choices=(0, 1, 2, 3),
        default=3,
        help="market bucket: 0=early, 1=today, 2=live, 3=all (default: 3)",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"raw response envelope (default: {DEFAULT_RAW_OUTPUT})",
    )
    parser.add_argument(
        "--parsed-output",
        type=Path,
        default=DEFAULT_PARSED_OUTPUT,
        help=f"normalized odds output (default: {DEFAULT_PARSED_OUTPUT})",
    )
    parser.add_argument(
        "--fresh-attempts",
        type=_positive_int,
        default=3,
        help="maximum attempts per request when cache evidence is stale (default: 3)",
    )
    parser.add_argument(
        "--max-origin-age",
        type=_positive_float,
        default=5.0,
        help="maximum Date minus Last-Modified age in seconds (default: 5)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="also print normalized JSON to stdout",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress summary output")
    parser.add_argument("--self-test", action="store_true", help="run offline tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        return _run_self_tests()
    if not args.sport:
        parser.error("--sport is required unless --self-test is used")
    try:
        raw, parsed = run_query(args)
        write_json_atomic(args.raw_output, raw)
        write_json_atomic(args.parsed_output, parsed)
    except PinnacleQueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.stdout:
        json.dump(parsed, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    elif not args.quiet:
        counts = parsed["counts"]
        statuses = ",".join(parsed["freshness"]["cf_cache_statuses"])
        print(
            f"fresh Pinnacle odds: {counts['events']} events, "
            f"{counts['periods']} periods, cache={statuses}, "
            f"origin={parsed['freshness']['origins_used'][-1]}"
        )
        print(f"raw: {args.raw_output}")
        print(f"parsed: {args.parsed_output}")
    return 0


class _FakeResponse:
    def __init__(
        self,
        body: object,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = json.dumps(body).encode("utf-8")
        self.url = ""
        self.infos: dict[object, object] = {}


def _fresh_headers_now() -> dict[str, str]:
    value = format_datetime(dt.datetime.now(dt.timezone.utc), usegmt=True)
    return {
        "CF-Cache-Status": "MISS",
        "Date": value,
        "Last-Modified": value,
    }


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:
        self.urls.append(url)
        response = self.responses.pop(0)
        response.url = url
        return response


class RequestFreshnessTests(unittest.TestCase):
    fresh_headers = {
        "CF-Cache-Status": "MISS",
        "Date": "Tue, 04 Aug 2026 08:45:34 GMT",
        "Last-Modified": "Tue, 04 Aug 2026 08:45:34 GMT",
    }

    def test_events_url_forces_full_live_snapshot(self) -> None:
        query = parse_qs(urlsplit(build_events_url(33, "123456")).query)
        self.assertEqual(
            query,
            {
                "mk": ["3"],
                "sp": ["33"],
                "v": ["0"],
                "lv": ["0"],
                "_": ["123456"],
            },
        )

    def test_events_url_accepts_explicit_market_kind(self) -> None:
        query = parse_qs(
            urlsplit(build_events_url(33, "123456", market_kind=1)).query
        )
        self.assertEqual(query["mk"], ["1"])

    def test_origin_priority_prefers_p4578_then_pin1188(self) -> None:
        self.assertEqual(
            PA_ORIGINS[:2],
            ("https://www.p4578.com", "https://www.pin1188.com"),
        )

    def test_url_builders_accept_a_backup_origin(self) -> None:
        origin = "https://www.part567.com"
        self.assertEqual(urlsplit(build_sports_url("123", origin=origin)).netloc, "www.part567.com")
        self.assertEqual(
            urlsplit(build_events_url(33, "456", origin=origin)).netloc,
            "www.part567.com",
        )

    def test_match_detail_url_retains_full_snapshot_parameters(self) -> None:
        query = parse_qs(
            urlsplit(build_events_url(33, "987654", event_id=4242)).query
        )
        self.assertEqual(query["more"], ["true"])
        self.assertEqual(query["me"], ["4242"])
        self.assertEqual(query["v"], ["0"])
        self.assertEqual(query["lv"], ["0"])

    def test_cache_busters_are_strictly_increasing_when_clock_repeats(self) -> None:
        tokens = FreshTokenFactory(clock_ns=lambda: 100)
        self.assertEqual([tokens.next(), tokens.next(), tokens.next()], ["100", "101", "102"])

    def test_freshness_gate_rejects_cloudflare_hit(self) -> None:
        headers = dict(self.fresh_headers, **{"CF-Cache-Status": "HIT"})
        self.assertIn("HIT", freshness_rejection_reason(200, headers, 5.0) or "")

    def test_freshness_gate_rejects_old_last_modified(self) -> None:
        headers = dict(
            self.fresh_headers,
            **{"Last-Modified": "Tue, 04 Aug 2026 08:45:20 GMT"},
        )
        self.assertIn("Last-Modified", freshness_rejection_reason(200, headers, 5.0) or "")

    def test_freshness_gate_rejects_old_response_date(self) -> None:
        received = int(
            dt.datetime(
                2026, 8, 4, 8, 45, 50, tzinfo=dt.timezone.utc
            ).timestamp()
            * 1_000_000_000
        )
        reason = freshness_rejection_reason(
            200,
            self.fresh_headers,
            5.0,
            received_unix_ns=received,
        )
        self.assertIn("Date", reason or "")

    def test_freshness_gate_accepts_current_cache_miss(self) -> None:
        self.assertIsNone(freshness_rejection_reason(200, self.fresh_headers, 5.0))

    def test_pin1188_accepts_current_dated_response_without_cf_header(self) -> None:
        headers = {"Date": format_datetime(dt.datetime.now(dt.timezone.utc), usegmt=True)}
        session = _FakeSession([_FakeResponse({"sports": []}, headers=headers)])
        capture = OriginFailover(("https://www.pin1188.com",)).fetch(
            session,
            lambda origin, token: build_sports_url(token, origin=origin),
            purpose="Pin1188 menu",
            token_factory=FreshTokenFactory(clock_ns=lambda: 800),
            attempts=1,
            max_origin_age_seconds=5.0,
        )

        self.assertEqual(capture.freshness["origin"], "https://www.pin1188.com")
        self.assertEqual(capture.freshness["cache_validation"], "current_date_and_unique_url")

    def test_fetch_retries_hit_with_a_new_cache_buster(self) -> None:
        current = _fresh_headers_now()
        hit = _FakeResponse(
            {"l": ["stale"]},
            headers=dict(current, **{"CF-Cache-Status": "HIT"}),
        )
        miss = _FakeResponse({"l": []}, headers=current)
        session = _FakeSession([hit, miss])
        tokens = FreshTokenFactory(clock_ns=lambda: 700)

        capture = fetch_fresh_json(
            session,
            lambda token: build_events_url(33, token),
            purpose="live tennis odds",
            token_factory=tokens,
            attempts=2,
            max_origin_age_seconds=5.0,
        )

        self.assertEqual(capture.body, {"l": []})
        self.assertEqual(len(session.urls), 2)
        self.assertNotEqual(session.urls[0], session.urls[1])
        self.assertEqual(capture.freshness["cf_cache_status"], "MISS")

    def test_origin_failover_is_ordered_and_sticky(self) -> None:
        current = _fresh_headers_now()
        session = _FakeSession(
            [
                _FakeResponse({}, status_code=503, headers=current),
                _FakeResponse({"sports": []}, headers=current),
                _FakeResponse({"sports": []}, headers=current),
            ]
        )
        origins = OriginFailover(
            ("https://www.p4578.com", "https://www.pin1188.com")
        )
        tokens = FreshTokenFactory(clock_ns=lambda: 900)

        first = origins.fetch(
            session,
            lambda origin, token: build_sports_url(token, origin=origin),
            purpose="menu",
            token_factory=tokens,
            attempts=1,
            max_origin_age_seconds=5.0,
        )
        second = origins.fetch(
            session,
            lambda origin, token: build_sports_url(token, origin=origin),
            purpose="menu again",
            token_factory=tokens,
            attempts=1,
            max_origin_age_seconds=5.0,
        )

        self.assertEqual(
            [urlsplit(url).netloc for url in session.urls],
            ["www.p4578.com", "www.pin1188.com", "www.pin1188.com"],
        )
        self.assertEqual(first.freshness["origin"], "https://www.pin1188.com")
        self.assertEqual(second.freshness["origin"], "https://www.pin1188.com")
        self.assertEqual(first.rejected_attempts[0]["origin"], "https://www.p4578.com")


class CompactParserTests(unittest.TestCase):
    @staticmethod
    def compact_event(
        event_id: int = 42,
        home: str = "Home United",
        away: str = "Away City",
    ) -> list[object]:
        periods = {
            "0": [
                [[1.5, -1.5, "1.5", "1.91", "1.95", 1, 0, 701, 0, 100.0, 1]],
                [["22.5", 22.5, "1.87", "1.99", 703, 0, 100.0, 1]],
                ["2.20", "1.80", None, 702, 0, 100.0, 1],
                0,
                "Game",
                1,
                0,
                [0, 0],
                7,
                [1, 0],
                [0, 0],
                1,
            ]
        }
        return [
            event_id,
            home,
            away,
            7,
            1_785_833_000_000,
            1,
            1,
            8,
            periods,
            [1, 0],
            [0, 0],
            [0, 1],
            0,
            None,
            None,
            "18'",
            "1st Set",
            "O",
            0,
            0,
            0,
            18,
            2,
            0,
            home,
            away,
            0,
            "Sets",
            None,
            0,
            0,
        ]

    @classmethod
    def compact_body(cls) -> dict[str, object]:
        return {
            "u": None,
            "l": [
                [
                    33,
                    "Tennis",
                    [
                        [
                            700,
                            "ATP Test League",
                            [
                                cls.compact_event(),
                                cls.compact_event(43, "Other United", "Third Club"),
                            ],
                            None,
                            "ATP Test League",
                            0,
                            None,
                        ]
                    ],
                    1_785_833_100_000,
                    0,
                    None,
                    [],
                    1,
                ]
            ],
            "n": None,
            "e": None,
            "e1": None,
        }

    def test_menu_parses_live_sport_counts(self) -> None:
        menu = {
            "sports": [
                [29, [29, "Soccer", 2, 10]],
                [33, [33, "Tennis", 28, 64]],
            ]
        }
        self.assertEqual(
            parse_sports_menu(menu),
            [
                {
                    "sport_id": 29,
                    "sport_name": "Soccer",
                    "live_event_count": 2,
                    "live_market_count": 10,
                },
                {
                    "sport_id": 33,
                    "sport_name": "Tennis",
                    "live_event_count": 28,
                    "live_market_count": 64,
                },
            ],
        )

    def test_sport_resolver_accepts_name_and_numeric_id(self) -> None:
        sports = parse_sports_menu(
            {"sports": [[29, [29, "Soccer", 2, 10]], [33, [33, "Tennis", 28, 64]]]}
        )
        self.assertEqual(resolve_sport(sports, "tennis")["sport_id"], 33)
        self.assertEqual(resolve_sport(sports, "29")["sport_name"], "Soccer")

    def test_normalizes_compact_event_and_primary_markets(self) -> None:
        sport = normalize_sport_feed(self.compact_body())[0]
        event = sport["leagues"][0]["events"][0]
        period = event["periods"][0]

        self.assertEqual(event["event_id"], 42)
        self.assertEqual(event["match_name"], "Home United vs Away City")
        self.assertEqual(event["score"], {"home": 1, "away": 0})
        self.assertEqual(event["running_time"], "18'")
        self.assertEqual(period["moneyline"]["home_odds"], "1.80")
        self.assertEqual(period["moneyline"]["away_odds"], "2.20")
        self.assertEqual(period["spreads"][0]["line_id"], 701)
        self.assertEqual(period["totals"][0]["over_odds"], "1.87")

    def test_all_market_feed_merges_live_and_normal_sections(self) -> None:
        body = self.compact_body()
        body["n"] = [
            [
                33,
                "Tennis",
                [
                    [
                        700,
                        "ATP Test League",
                        [self.compact_event(99, "Pregame Home", "Pregame Away")],
                        None,
                        "ATP Test League",
                        0,
                        None,
                    ]
                ],
                1_785_833_100_001,
                0,
                None,
                [],
                1,
            ]
        ]

        sport = normalize_sport_feed(body)[0]
        events = sport["leagues"][0]["events"]

        self.assertEqual([event["event_id"] for event in events], [42, 43, 99])
        self.assertEqual(
            [event["market_section"] for event in events],
            ["live", "live", "normal"],
        )

    def test_normalizes_detailed_period_layout(self) -> None:
        detailed = [
            [["team-total-raw"]],
            [{"special": "raw"}],
            [[0.5, -0.5, "0.5", "1.80", "2.00", 1, 0, 801, 1, 300.0, 1]],
            [["4.5", 4.5, "1.75", "2.05", 802, 1, 300.0, 1]],
            ["2.30", "1.70", None, 803, 1, 300.0, 1],
            0,
            "Game",
            1,
            0,
            0,
            11,
            [3, 0],
            [0, 1],
            2,
        ]
        period = normalize_period("0", detailed)

        self.assertEqual(period["layout"], "match_detail")
        self.assertEqual(period["spreads"][0]["line_id"], 801)
        self.assertEqual(period["totals"][0]["line_id"], 802)
        self.assertEqual(period["moneyline"]["line_id"], 803)
        self.assertEqual(period["team_totals_raw"], [["team-total-raw"]])
        self.assertEqual(period["specials_raw"], [{"special": "raw"}])

    def test_league_filter_accepts_competition_name_or_id(self) -> None:
        sport = normalize_sport_feed(self.compact_body())[0]
        self.assertEqual(filter_leagues(sport, "ATP")["leagues"][0]["league_id"], 700)
        self.assertEqual(filter_leagues(sport, "700")["leagues"][0]["league_name"], "ATP Test League")

    def test_match_selector_rejects_ambiguous_substring(self) -> None:
        sport = normalize_sport_feed(self.compact_body())[0]
        with self.assertRaisesRegex(SelectionError, "ambiguous"):
            select_single_event(sport, "united")

    def test_match_selector_accepts_exact_event_id(self) -> None:
        sport = normalize_sport_feed(self.compact_body())[0]
        league, event = select_single_event(sport, "43")
        self.assertEqual(league["league_id"], 700)
        self.assertEqual(event["match_name"], "Other United vs Third Club")


class CommandContractTests(unittest.TestCase):
    def test_cli_accepts_competition_comp_and_league_aliases(self) -> None:
        parser = build_argument_parser()
        for flag in ("--competition", "--comp", "--league"):
            with self.subTest(flag=flag):
                args = parser.parse_args(["--sport", "tennis", flag, "ATP"])
                self.assertEqual(args.league, "ATP")

    def test_cli_defaults_to_all_markets_and_accepts_mk_override(self) -> None:
        parser = build_argument_parser()
        self.assertEqual(parser.parse_args(["--sport", "tennis"]).mk, 3)
        self.assertEqual(parser.parse_args(["--sport", "tennis", "--mk", "1"]).mk, 1)

    def test_detail_feed_uses_selected_names_and_richer_event(self) -> None:
        event = CompactParserTests.compact_event()
        event[8]["0"] = [
            [["team-total"]],
            None,
            [[0.5, -0.5, "0.5", "1.80", "2.00", 1, 0, 801, 1, 300.0, 1]],
            [],
            ["2.30", "1.70", None, 803, 1, 300.0, 1],
            0,
            "Game",
            1,
            0,
            0,
            11,
            [3, 0],
            [0, 1],
            2,
        ]
        detail = normalize_detail_feed(
            {"e": [33, 700, 0, event, 1_785_833_200_000]},
            sport_name="Tennis",
            league_name="ATP Test League",
        )
        self.assertEqual(detail["sport_id"], 33)
        self.assertEqual(detail["leagues"][0]["league_name"], "ATP Test League")
        self.assertEqual(
            detail["leagues"][0]["events"][0]["periods"][0]["layout"],
            "match_detail",
        )

    def test_run_query_preserves_raw_bodies_and_fetches_match_detail(self) -> None:
        headers = _fresh_headers_now()
        menu = {"sports": [[33, [33, "Tennis", 2, 7]]]}
        sport_body = CompactParserTests.compact_body()
        detail_body = {
            "e": [
                33,
                700,
                0,
                CompactParserTests.compact_event(42),
                1_785_833_200_000,
            ]
        }
        session = _FakeSession(
            [
                _FakeResponse(menu, headers=headers),
                _FakeResponse(sport_body, headers=headers),
                _FakeResponse(detail_body, headers=headers),
            ]
        )
        args = Namespace(
            sport="tennis",
            league="ATP Test",
            match="42",
            mk=3,
            fresh_attempts=3,
            max_origin_age=5.0,
        )

        raw, parsed = run_query(args, session=session)

        self.assertEqual([item["body"] for item in raw["requests"]], [menu, sport_body, detail_body])
        self.assertEqual(parsed["sport"]["leagues"][0]["events"][0]["event_id"], 42)
        self.assertEqual(parsed["selection"]["event_id"], 42)
        self.assertEqual(raw["origins_used"], ["https://www.p4578.com"])
        self.assertEqual(
            [item["origin"] for item in raw["requests"]],
            ["https://www.p4578.com"] * 3,
        )
        self.assertFalse(parsed["freshness"]["fallback_used"])
        self.assertEqual(len(session.urls), 3)
        tokens = [parse_qs(urlsplit(url).query)["_"][0] for url in session.urls]
        self.assertEqual(len(tokens), len(set(tokens)))
        detail_query = parse_qs(urlsplit(session.urls[-1]).query)
        self.assertTrue(all(parse_qs(urlsplit(url).query).get("mk", ["3"])[0] == "3" for url in session.urls))
        self.assertEqual(detail_query["more"], ["true"])
        self.assertEqual(detail_query["me"], ["42"])

    def test_atomic_json_writer_creates_readable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output.json"
            write_json_atomic(path, {"answer": 42})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"answer": 42})


def _run_self_tests() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
