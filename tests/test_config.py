"""Config loading tests."""

from pathlib import Path

import pytest
import yaml

from deltax.config import load_config


def test_load_config_endpoints_list(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {
                    "endpoints": [
                        "/matches?sport=16",
                        "/matches?sport=31",
                    ]
                },
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
    assert config.tipsport_endpoints == ("/matches?sport=16", "/matches?sport=31")


def test_load_config_legacy_single_endpoint(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoint": "/matches?allEvents=true"},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
    assert config.tipsport_endpoints == ("/matches?allEvents=true",)


def test_load_config_endpoints_env_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "tipsport": {"endpoints": ["/from-yaml"]},
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(
        env={
            "DELTAX_CONFIG_PATH": str(config_path),
            "DELTAX_TIPSPORT_ENDPOINTS": "/from-env-a,/from-env-b",
        }
    )
    assert config.tipsport_endpoints == ("/from-env-a", "/from-env-b")


def test_load_config_requires_endpoint(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump({"tipsport": {}, "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tipsport.endpoints"):
        load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
