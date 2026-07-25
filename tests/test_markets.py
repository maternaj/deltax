"""Tests for market classification and config persistence."""

from pathlib import Path

import pytest
import yaml

from deltax.markets import MarketRegistry, load_market_registry


def test_should_process_wanted_and_pending(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    raw = {
        "markets": {
            "wanted": ["16-WINNER_3W-1"],
            "pending": ["16-ASIAN_TOTAL-1"],
            "blacklisted": ["16-EXACT_RESULT-1"],
        }
    }
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    registry = load_market_registry(raw, config_path=config_path)

    assert registry.should_process("16-WINNER_3W-1")
    assert registry.should_process("16-ASIAN_TOTAL-1")
    assert registry.should_process("16-UNKNOWN-1")
    assert not registry.should_process("16-EXACT_RESULT-1")


def test_new_market_added_to_pending_in_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    raw = {
        "markets": {
            "wanted": ["16-WINNER_3W-1"],
            "pending": [],
            "blacklisted": ["16-EXACT_RESULT-1"],
        }
    }
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    registry = load_market_registry(raw, config_path=config_path)

    registry.register_seen("16-NEW_MARKET-1")

    assert "16-NEW_MARKET-1" in registry.pending
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "16-NEW_MARKET-1" in saved["markets"]["pending"]


def test_blacklisted_market_not_added_to_pending(tmp_path: Path) -> None:
    registry = MarketRegistry(
        wanted={"16-WINNER_3W-1"},
        pending=set(),
        blacklisted={"16-EXACT_RESULT-1"},
        config_path=tmp_path / "config.yaml",
        _raw_config={"markets": {"wanted": [], "pending": [], "blacklisted": ["16-EXACT_RESULT-1"]}},
    )
    registry.register_seen("16-EXACT_RESULT-1")
    assert "16-EXACT_RESULT-1" not in registry.pending


def test_blacklisted_prefix_blocks_entire_sport(tmp_path: Path) -> None:
    raw = {
        "markets": {
            "wanted": ["16-WINNER_3W-1"],
            "pending": [],
            "blacklisted": [],
            "blacklisted_prefixes": ["11-"],
        }
    }
    registry = load_market_registry(raw, config_path=tmp_path / "config.yaml")

    assert registry.should_process("16-WINNER_3W-1")
    assert not registry.should_process("11-WINNER_3W-1")
    assert not registry.should_process("11-ASIAN_TOTAL-1")


def test_blacklisted_prefix_not_added_to_pending(tmp_path: Path) -> None:
    registry = MarketRegistry(
        wanted=set(),
        pending=set(),
        blacklisted=set(),
        blacklisted_prefixes=("188-",),
        config_path=tmp_path / "config.yaml",
        _raw_config={"markets": {"blacklisted_prefixes": ["188-"]}},
    )
    registry.register_seen("188-WINNER_2W-1")
    assert "188-WINNER_2W-1" not in registry.pending


def test_wanted_conflicts_with_blacklisted_prefix(tmp_path: Path) -> None:
    raw = {
        "markets": {
            "wanted": ["11-WINNER_3W-1"],
            "pending": [],
            "blacklisted": [],
            "blacklisted_prefixes": ["11-"],
        }
    }
    with pytest.raises(ValueError, match="blacklisted_prefixes"):
        load_market_registry(raw, config_path=tmp_path / "config.yaml")
