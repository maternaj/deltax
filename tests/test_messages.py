"""Message and Telegram helper tests."""

from deltax.config import DropTier
from deltax.drop_detector import DropHit
from deltax.messages import format_drop_alert_message, format_match_url
from deltax.parser import SelectionRow
from deltax.telegram import TelegramSender, parse_telegram_groups


def _selection_row() -> SelectionRow:
    return SelectionRow(
        opp_id=1,
        event_id=10,
        match_id=100,
        my_selection_id="16-WINNER_3W-1",
        match_name="A - B",
        home_participant="A",
        visiting_participant="B",
        competition_name="League",
        sport_name="Fotbal",
        super_sport_name="Fotbal",
        match_type="PREMATCH",
        event_name="Result",
        opp_name="A",
        odd=1.8,
        betting_enabled=True,
        opp_type="1",
        opp_number=None,
        match_url="/kurzy/zapas/a-b/100",
        date_start=1775395800000,
        tipsport_snapshot={"match": {}, "event": {}, "opp": {}},
    )


def test_format_match_url() -> None:
    url = format_match_url("https://www.tipsport.cz", "/kurzy/zapas/a-b/1")
    assert url == "https://www.tipsport.cz/kurzy/zapas/a-b/1"


def test_format_drop_alert_message_contains_link() -> None:
    row = _selection_row()
    hit = DropHit(
        opp_id=1,
        match_id=100,
        my_selection_id="16-WINNER_3W-1",
        drop_pct=10.0,
        implied_drop_pct=0.0,
        odds_previous=2.0,
        odds_now=1.8,
        baseline_observed_at=0.0,
        current_observed_at=30.0,
        tier=DropTier(window_seconds=0, drop_pct=10),
        row=row,
    )
    msg = format_drop_alert_message(hit, match_url_base="https://www.tipsport.cz")
    assert "prematch odds drop" in msg
    assert "2.00 → 1.80" in msg
    assert "https://www.tipsport.cz/kurzy/zapas/a-b/100" in msg


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
