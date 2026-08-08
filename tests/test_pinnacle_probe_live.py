"""Exploratory probes: live/in-play soccer odds via Pinnacle compact API."""

from __future__ import annotations

import os

import pytest

from deltax.pinnacle.flatten import flatten_selections, is_prematch_event
from deltax.pinnacle.parser import normalize_sport_feed
from pinnacle_feeds import live_event, mixed_live_and_prematch_body
from pinnacle_probe import probe_soccer_live_odds


def test_live_section_events_are_filtered_by_flatten_and_is_prematch() -> None:
    sports = normalize_sport_feed(mixed_live_and_prematch_body())
    live = sports[0]["leagues"][0]["events"][0]
    assert live["market_section"] == "live"
    assert live["running"] == 1
    assert is_prematch_event(live, prematch_only=False) is False

    rows = flatten_selections(sports, prematch_only=False)
    assert all(row.tipsport_snapshot.get("market_section") != "live" for row in rows)


def test_live_event_fixture_carries_open_lines() -> None:
    body = {
        "u": None,
        "l": [
            [
                29,
                "Soccer",
                [
                    [
                        1980,
                        "Test League",
                        [live_event()],
                        None,
                        "Test League",
                        0,
                        None,
                    ]
                ],
                0,
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
    sports = normalize_sport_feed(body)
    event = sports[0]["leagues"][0]["events"][0]
    period = event["periods"][0]
    assert period["moneyline"]["home_odds"] is not None
    assert len(period["spreads"]) >= 1
    assert len(period["totals"]) >= 1


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("DELTAX_PINNACLE_PROBE", "").lower() not in {"1", "true", "yes"},
    reason="set DELTAX_PINNACLE_PROBE=1 to run live Pinnacle in-play probes",
)
def test_live_api_exposes_inplay_soccer_odds_outside_flatten_pipeline() -> None:
    from deltax.pinnacle.client import PinnacleClient

    client = PinnacleClient(fresh_attempts=2, max_origin_age_seconds=5.0)
    try:
        result = probe_soccer_live_odds(client)
    finally:
        client.close()

    assert result.live_events > 0, "expected mk=2 soccer feed to include live-section events"
    assert result.live_events_with_lines > 0, (
        "expected live events to carry moneyline/spread/total odds in normalized parser output"
    )
    assert result.sample_live_match
    assert result.sample_live_odds, "expected at least one live moneyline price > 1.0"
    assert result.flatten_live_rows == 0, (
        "current flatten_selections intentionally skips market_section=live; "
        "live odds must be consumed from normalized feeds or a future in-play flatten path"
    )
