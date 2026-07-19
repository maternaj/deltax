"""Message and Telegram helper tests."""

from deltax.config import DropTier
from deltax.drop_detector import DropHit
from deltax.messages import format_drop_alert_message, format_match_url
from deltax.parser import SelectionRow
from deltax.telegram import parse_telegram_groups


def test_format_match_url() -> None:
    url = format_match_url("https://www.tipsport.cz", "/kurzy/zapas/a-b/1")
    assert url == "https://www.tipsport.cz/kurzy/zapas/a-b/1"


def test_format_drop_alert_message_contains_link() -> None:
    row = SelectionRow(
        opp_id=1,
        match_id=100,
        market_type="WINNER_3W",
        match_name="A - B",
        competition_name="League",
        event_name="Result",
        opp_name="A",
        odd=1.8,
        betting_enabled=True,
        match_url="/kurzy/zapas/a-b/100",
        my_selection_id="16-WINNER_3W-1",
        date_start=1775395800000,
    )
    hit = DropHit(
        opp_id=1,
        match_id=100,
        market_type="WINNER_3W",
        drop_pct=10.0,
        baseline_odds=2.0,
        current_odds=1.8,
        tier=DropTier(window_seconds=60, drop_pct=10),
        row=row,
    )
    msg = format_drop_alert_message(hit, match_url_base="https://www.tipsport.cz")
    assert "prematch odds drop" in msg
    assert "https://www.tipsport.cz/kurzy/zapas/a-b/100" in msg


def test_parse_telegram_groups() -> None:
    raw = "A:123456:AAHtoken:-999,B:654321:AAHother:-111"
    groups = parse_telegram_groups(raw)
    assert set(groups) == {"A", "B"}
    assert groups["A"].chat_id == "-999"
