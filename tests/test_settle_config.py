"""Settlement config tests."""

from pathlib import Path

import pytest
import yaml

from deltax.config import load_config


def test_load_settle_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoints": ["/matches"]},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
    assert config.settle.sleep_seconds == 900
    assert config.settle.default_delay_hours == 6
    assert config.settle.max_age_days == 3
    assert config.settle.batch_match_limit == 50


def test_load_settle_market_delay_hours(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoints": ["/matches"]},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
                "settle": {
                    "default_delay_hours": 6,
                    "market_delay_hours": {
                        "16-GOAL_SCORERS-1": 12,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
    assert config.settle.delay_hours_for("16-GOAL_SCORERS-1") == 12
    assert config.settle.delay_hours_for("16-WINNER_3W-1") == 6


def test_load_settle_env_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoints": ["/matches"]},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(
        env={
            "DELTAX_CONFIG_PATH": str(config_path),
            "DELTAX_SETTLE_SLEEP_SECONDS": "1200",
            "DELTAX_SETTLE_DEFAULT_DELAY_HOURS": "8",
            "DELTAX_SETTLE_MAX_AGE_DAYS": "2",
        }
    )
    assert config.settle.sleep_seconds == 1200
    assert config.settle.default_delay_hours == 8
    assert config.settle.max_age_days == 2


def test_load_settle_invalid_sleep(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoints": ["/matches"]},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
                "settle": {"sleep_seconds": 10},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sleep_seconds"):
        load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
