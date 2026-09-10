"""Asian handicap/total line classification for settlement and monitor filtering."""

from __future__ import annotations

import re

# Tipsport quarter lines: "Team -0.75 (-0.5, -1.0)" or "Více než 2.25 (2.0, 2.5)"
_SPLIT_PAREN_RE = re.compile(
    r"\(\s*([-+]?\d+(?:[.,]\d+)?)\s*,\s*([-+]?\d+(?:[.,]\d+)?)\s*\)\s*$"
)
# Pinnacle quarter lines: "VPS 0-0.5", "Over 2-2.5" (split pair, not a single decimal)
_SPLIT_HYPHEN_RE = re.compile(
    r"(?<![\d.,])([-+]?\d+(?:[.,]\d+)?)\s*-\s*([-+]?\d+(?:[.,]\d+)?)\s*$"
)
_TRAILING_LINE_RE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*$")

ASIAN_MARKET_TOKEN = "ASIAN"
_HANDICAP_TOTAL_TOKENS = ("SPREAD", "TOTAL", "ASIAN", "HANDICAP", "HCP")


def is_asian_market(my_selection_id: str | None) -> bool:
    return ASIAN_MARKET_TOKEN in str(my_selection_id or "")


def _parse_threshold(value: str) -> float:
    return float(value.replace(",", "."))


def _split_pair_is_quarter(left: float, right: float) -> bool:
    return abs(abs(left - right) - 0.5) < 0.01


def _split_pair_from_text(text: str) -> tuple[float, float] | None:
    for pattern in (_SPLIT_PAREN_RE, _SPLIT_HYPHEN_RE):
        match = pattern.search(text)
        if match is None:
            continue
        left = _parse_threshold(match.group(1))
        right = _parse_threshold(match.group(2))
        if _split_pair_is_quarter(left, right):
            return left, right
    return None


def is_quarter_line_opp(opp_name: str | None) -> bool:
    """True when opp_name ends with a split pair differing by 0.5 (¼/¾ Asian line)."""
    text = str(opp_name or "").strip()
    if not text:
        return False
    return _split_pair_from_text(text) is not None


def is_quarter_line_alert(*, my_selection_id: str | None, opp_name: str | None) -> bool:
    """Quarter-line Asian alert — settlement result should be '?'."""
    if not is_asian_market(my_selection_id):
        return False
    return is_quarter_line_opp(opp_name)


def is_quarter_line_number(value: float) -> bool:
    """True for Asian quarter lines (.25 / .75 fractional part)."""
    fractional = round(abs(value) % 1.0, 2)
    return fractional in {0.25, 0.75}


def parse_line_value(text: str | None) -> float | None:
    """Parse a handicap/total line number from opp_number or opp_name tail."""
    raw = str(text or "").strip()
    if not raw:
        return None
    split = _split_pair_from_text(raw)
    if split is not None:
        left, right = split
        return round((left + right) / 2.0, 2)
    normalized = raw.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        pass
    match = _TRAILING_LINE_RE.search(normalized)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def is_handicap_or_total_market(my_selection_id: str | None) -> bool:
    folded = str(my_selection_id or "").upper()
    return any(token in folded for token in _HANDICAP_TOTAL_TOKENS)


def should_skip_quarter_handicap(
    *,
    my_selection_id: str | None,
    opp_name: str | None,
    opp_number: str | None = None,
) -> bool:
    """Skip monitor ingest/alerts for quarter Asian handicap and total lines."""
    if not is_handicap_or_total_market(my_selection_id):
        return False
    if is_quarter_line_opp(opp_name):
        return True
    for candidate in (opp_number, opp_name):
        line = parse_line_value(candidate)
        if line is not None and is_quarter_line_number(line):
            return True
    return False
