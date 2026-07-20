"""Message and Telegram helper tests."""

from deltax.config import DropTier
from deltax.drop_detector import DropHit
from deltax.messages import (
    drop_window_minutes,
    format_drop_alert_message,
    format_kickoff_prague,
    format_match_url,
    match_phase_emoji,
    selection_icon,
    sport_emoji,
)
from deltax.parser import SelectionRow
from deltax.telegram import TelegramSender, parse_telegram_groups


def _selection_row(**overrides: object) -> SelectionRow:
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
        "tipsport_snapshot": {"match": {}, "event": {}, "opp": {}},
    }
    base.update(overrides)
    return SelectionRow(**base)


def _drop_hit(row: SelectionRow, **overrides: object) -> DropHit:
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
    assert sport_emoji("Unknown Sport") == "🏷️"


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


def test_format_drop_alert_message_four_line_layout() -> None:
    row = _selection_row()
    hit = _drop_hit(row)
    msg = format_drop_alert_message(hit, match_url_base="https://www.tipsport.cz")
    lines = msg.splitlines()

    assert len(lines) == 4
    assert lines[0] == "⚽ Premier League"
    assert lines[1] == "🔵 Arsenal - Chelsea, <b>Celkový počet gólů hráče</b>"
    assert "➡️ Hráč X - více než 0.5" in lines[2]
    assert "<b>@ 1.73</b>" in lines[2]
    assert "was 1.92 → Δ -10.0%/-5.2%" in lines[2]
    assert lines[3].startswith("⏰ ")
    assert (
        'drop <b>3</b> min · opp <a href="https://www.tipsport.cz/kurzy/zapas/arsenal-chelsea/8302416">2664187029</a>'
        in lines[3]
    )


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
