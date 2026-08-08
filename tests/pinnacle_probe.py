"""Shared helpers for exploratory Pinnacle API probes (corners, live odds)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deltax.pinnacle.client import PinnacleClient
from deltax.pinnacle.flatten import flatten_selections
from deltax.pinnacle.parser import (
    bulk_feed_mentions_corners,
    normalize_sport_feed,
    parse_corner_event_from_detail,
    sport_by_id,
)


def _parse_odd(value: Any) -> float | None:
    if value is None:
        return None
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    if odd <= 1.0:
        return None
    return odd


def count_open_lines(event: dict[str, Any]) -> int:
    total = 0
    for period in event.get("periods") or []:
        moneyline = period.get("moneyline")
        if isinstance(moneyline, dict):
            for key in ("home_odds", "away_odds", "draw_odds"):
                if _parse_odd(moneyline.get(key)) is not None:
                    total += 1
        for bucket in ("spreads", "totals"):
            for line in period.get(bucket) or []:
                for key in ("home_odds", "away_odds", "over_odds", "under_odds"):
                    if _parse_odd(line.get(key)) is not None:
                        total += 1
    return total


def prematch_candidates(sports: list[dict[str, Any]], *, limit: int = 25) -> list[dict[str, Any]]:
    rows: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    soccer = sport_by_id(sports, 29)
    if soccer is None:
        return []
    for league in soccer.get("leagues") or []:
        for event in league.get("events") or []:
            if event.get("market_section") != "normal":
                continue
            more_bets = int(event.get("more_bet_count") or 0)
            rows.append((more_bets, league, event, soccer))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "sport": sport,
            "league": league,
            "event": event,
            "more_bet_count": more_bets,
        }
        for more_bets, league, event, sport in rows[:limit]
    ]


@dataclass(frozen=True)
class CornerProbeResult:
    bulk_feed_has_corners: bool
    detail_events_checked: int
    detail_with_corner_event: int
    corner_events_with_lines: int
    sample_corner_match: str | None
    sample_corner_templates: tuple[str, ...]


def probe_soccer_corners(
    client: PinnacleClient,
    *,
    market_kind: int = 1,
    candidate_limit: int = 12,
) -> CornerProbeResult:
    body = client.fetch_events(29, market_kind)
    if body is None:
        raise RuntimeError("Pinnacle soccer bulk feed unavailable")

    bulk_has_corners = bulk_feed_mentions_corners(body)
    sports = normalize_sport_feed(body)
    candidates = prematch_candidates(sports, limit=candidate_limit)

    detail_with_corner = 0
    corner_with_lines = 0
    sample_match: str | None = None
    sample_templates: tuple[str, ...] = ()

    for candidate in candidates:
        event_id = int(candidate["event"]["event_id"])
        detail = client.fetch_event_detail(29, event_id, market_kind=market_kind)
        if detail is None:
            continue
        corner_event = parse_corner_event_from_detail(detail, market_section="normal")
        if corner_event is None:
            continue
        detail_with_corner += 1
        open_lines = count_open_lines(corner_event)
        if open_lines <= 0:
            continue
        corner_with_lines += 1
        if sample_match is None:
            sample_match = str(corner_event.get("match_name") or "")
            sport = candidate["sport"]
            league = candidate["league"]
            rows = flatten_selections(
                [
                    {
                        "sport_id": sport["sport_id"],
                        "sport_name": sport["sport_name"],
                        "leagues": [
                            {
                                "league_id": league["league_id"],
                                "league_name": league["league_name"],
                                "events": [corner_event],
                            }
                        ],
                    }
                ],
                prematch_only=True,
                main_lines_only=True,
            )
            sample_templates = tuple(sorted({row.my_selection_id for row in rows}))

    return CornerProbeResult(
        bulk_feed_has_corners=bulk_has_corners,
        detail_events_checked=len(candidates),
        detail_with_corner_event=detail_with_corner,
        corner_events_with_lines=corner_with_lines,
        sample_corner_match=sample_match,
        sample_corner_templates=sample_templates,
    )


@dataclass(frozen=True)
class LiveProbeResult:
    live_events: int
    live_events_with_lines: int
    sample_live_match: str | None
    sample_live_odds: tuple[float, ...]
    flatten_live_rows: int


def probe_soccer_live_odds(client: PinnacleClient) -> LiveProbeResult:
    body = client.fetch_events(29, 2)
    if body is None:
        raise RuntimeError("Pinnacle soccer live feed (mk=2) unavailable")

    sports = normalize_sport_feed(body)
    soccer = sport_by_id(sports, 29)
    if soccer is None:
        return LiveProbeResult(0, 0, None, (), 0)

    live_events: list[dict[str, Any]] = []
    for league in soccer.get("leagues") or []:
        for event in league.get("events") or []:
            if event.get("market_section") == "live":
                live_events.append(event)

    with_lines = [event for event in live_events if count_open_lines(event) > 0]
    sample_match: str | None = None
    sample_odds: tuple[float, ...] = ()
    if with_lines:
        sample = with_lines[0]
        sample_match = str(sample.get("match_name") or "")
        period = (sample.get("periods") or [{}])[0]
        moneyline = period.get("moneyline") or {}
        sample_odds = tuple(
            odd
            for odd in (
                _parse_odd(moneyline.get("home_odds")),
                _parse_odd(moneyline.get("away_odds")),
                _parse_odd(moneyline.get("draw_odds")),
            )
            if odd is not None
        )

    flatten_rows = flatten_selections(sports, prematch_only=False)
    live_flatten_rows = sum(
        1
        for row in flatten_rows
        if row.tipsport_snapshot.get("market_section") == "live"
    )

    return LiveProbeResult(
        live_events=len(live_events),
        live_events_with_lines=len(with_lines),
        sample_live_match=sample_match,
        sample_live_odds=sample_odds,
        flatten_live_rows=live_flatten_rows,
    )
