"""Load fs_matching.yaml (matching thresholds + bootstrap aliases)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FsMatchingConfig:
    min_match_score: float
    min_second_best_gap: float
    kickoff_window_minutes: int
    time_penalty_per_minute: float
    load_window_hours: float
    team_aliases: dict[str, str]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_fs_matching_path() -> Path:
    return _project_root() / "config" / "fs_matching.yaml"


def load_fs_matching_config(path: Path | None = None) -> FsMatchingConfig:
    config_path = path or default_fs_matching_path()
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    matching = raw.get("matching") or {}
    aliases = raw.get("team_aliases") or {}
    return FsMatchingConfig(
        min_match_score=float(matching.get("min_match_score", 75)),
        min_second_best_gap=float(matching.get("min_second_best_gap", 10)),
        kickoff_window_minutes=int(matching.get("kickoff_window_minutes", 180)),
        time_penalty_per_minute=float(matching.get("time_penalty_per_minute", 0.05)),
        load_window_hours=float(matching.get("load_window_hours", 3)),
        team_aliases={str(k): str(v) for k, v in aliases.items()},
    )
