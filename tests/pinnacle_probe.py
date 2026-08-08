"""Shared helpers for exploratory Pinnacle API probes (corners, live odds)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from deltax.pinnacle.client import PinnacleClient
from deltax.pinnacle.flatten import flatten_selections
from deltax.pinnacle.parser import (
    bulk_feed_mentions_corners,
    normalize_sport_feed,
    parse_corner_event_from_detail,
    sport_by_id,
)

SOCCER_SPORT_ID = 29
TENNIS_SPORT_ID = 33

# Corners only appear on match-detail `ce` rows. In practice they correlate with
# richer main-match menus: bulk prematch rows below this threshold did not expose
# corners in live API probes (Aug 2026).
DEFAULT_CORNER_MORE_BET_MIN = 30


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


def sample_event_odds(event: dict[str, Any]) -> tuple[float, ...]:
    period = (event.get("periods") or [{}])[0]
    moneyline = period.get("moneyline") or {}
    odds = [
        _parse_odd(moneyline.get("home_odds")),
        _parse_odd(moneyline.get("away_odds")),
        _parse_odd(moneyline.get("draw_odds")),
    ]
    for bucket in ("spreads", "totals"):
        for line in period.get(bucket) or []:
            for key in ("home_odds", "away_odds", "over_odds", "under_odds"):
                odd = _parse_odd(line.get(key))
                if odd is not None:
                    odds.append(odd)
    return tuple(odd for odd in odds if odd is not None)


def iter_prematch_events(
    sports: list[dict[str, Any]],
    *,
    sport_id: int,
) -> list[dict[str, Any]]:
    sport = sport_by_id(sports, sport_id)
    if sport is None:
        return []
    rows: list[dict[str, Any]] = []
    for league in sport.get("leagues") or []:
        for event in league.get("events") or []:
            if event.get("market_section") != "normal":
                continue
            rows.append(
                {
                    "sport": sport,
                    "league": league,
                    "event": event,
                    "more_bet_count": int(event.get("more_bet_count") or 0),
                }
            )
    return rows


def select_corner_detail_candidates(
    prematch_rows: list[dict[str, Any]],
    *,
    more_bet_min: int = DEFAULT_CORNER_MORE_BET_MIN,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Pick main-match rows worth a detail fetch when hunting corner `ce` markets."""
    filtered = [row for row in prematch_rows if row["more_bet_count"] >= more_bet_min]
    filtered.sort(key=lambda row: row["more_bet_count"], reverse=True)
    if limit is not None:
        return filtered[:limit]
    return filtered


@dataclass(frozen=True)
class CornerScopeProbeResult:
    bulk_feed_has_corners: bool
    prematch_events_total: int
    more_bet_min: int
    candidate_events: int
    detail_fetches: int
    corners_with_lines: int
    leagues_with_corners: tuple[tuple[str, int], ...]
    sample_corner_match: str | None
    sample_corner_templates: tuple[str, ...]
    detail_calls_saved_vs_full_scan: int

    @property
    def corner_hit_rate(self) -> float:
        if self.detail_fetches <= 0:
            return 0.0
        return self.corners_with_lines / self.detail_fetches


@dataclass(frozen=True)
class CornerProbeResult:
    bulk_feed_has_corners: bool
    detail_events_checked: int
    detail_with_corner_event: int
    corner_events_with_lines: int
    sample_corner_match: str | None
    sample_corner_templates: tuple[str, ...]


def probe_soccer_corner_scope(
    client: PinnacleClient,
    *,
    market_kind: int = 1,
    more_bet_min: int = DEFAULT_CORNER_MORE_BET_MIN,
    max_detail_fetches: int | None = None,
) -> CornerScopeProbeResult:
    """Efficient prematch corner discovery: bulk mk feed, then detail only for rich menus."""
    body = client.fetch_events(SOCCER_SPORT_ID, market_kind)
    if body is None:
        raise RuntimeError("Pinnacle soccer bulk feed unavailable")

    bulk_has_corners = bulk_feed_mentions_corners(body)
    sports = normalize_sport_feed(body)
    prematch_rows = iter_prematch_events(sports, sport_id=SOCCER_SPORT_ID)
    candidates = select_corner_detail_candidates(
        prematch_rows,
        more_bet_min=more_bet_min,
        limit=max_detail_fetches,
    )

    league_hits: Counter[str] = Counter()
    corners_with_lines = 0
    sample_match: str | None = None
    sample_templates: tuple[str, ...] = ()

    for candidate in candidates:
        event_id = int(candidate["event"]["event_id"])
        detail = client.fetch_event_detail(
            SOCCER_SPORT_ID,
            event_id,
            market_kind=market_kind,
        )
        if detail is None:
            continue
        corner_event = parse_corner_event_from_detail(detail, market_section="normal")
        if corner_event is None:
            continue
        open_lines = count_open_lines(corner_event)
        if open_lines <= 0:
            continue
        corners_with_lines += 1
        league_hits[str(candidate["league"].get("league_name") or "unknown")] += 1
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

    all_candidates = select_corner_detail_candidates(
        prematch_rows,
        more_bet_min=more_bet_min,
    )
    return CornerScopeProbeResult(
        bulk_feed_has_corners=bulk_has_corners,
        prematch_events_total=len(prematch_rows),
        more_bet_min=more_bet_min,
        candidate_events=len(all_candidates),
        detail_fetches=len(candidates),
        corners_with_lines=corners_with_lines,
        leagues_with_corners=tuple(league_hits.most_common()),
        sample_corner_match=sample_match,
        sample_corner_templates=sample_templates,
        detail_calls_saved_vs_full_scan=max(len(prematch_rows) - len(all_candidates), 0),
    )


def probe_soccer_corners(
    client: PinnacleClient,
    *,
    market_kind: int = 1,
    candidate_limit: int = 12,
) -> CornerProbeResult:
    scope = probe_soccer_corner_scope(
        client,
        market_kind=market_kind,
        more_bet_min=DEFAULT_CORNER_MORE_BET_MIN,
        max_detail_fetches=candidate_limit,
    )
    return CornerProbeResult(
        bulk_feed_has_corners=scope.bulk_feed_has_corners,
        detail_events_checked=scope.detail_fetches,
        detail_with_corner_event=scope.corners_with_lines,
        corner_events_with_lines=scope.corners_with_lines,
        sample_corner_match=scope.sample_corner_match,
        sample_corner_templates=scope.sample_corner_templates,
    )


@dataclass(frozen=True)
class LiveProbeResult:
    sport_id: int
    live_events: int
    live_events_with_lines: int
    sample_live_match: str | None
    sample_live_odds: tuple[float, ...]
    flatten_live_rows: int
    leagues_with_live: tuple[tuple[str, int], ...] = field(default_factory=tuple)


def probe_live_odds(
    client: PinnacleClient,
    *,
    sport_id: int,
    market_kind: int = 2,
) -> LiveProbeResult:
    body = client.fetch_events(sport_id, market_kind)
    if body is None:
        raise RuntimeError(f"Pinnacle live feed unavailable sport_id={sport_id} mk={market_kind}")

    sports = normalize_sport_feed(body)
    sport = sport_by_id(sports, sport_id)
    if sport is None:
        return LiveProbeResult(sport_id, 0, 0, None, (), 0)

    live_events: list[dict[str, Any]] = []
    league_counts: Counter[str] = Counter()
    for league in sport.get("leagues") or []:
        for event in league.get("events") or []:
            if event.get("market_section") == "live":
                live_events.append(event)
                league_counts[str(league.get("league_name") or "unknown")] += 1

    with_lines = [event for event in live_events if count_open_lines(event) > 0]
    sample_match: str | None = None
    sample_odds: tuple[float, ...] = ()
    if with_lines:
        sample = with_lines[0]
        sample_match = str(sample.get("match_name") or "")
        sample_odds = sample_event_odds(sample)

    flatten_rows = flatten_selections(sports, prematch_only=False)
    live_flatten_rows = sum(
        1
        for row in flatten_rows
        if row.tipsport_snapshot.get("market_section") == "live"
    )

    return LiveProbeResult(
        sport_id=sport_id,
        live_events=len(live_events),
        live_events_with_lines=len(with_lines),
        sample_live_match=sample_match,
        sample_live_odds=sample_odds,
        flatten_live_rows=live_flatten_rows,
        leagues_with_live=tuple(league_counts.most_common()),
    )


def probe_tennis_live_odds(client: PinnacleClient) -> LiveProbeResult:
    return probe_live_odds(client, sport_id=TENNIS_SPORT_ID, market_kind=2)


def probe_soccer_live_odds(client: PinnacleClient) -> LiveProbeResult:
    return probe_live_odds(client, sport_id=SOCCER_SPORT_ID, market_kind=2)
