"""Monitor pipeline tests."""

from unittest.mock import MagicMock, patch

import pytest

from deltax.config import AppConfig, DropTier
from deltax.drop_detector import DropHit, SelectionState
from deltax.monitor import DeltaXMonitor
from deltax.parser import SelectionRow
from deltax.telegram import telegram_enabled


def _config() -> AppConfig:
    return AppConfig(
        tipsport_base_url="https://www.tipsport.cz",
        tipsport_endpoint="/matches",
        refresh_seconds=30,
        selection_ttl_seconds=600,
        drop_tiers=(DropTier(window_seconds=0, drop_pct=10),),
        match_url_base="https://www.tipsport.cz",
        default_alert_groups="A",
        config_path=__import__("pathlib").Path("config.yaml"),
    )


def _hit() -> DropHit:
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
        date_start=None,
    )
    return DropHit(
        opp_id=1,
        match_id=100,
        market_type="WINNER_3W",
        drop_pct=10.0,
        baseline_odds=2.0,
        current_odds=1.8,
        tier=DropTier(window_seconds=0, drop_pct=10),
        row=row,
    )


def test_telegram_disabled_when_env_empty() -> None:
    assert not telegram_enabled({"DELTAX_TELEGRAM_GROUPS": ""})
    assert not telegram_enabled({})


def test_market_not_disarmed_when_persist_fails() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    hit = _hit()

    with patch("deltax.monitor.pick_market_alerts", return_value=[hit]):
        with patch.object(monitor, "_persist_alert", return_value=None):
            sent = monitor.process_alerts(now_ts=100.0)

    assert sent == 0
    assert (100, "WINNER_3W") not in monitor.runtime.store.markets


def test_market_disarmed_only_after_persist_success() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    hit = _hit()

    with patch("deltax.monitor.pick_market_alerts", return_value=[hit]):
        with patch.object(monitor, "_persist_alert", return_value=42):
            with patch.object(monitor, "_update_telegram_status"):
                sent = monitor.process_alerts(now_ts=30.0)

    assert sent == 1
    assert monitor.runtime.store.markets[(100, "WINNER_3W")].armed is False


def test_validate_startup_requires_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    monkeypatch.setattr("deltax.monitor.validate_connection", MagicMock())
    monitor.validate_startup()
