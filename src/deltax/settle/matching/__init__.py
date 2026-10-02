"""Team-name matching utilities (copied from morex/inspire for FS linking)."""

from deltax.settle.matching.aliases import load_merged_team_aliases
from deltax.settle.matching.config import FsMatchingConfig, load_fs_matching_config
from deltax.settle.matching.scoring import pair_score
from deltax.settle.matching.teams import name_similarity, normalize_team

__all__ = [
    "FsMatchingConfig",
    "load_fs_matching_config",
    "load_merged_team_aliases",
    "name_similarity",
    "normalize_team",
    "pair_score",
]
