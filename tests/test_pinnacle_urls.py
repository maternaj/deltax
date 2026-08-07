"""Pinnacle / PS3838 deeplink builder tests."""

from deltax.pinnacle.parser import normalize_sport_feed
from deltax.pinnacle.urls import (
    build_event_slug,
    build_match_url,
    detect_match_url_style,
    ps3838_path_slug,
    slugify,
)
from pinnacle_feeds import prematch_soccer_body


def test_ps3838_path_slug_matches_site_algorithm() -> None:
    assert ps3838_path_slug("Scotland - Championship") == "Scotland-Championship"
    assert (
        build_event_slug("Dunfermline Athletic", "Ayr United", style="stats")
        == "Dunfermline-Athletic-vs-Ayr-United"
    )
    assert build_event_slug("Team A (Corners)", "Team B", style="stats") == "Team-A-vs-Team-B"


def test_slugify_normalizes_for_pinnacle_classic() -> None:
    assert slugify("Brazil - Mineiro U20") == "brazil-mineiro-u20"
    assert build_event_slug("Cruzeiro", "Itabirito", style="classic") == "cruzeiro-vs-itabirito"


def test_detect_match_url_style() -> None:
    assert detect_match_url_style("https://www.ps3838.com/en") == "stats"
    assert detect_match_url_style("https://www.ps3838.com/en/compact") == "stats"
    assert detect_match_url_style("https://www.pinnacle.com/en") == "classic"


def test_build_match_url_ps3838_stats_from_user_example() -> None:
    url = build_match_url(
        match_url_base="https://www.ps3838.com/en",
        sport={"sport_id": 29, "sport_name": "Soccer"},
        league={"league_id": 2417, "league_name": "Scotland - Championship"},
        event={
            "event_id": 1633177769,
            "home": "Dunfermline Athletic",
            "away": "Ayr United",
        },
        sport_slug_overrides={29: "soccer"},
    )
    assert url == (
        "https://www.ps3838.com/en/sports/soccer/stats/"
        "Scotland-Championship/Dunfermline-Athletic-vs-Ayr-United/1633177769"
    )


def test_build_match_url_ps3838_stats_from_feed_fixture() -> None:
    sports = normalize_sport_feed(prematch_soccer_body())
    sport = sports[0]
    league = sport["leagues"][0]
    event = league["events"][0]

    url = build_match_url(
        match_url_base="https://www.ps3838.com/en",
        sport=sport,
        league=league,
        event=event,
        sport_slug_overrides={29: "soccer"},
    )

    assert url == (
        "https://www.ps3838.com/en/sports/soccer/stats/"
        "England-Premier-League/Arsenal-vs-Chelsea/999001"
    )


def test_build_match_url_pinnacle_classic() -> None:
    sports = normalize_sport_feed(prematch_soccer_body())
    sport = sports[0]
    league = sport["leagues"][0]
    event = league["events"][0]

    url = build_match_url(
        match_url_base="https://www.pinnacle.com/en",
        sport=sport,
        league=league,
        event=event,
        style="classic",
        sport_slug_overrides={29: "soccer"},
    )

    assert url == (
        "https://www.pinnacle.com/en/soccer/england-premier-league/"
        "arsenal-vs-chelsea/999001/"
    )
