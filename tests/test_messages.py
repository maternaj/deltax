"""Message and Telegram helper tests."""

from deltax.config import DropTier
from deltax.drop_detector import DropHit
from deltax.messages import (
    drop_window_minutes,
    format_drop_alert_message,
    format_kickoff_prague,
    format_line4_timing,
    format_match_url,
    format_time_to_kickoff,
    match_phase_emoji,
    selection_icon,
    sport_emoji,
)
from deltax.parser import SelectionRow, TrackedSelection
from deltax.telegram import TelegramSender, parse_telegram_groups


def _tracked(**overrides: object) -> TrackedSelection:
    base = {
        "opp_id": 2664187029,
        "event_id": 10,
        "match_id": 8302416,
        "my_selection_id": "16-TOTAL_PARTICIPANT-1",
        "match_name": "Arsenal - Chelsea",
        "home_participant": "Arsenal",
        "visiting_participant": "Chelsea",
        "competition_name": "Premier League",
        "sport_name": "Fotbal",
        "super_sport_name": "Fotbal",
        "match_type": "PREMATCH",
        "event_name": "Celkový počet gólů hráče",
        "opp_name": "Hráč X - více než 0.5",
        "odd": 1.73,
        "betting_enabled": True,
        "opp_type": "1",
        "opp_number": None,
        "match_url": "/kurzy/zapas/arsenal-chelsea/8302416",
        "date_start": 1775395800000,
    }
    base.update(overrides)
    return TrackedSelection(**base)


def _drop_hit(row: TrackedSelection, **overrides: object) -> DropHit:
    base = {
        "opp_id": row.opp_id,
        "match_id": row.match_id,
        "my_selection_id": row.my_selection_id,
        "drop_pct": 10.0,
        "implied_drop_pct": 5.2,
        "odds_previous": 1.92,
        "odds_now": 1.73,
        "baseline_observed_at": 1000.0,
        "current_observed_at": 1180.0,
        "tier": DropTier(window_seconds=180, drop_pct=15, implied_drop_pct=5),
        "row": row,
    }
    base.update(overrides)
    return DropHit(**base)


def test_format_match_url() -> None:
    url = format_match_url("https://www.tipsport.cz", "/kurzy/zapas/a-b/1")
    assert url == "https://www.tipsport.cz/kurzy/zapas/a-b/1"


def test_sport_emoji_czech_and_default() -> None:
    assert sport_emoji("Fotbal") == "⚽"
    assert sport_emoji("Lední hokej") == "🏒"
    assert sport_emoji("Esporty") == "🎮"
    assert sport_emoji("Šipky") == "🎯"
    assert sport_emoji("Společenské sázky") == "🎰"
    assert sport_emoji("Unknown Sport") == "🏷️"


def test_sport_emoji_all_known_super_sports() -> None:
    known = [
        "Akrobatické lyžování",
        "Alpské lyžování",
        "Americký fotbal",
        "Atletika",
        "Australský fotbal",
        "Badminton",
        "Bandy",
        "Baseball",
        "Basketbal",
        "Biatlon",
        "Boby",
        "Bojové sporty",
        "Bowls",
        "Box",
        "Curling",
        "Cyklistika",
        "Dostihy",
        "Esporty",
        "Florbal",
        "Fotbal",
        "Futsal",
        "Golf",
        "Házená",
        "Hokejbal",
        "Klasické lyžování",
        "Krasobruslení",
        "Kriket",
        "Lakros",
        "Lední hokej",
        "Malý fotbal",
        "Motorsport",
        "Padel",
        "Plavání",
        "Plážový fotbal",
        "Plážový volejbal",
        "Plochá dráha",
        "Pool",
        "Pozemní hokej",
        "Rugby",
        "Rychlobruslení",
        "Šachy",
        "Saně",
        "Short Track",
        "Šipky",
        "Skeleton",
        "Skialpinismus",
        "Skoky na lyžích",
        "Snooker",
        "Snowboarding",
        "Softball",
        "Společenské sázky",
        "Squash",
        "Stolní tenis",
        "Tenis",
        "Vodní pólo",
        "Volejbal",
    ]
    for name in known:
        assert sport_emoji(name) != "🏷️", name


def test_selection_icon_over_under_default() -> None:
    assert selection_icon("Over 2.5") == "⬆️"
    assert selection_icon("under 0.5") == "⬇️"
    assert selection_icon("Team A") == "➡️"


def test_match_phase_emoji_prematch_and_inplay() -> None:
    assert match_phase_emoji("PREMATCH") == "🔵"
    assert match_phase_emoji("LIVE") == "🔴"


def test_drop_window_minutes() -> None:
    assert drop_window_minutes(1000.0, 1180.0) == 3
    assert drop_window_minutes(1000.0, 1030.0) == 0


def test_format_kickoff_prague() -> None:
    kickoff = format_kickoff_prague(1775395800000)
    assert kickoff.startswith("2026-")


KICKOFF_MS = 1775395800000
KICKOFF_TS = KICKOFF_MS / 1000.0


def test_format_time_to_kickoff_countdown_and_live() -> None:
    assert format_time_to_kickoff(None, KICKOFF_TS) == "?"
    assert format_time_to_kickoff(KICKOFF_MS, KICKOFF_TS - 8100) == "T-2h 15m"
    assert format_time_to_kickoff(KICKOFF_MS, KICKOFF_TS - 2700) == "T-45m"
    assert format_time_to_kickoff(KICKOFF_MS, KICKOFF_TS - 90000) == "T-1d 1h"
    assert format_time_to_kickoff(KICKOFF_MS, KICKOFF_TS - 12 * 86400) == "T-12d"
    assert format_time_to_kickoff(KICKOFF_MS, KICKOFF_TS + 720) == "LIVE +12m"


def test_format_line4_timing_layouts() -> None:
    kickoff = format_kickoff_prague(KICKOFF_MS)
    tail = "drop <b>3</b> min · <b>Δ -10.0%/-5.2%</b>"

    hours_ahead = format_line4_timing(
        KICKOFF_MS,
        KICKOFF_TS - 8100,
        drop_min=3,
        drop_delta="Δ -10.0%/-5.2%",
    )
    assert hours_ahead == f"⏰ {kickoff} (<b>T-2h 15m</b>) · {tail}"

    urgent = format_line4_timing(
        KICKOFF_MS,
        KICKOFF_TS - 2700,
        drop_min=3,
        drop_delta="Δ -10.0%/-5.2%",
    )
    assert urgent == f"⏰ {kickoff} · <b>🔜 T-45m</b> · {tail}"

    live = format_line4_timing(
        KICKOFF_MS,
        KICKOFF_TS + 720,
        drop_min=3,
        drop_delta="Δ -10.0%/-5.2%",
    )
    assert live == f"⏰ {kickoff} (<b>LIVE +12m</b>) · {tail}"

    missing = format_line4_timing(None, KICKOFF_TS, drop_min=3, drop_delta="Δ -10.0%/-5.2%")
    assert missing == f"⏰ ? (?) · {tail}"


def test_format_drop_alert_message_four_line_layout() -> None:
    row = _tracked()
    hit = _drop_hit(
        row,
        baseline_observed_at=KICKOFF_TS - 8280,
        current_observed_at=KICKOFF_TS - 8100,
    )
    msg = format_drop_alert_message(hit, match_url_base="https://www.tipsport.cz")
    lines = msg.splitlines()

    assert len(lines) == 4
    assert lines[0] == "⚽ <b>Premier League</b>"
    assert lines[1] == (
        '🔵 <a href="https://www.tipsport.cz/kurzy/zapas/arsenal-chelsea/8302416">'
        "Arsenal - Chelsea</a>, <b>Celkový počet gólů hráče</b>"
    )
    assert (
        lines[2]
        == "➡️ <b>Hráč X - více než 0.5 @ 1.73</b> (<s>1.92</s>↓)"
    )
    assert lines[3].startswith("⏰ ")
    assert "(<b>T-2h 15m</b>)" in lines[3]
    assert "drop <b>3</b> min · <b>Δ -10.0%/-5.2%</b>" in lines[3]


def test_parse_telegram_groups() -> None:
    raw = "A:123456:AAHtoken:-999,B:654321:AAHother:-111"
    groups = parse_telegram_groups(raw)
    assert set(groups) == {"A", "B"}
    assert groups["A"].chat_id == "-999"


def test_telegram_sender_reuses_client() -> None:
    sender = TelegramSender()
    client_a = sender._client_or_create()
    client_b = sender._client_or_create()
    assert client_a is client_b
    sender.close()
