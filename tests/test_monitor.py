"""Monitor pipeline tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from deltax.config import AppConfig, DropTier, load_config
from deltax.drop_detector import DropHit
from deltax.markets import load_market_registry
from deltax.monitor import DeltaXMonitor
from deltax.parser import SelectionRow
from deltax.telegram import telegram_enabled


def _config() -> AppConfig:
    raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    return AppConfig(
        tipsport_base_url="https://www.tipsport.cz",
        tipsport_endpoint="/matches",
        refresh_seconds=30,
        selection_ttl_seconds=600,
        max_odds=5.0,
        drop_tiers=(DropTier(window_seconds=0, drop_pct=10),),
        match_url_base="https://www.tipsport.cz",
        default_alert_groups="A",
        config_path=Path("config.yaml"),
        market_registry=load_market_registry(raw, config_path=Path("config.yaml")),
    )


def _selection_row(**kwargs) -> SelectionRow:
    defaults = {
        "opp_id": 1,
        "event_id": 10,
        "match_id": 100,
        "my_selection_id": "16-WINNER_3W-1",
        "match_name": "A - B",
        "home_participant": "A",
        "visiting_participant": "B",
        "competition_name": "League",
        "sport_name": "Fotbal",
        "super_sport_name": "Fotbal",
        "match_type": "PREMATCH",
        "event_name": "Result",
        "opp_name": "A",
        "odd": 1.8,
        "betting_enabled": True,
        "opp_type": "1",
        "opp_number": None,
        "match_url": "/kurzy/zapas/a-b/100",
        "date_start": None,
        "tipsport_snapshot": {"match": {"id": 100}, "event": {"id": 10}, "opp": {"id": 1}},
    }
    defaults.update(kwargs)
    return SelectionRow(**defaults)


def _hit() -> DropHit:
    row = _selection_row()
    return DropHit(
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
    assert (100, "16-WINNER_3W-1") not in monitor.runtime.store.markets


def test_market_disarmed_only_after_persist_success() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    hit = _hit()

    with patch("deltax.monitor.pick_market_alerts", return_value=[hit]):
        with patch.object(monitor, "_persist_alert", return_value=42):
            with patch.object(monitor, "_update_telegram_status"):
                sent = monitor.process_alerts(now_ts=30.0)

    assert sent == 1
    assert monitor.runtime.store.markets[(100, "16-WINNER_3W-1")].armed is False


def test_validate_startup_requires_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    monkeypatch.setattr("deltax.monitor.validate_connection", MagicMock())
    monitor.validate_startup()


def test_blacklisted_markets_skipped_on_ingest() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    row = _selection_row(
        opp_id=99,
        my_selection_id="16-EXACT_RESULT-1",
        event_name="Exact",
        opp_name="1:0",
        odd=6.0,
    )
    changed = monitor.ingest_rows([row], now_ts=10.0)
    assert changed == 0
    assert 99 not in monitor.runtime.store.selections


def test_load_config_uses_my_selection_id_lists() -> None:
    config = load_config(env={"DELTAX_CONFIG_PATH": str(Path("config.yaml").resolve())})
    registry = config.market_registry
    assert "16-WINNER_3W-1" in registry.wanted
    assert "16-WINNER_3W-2" in registry.blacklisted
    assert registry.should_process("16-WINNER_3W-1")
    assert not registry.should_process("16-WINNER_3W-2")
