"""Pinnacle parser and flatten tests."""

from deltax.pinnacle.flatten import (
    build_my_selection_id,
    flatten_selections,
    is_prematch_event,
    stable_opp_id,
)
from deltax.pinnacle.parser import normalize_sport_feed
from pinnacle_feeds import mixed_live_and_prematch_body, prematch_soccer_body


def test_normalize_prematch_soccer_feed() -> None:
    sports = normalize_sport_feed(prematch_soccer_body())
    assert len(sports) == 1
    sport = sports[0]
    assert sport["sport_id"] == 29
    assert len(sport["leagues"]) == 1
    event = sport["leagues"][0]["events"][0]
    assert event["market_section"] == "normal"
    assert event["running"] == 0
    assert event["live"] == 0


def test_flatten_prematch_main_lines() -> None:
    sports = normalize_sport_feed(prematch_soccer_body())
    rows = flatten_selections(
        sports,
        prematch_only=True,
        main_lines_only=True,
        match_url_base="https://www.ps3838.com/en",
        sport_slug_overrides={29: "soccer"},
    )
    templates = {row.my_selection_id for row in rows}
    assert "29-0-MONEYLINE-HOME" in templates
    assert "29-0-MONEYLINE-AWAY" in templates
    assert "29-0-MONEYLINE-DRAW" in templates
    assert "29-0-SPREAD-HOME" in templates
    assert "29-0-TOTAL-OVER" in templates
    assert rows[0].match_type == "PREMATCH"
    assert rows[0].tipsport_snapshot["source"] == "pinnacle"
    assert rows[0].match_url.startswith(
        "https://www.ps3838.com/en/sports/soccer/matchup/England-Premier-League/"
    )
    assert rows[0].match_url.endswith("/1980/999001")


def test_flatten_skips_live_section_events() -> None:
    sports = normalize_sport_feed(mixed_live_and_prematch_body())
    all_rows = flatten_selections(sports, prematch_only=True)
    event_ids = {row.match_id for row in all_rows}
    assert 999001 in event_ids
    assert 999002 not in event_ids


def test_is_prematch_event_rejects_live_flags() -> None:
    sports = normalize_sport_feed(mixed_live_and_prematch_body())
    live_event = sports[0]["leagues"][0]["events"][0]
    assert live_event["market_section"] == "live"
    assert not is_prematch_event(live_event, prematch_only=True)


def test_stable_opp_id_is_deterministic() -> None:
    template = build_my_selection_id(29, "0", "MONEYLINE", "HOME")
    assert stable_opp_id(999001, template) == stable_opp_id(999001, template)
    assert stable_opp_id(999001, template) != stable_opp_id(999001, template.replace("HOME", "AWAY"))


def test_league_allow_name_substrings() -> None:
    sports = normalize_sport_feed(prematch_soccer_body())
    rows = flatten_selections(
        sports,
        league_allow_name_substrings=("Bundesliga",),
    )
    assert rows == []

    rows = flatten_selections(
        sports,
        league_allow_name_substrings=("Premier",),
    )
    assert len(rows) >= 5
