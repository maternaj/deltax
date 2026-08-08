"""Exploratory probes: soccer corner markets via Pinnacle compact API."""

from __future__ import annotations

import os

import pytest

from deltax.pinnacle.flatten import flatten_selections
from deltax.pinnacle.parser import (
    bulk_feed_mentions_corners,
    normalize_sport_feed,
    parse_corner_event_from_detail,
)
from pinnacle_feeds import prematch_parent_detail_body, prematch_soccer_body
from pinnacle_probe import (
    DEFAULT_CORNER_MORE_BET_MIN,
    probe_soccer_corner_scope,
    probe_soccer_corners,
    select_corner_detail_candidates,
)


def test_bulk_snapshot_does_not_surface_corners() -> None:
    body = prematch_soccer_body()
    assert bulk_feed_mentions_corners(body) is False
    sports = normalize_sport_feed(body)
    names = {
        event.get("match_name")
        for sport in sports
        for league in sport.get("leagues") or []
        for event in league.get("events") or []
    }
    assert not any("corner" in str(name).casefold() for name in names)


def test_detail_ce_row_parses_corner_event_and_flattens() -> None:
    body = prematch_parent_detail_body()
    corner = parse_corner_event_from_detail(body, market_section="normal")
    assert corner is not None
    assert corner["event_id"] == 1633377443
    assert "(Corners)" in corner["home"]
    assert corner["periods"][0]["layout"] == "match_detail"

    rows = flatten_selections(
        [
            {
                "sport_id": 29,
                "sport_name": "Soccer",
                "leagues": [
                    {
                        "league_id": 6310,
                        "league_name": "Brazil - Serie A",
                        "events": [corner],
                    }
                ],
            }
        ],
        prematch_only=True,
        main_lines_only=True,
    )
    templates = {row.my_selection_id for row in rows}
    assert "29-0-TOTAL-OVER" in templates
    assert "29-0-TOTAL-UNDER" in templates
    assert "29-0-SPREAD-HOME" in templates


def test_corner_candidates_use_more_bet_threshold() -> None:
    rows = [
        {"more_bet_count": 49, "event": {"event_id": 1}},
        {"more_bet_count": 31, "event": {"event_id": 2}},
        {"more_bet_count": 18, "event": {"event_id": 3}},
        {"more_bet_count": 41, "event": {"event_id": 4}},
    ]
    picked = select_corner_detail_candidates(rows, more_bet_min=30)
    assert [row["event"]["event_id"] for row in picked] == [1, 4, 2]
    assert DEFAULT_CORNER_MORE_BET_MIN == 30


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DELTAX_PINNACLE_PROBE", "").lower() not in {"1", "true", "yes"},
    reason="set DELTAX_PINNACLE_PROBE=1 to run live Pinnacle corner probes",
)
def test_live_api_exposes_prematch_corner_markets_via_event_detail() -> None:
    from deltax.pinnacle.client import PinnacleClient

    client = PinnacleClient(fresh_attempts=2, max_origin_age_seconds=5.0)
    try:
        result = probe_soccer_corners(client, candidate_limit=8)
    finally:
        client.close()

    assert result.bulk_feed_has_corners is False
    assert result.detail_events_checked > 0
    assert result.detail_with_corner_event > 0, (
        "expected at least one prematch soccer detail response with a ce corner row"
    )
    assert result.corner_events_with_lines > 0, (
        "expected parseable corner handicap/total lines from detail ce rows"
    )
    assert result.sample_corner_match
    assert "corner" in result.sample_corner_match.casefold()
    assert result.sample_corner_templates


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DELTAX_PINNACLE_PROBE", "").lower() not in {"1", "true", "yes"},
    reason="set DELTAX_PINNACLE_PROBE=1 to run live Pinnacle corner scope probes",
)
def test_efficient_corner_scope_uses_more_bet_gate_not_full_scan() -> None:
    from deltax.pinnacle.client import PinnacleClient

    client = PinnacleClient(fresh_attempts=2, max_origin_age_seconds=5.0)
    try:
        result = probe_soccer_corner_scope(
            client,
            more_bet_min=DEFAULT_CORNER_MORE_BET_MIN,
            max_detail_fetches=25,
        )
    finally:
        client.close()

    assert result.bulk_feed_has_corners is False
    assert result.prematch_events_total > result.candidate_events, (
        "corners are sparse; detail gate should skip low-menu prematch rows"
    )
    assert result.detail_calls_saved_vs_full_scan > 0
    assert result.detail_fetches <= 25
    assert result.corners_with_lines > 0
    assert result.corner_hit_rate >= 0.8, (
        f"more_bet_count>={DEFAULT_CORNER_MORE_BET_MIN} should mostly expose ce rows; "
        f"got {result.corner_hit_rate:.0%} over {result.detail_fetches} fetches"
    )
    assert result.leagues_with_corners, "expected league breakdown for corner offers"
