"""Parse Pinnacle compact API payloads into normalized structures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from deltax.pinnacle.protocol import PinnacleProtocolError, SelectionError


def _at(values: Any, index: int, default: Any = None) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return default


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _utc_from_epoch_ms(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        stamp = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
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

            leagues_by_id = {league["league_id"]: league for league in sport["leagues"]}
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
                existing_event_ids = {event["event_id"] for event in league["events"]}
                for event_row in event_rows:
                    event = normalize_event(event_row, market_section=market_section)
                    if event["event_id"] not in existing_event_ids:
                        league["events"].append(event)
                        existing_event_ids.add(event["event_id"])
    return sports


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


def sport_by_id(sports: list[dict[str, Any]], sport_id: int) -> dict[str, Any] | None:
    for sport in sports:
        if sport.get("sport_id") == sport_id:
            return sport
    return None


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


def parse_corner_event_from_detail(body: Any, *, market_section: str = "normal") -> dict[str, Any] | None:
    """Return the corners sub-event from a match-detail response (`ce` row), if present."""
    corner = body.get("ce") if isinstance(body, dict) else None
    if not isinstance(corner, list) or len(corner) < 4:
        return None
    event_row = _at(corner, 3)
    if not isinstance(event_row, list):
        return None
    try:
        return normalize_event(event_row, market_section=market_section)
    except PinnacleProtocolError:
        return None


def bulk_feed_mentions_corners(body: Any) -> bool:
    """True when the compact l/n snapshot JSON contains corner-related strings."""
    if not isinstance(body, dict):
        return False
    for section in ("l", "n"):
        rows = body.get(section)
        if not isinstance(rows, list):
            continue
        for sport_row in rows:
            league_rows = _at(sport_row, 2)
            if not isinstance(league_rows, list):
                continue
            for league_row in league_rows:
                league_name = _text(_at(league_row, 1))
                if league_name and "corner" in league_name.casefold():
                    return True
                event_rows = _at(league_row, 2)
                if not isinstance(event_rows, list):
                    continue
                for event_row in event_rows:
                    home = _text(_at(event_row, 1))
                    away = _text(_at(event_row, 2))
                    match_name = f"{home or ''} {away or ''}".casefold()
                    if "corner" in match_name:
                        return True
    return False
