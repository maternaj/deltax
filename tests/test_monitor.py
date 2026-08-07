"""Monitor pipeline tests."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from deltax.config import AppConfig, DropTier, SettleConfig, load_config
from deltax.drop_detector import DropHit
from deltax.markets import load_market_registry
from deltax.monitor import DeltaXMonitor
from deltax.parser import SelectionRow, tracked_from_row
from deltax.telegram import telegram_enabled


def _config() -> AppConfig:
    raw = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    return AppConfig(
        tipsport_base_url="https://www.tipsport.cz",
        tipsport_endpoints=("/matches",),
        refresh_seconds=30,
        selection_ttl_seconds=600,
        max_odds=5.0,
        excluded_event_name_substrings=("ITF",),
        drop_tiers=(DropTier(window_seconds=0, drop_pct=10),),
        match_url_base="https://www.tipsport.cz",
        default_alert_groups="A",
        settle=SettleConfig(
            sleep_seconds=900,
            default_delay_hours=6,
            max_age_days=3,
            batch_match_limit=50,
            match_request_delay_seconds=0,
            market_delay_hours={},
        ),
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
    row = tracked_from_row(_selection_row())
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


def test_excluded_event_name_skipped_on_ingest() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    row = _selection_row(
        opp_id=77,
        my_selection_id="16-WINNER_3W-1",
        event_name="ITF Challenger Prague",
        opp_name="A",
        odd=2.0,
    )
    changed = monitor.ingest_rows([row], now_ts=10.0)
    assert changed == 0
    assert 77 not in monitor.runtime.store.selections
    assert "16-WINNER_3W-1" not in monitor.config.market_registry.pending


def test_excluded_event_name_case_sensitive() -> None:
    monitor = DeltaXMonitor(_config(), env={"DELTAX_TELEGRAM_GROUPS": ""})
    row = _selection_row(
        opp_id=78,
        my_selection_id="16-WINNER_3W-1",
        event_name="itf Challenger Prague",
        opp_name="A",
        odd=2.0,
    )
    changed = monitor.ingest_rows([row], now_ts=10.0)
    assert changed == 0
    assert 78 in monitor.runtime.store.selections


def test_load_config_uses_my_selection_id_lists() -> None:
    config = load_config(env={"DELTAX_CONFIG_PATH": str(Path("config.yaml").resolve())})
    registry = config.market_registry
    assert "16-WINNER_3W-1" in registry.wanted
    assert "16-WINNER_3W-2" in registry.blacklisted
    assert registry.should_process("16-WINNER_3W-1")
    assert not registry.should_process("16-WINNER_3W-2")
    assert len(config.tipsport_endpoints) >= 1
    assert "ITF" in config.excluded_event_name_substrings


def test_run_cycle_fetches_all_endpoints_in_sequence() -> None:
    config = replace(_config(), tipsport_endpoints=("/a", "/b"))
    monitor = DeltaXMonitor(config, env={"DELTAX_TELEGRAM_GROUPS": ""})
    calls: list[str] = []

    def fake_fetch(endpoint: str):
        calls.append(endpoint)
        return {"matches": []}

    monitor.client.fetch = fake_fetch  # type: ignore[method-assign]

    stats = monitor.run_cycle()

    assert calls == ["/a", "/b"]
    assert stats["ok"] is True
    assert stats["endpoints_ok"] == 2
    assert stats["endpoints_failed"] == 0


def test_run_cycle_continues_when_one_endpoint_fails() -> None:
    config = replace(_config(), tipsport_endpoints=("/bad", "/good"))
    monitor = DeltaXMonitor(config, env={"DELTAX_TELEGRAM_GROUPS": ""})

    def fake_fetch(endpoint: str):
        if endpoint == "/bad":
            return None
        return {
            "matches": [
                {
                    "id": 1,
                    "name": "A - B",
                    "nameCompetition": "League",
                    "events": [
                        {
                            "id": 10,
                            "name": "Result",
                            "mySelectionId": "16-WINNER_3W-1",
                            "opps": [
                                {
                                    "id": 101,
                                    "name": "A",
                                    "odd": 2.0,
                                    "bettingEnabled": True,
                                    "type": "1",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    monitor.client.fetch = fake_fetch  # type: ignore[method-assign]

    stats = monitor.run_cycle()

    assert stats["ok"] is True
    assert stats["selections"] == 1
    assert stats["endpoints_ok"] == 1
    assert stats["endpoints_failed"] == 1
