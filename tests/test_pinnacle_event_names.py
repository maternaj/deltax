"""Tests for Pinnacle market event name formatting."""

from deltax.pinnacle.flatten import format_market_event_name


def test_format_market_event_name_main_period() -> None:
    period = {"period_key": "0", "name": None, "period_number": 0}
    assert format_market_event_name(market="MONEYLINE", period=period) == "Moneyline"
    assert format_market_event_name(market="SPREAD", period=period) == "Handicap"
    assert format_market_event_name(market="TOTAL", period=period) == "Over/Under"


def test_format_market_event_name_non_main_period() -> None:
    period = {"period_key": "1", "name": None, "period_number": 1}
    assert format_market_event_name(market="MONEYLINE", period=period) == "Period 1 · Moneyline"


def test_format_market_event_name_uses_string_period_name() -> None:
    period = {"period_key": "0", "name": "1st Half", "period_number": 1}
    assert format_market_event_name(market="TOTAL", period=period) == "1st Half · Over/Under"
