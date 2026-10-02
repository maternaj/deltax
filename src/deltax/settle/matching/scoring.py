"""Pair scoring for alert ↔ Flashscore fixture (from morex/morex/inspire/match_mapping.py)."""

from __future__ import annotations

from typing import Mapping

from deltax.settle.matching.config import FsMatchingConfig
from deltax.settle.matching.teams import name_similarity


def pair_score(
    alert_home: str,
    alert_away: str,
    fs_home: str,
    fs_away: str,
    time_diff_min: float,
    *,
    matching: FsMatchingConfig,
    aliases: Mapping[str, str] | None = None,
    swapped: bool = False,
) -> float:
    if swapped:
        fs_home, fs_away = fs_away, fs_home
    home_score = name_similarity(alert_home, fs_home, aliases=aliases)
    away_score = name_similarity(alert_away, fs_away, aliases=aliases)
    name_score = (home_score + away_score) / 2.0
    if home_score == 100:
        name_score += 5
    if away_score == 100:
        name_score += 5
    penalty = matching.time_penalty_per_minute * abs(time_diff_min)
    return name_score - penalty
