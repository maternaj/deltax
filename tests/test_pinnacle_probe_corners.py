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
from pinnacle_probe import probe_soccer_corners


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
