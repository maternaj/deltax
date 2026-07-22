"""Asian handicap/total line classification for settlement."""

from __future__ import annotations

import re

# Tipsport quarter lines: "Team -0.75 (-0.5, -1.0)" or "Více než 2.25 (2.0, 2.5)"
_SPLIT_PAREN_RE = re.compile(
    r"\(\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)\s*\)\s*$"
)

ASIAN_MARKET_TOKEN = "ASIAN"


def is_asian_market(my_selection_id: str | None) -> bool:
    return ASIAN_MARKET_TOKEN in str(my_selection_id or "")


def _parse_threshold(value: str) -> float:
    return float(value.replace(",", "."))


def is_quarter_line_opp(opp_name: str | None) -> bool:
    """True when opp_name ends with a split pair differing by 0.5 (¼/¾ Asian line)."""
    text = str(opp_name or "").strip()
    if not text:
        return False
    match = _SPLIT_PAREN_RE.search(text)
    if not match:
        return False
    left = _parse_threshold(match.group(1))
    right = _parse_threshold(match.group(2))
    return abs(abs(left - right) - 0.5) < 0.01


def is_quarter_line_alert(*, my_selection_id: str | None, opp_name: str | None) -> bool:
    """Quarter-line Asian alert — settlement result should be '?'."""
    if not is_asian_market(my_selection_id):
        return False
    return is_quarter_line_opp(opp_name)
