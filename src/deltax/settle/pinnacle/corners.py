"""Corner-market detection and W/L grading for Pinnacle alerts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from deltax.settle.asian_lines import is_quarter_line_alert, is_quarter_line_opp, parse_line_value
from deltax.settle.constants import RESULT_LOSS, RESULT_UNKNOWN, RESULT_VOID, RESULT_WIN

_CORNERS_SUFFIX_RE = re.compile(r"\s*\((?:Corners|corners)\)\s*")
_BOOKINGS_SUFFIX_RE = re.compile(r"\s*\((?:Bookings|bookings)\)\s*")
_PINNACLE_TEMPLATE_RE = re.compile(
    r"^(?P<sport>\d+)-(?P<period>\d+)-(?P<market>[A-Z_]+)-(?P<side>[A-Z]+)$"
)


@dataclass(frozen=True)
class CornerCounts:
    home: int
    away: int

    @property
    def total(self) -> int:
        return self.home + self.away


def strip_relative_unit_suffix(name: str | None) -> str:
    text = str(name or "").strip()
    text = _CORNERS_SUFFIX_RE.sub("", text)
    text = _BOOKINGS_SUFFIX_RE.sub("", text)
    return text.strip()


def normalize_team_key(name: str | None) -> str:
    text = strip_relative_unit_suffix(name).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def is_bookings_alert(*, home_participant: str | None, visiting_participant: str | None, match_name: str | None) -> bool:
    blob = " ".join(
        str(part or "")
        for part in (home_participant, visiting_participant, match_name)
    )
    return bool(_BOOKINGS_SUFFIX_RE.search(blob))


def is_corners_alert(*, home_participant: str | None, visiting_participant: str | None, match_name: str | None) -> bool:
    if is_bookings_alert(
        home_participant=home_participant,
        visiting_participant=visiting_participant,
        match_name=match_name,
    ):
        return False
    blob = " ".join(
        str(part or "")
        for part in (home_participant, visiting_participant, match_name)
    )
    if _CORNERS_SUFFIX_RE.search(blob):
        return True
    return False


def parse_pinnacle_template(my_selection_id: str) -> tuple[str, str, str, str] | None:
    match = _PINNACLE_TEMPLATE_RE.match(str(my_selection_id or "").strip())
    if match is None:
        return None
    return match.group("sport"), match.group("period"), match.group("market"), match.group("side")


def grade_corner_alert(
    *,
    my_selection_id: str,
    opp_name: str,
    opp_number: str | None,
    counts: CornerCounts,
) -> str | None:
    """Return W/L/V/? or None when the alert cannot be graded."""
    parsed = parse_pinnacle_template(my_selection_id)
    if parsed is None:
        return None
    _sport, period, market, side = parsed
    if period != "0":
        return None

    if is_quarter_line_alert(my_selection_id=my_selection_id, opp_name=opp_name):
        return RESULT_UNKNOWN
    if is_quarter_line_opp(opp_name):
        return RESULT_UNKNOWN

    if market == "MONEYLINE":
        if side == "HOME":
            if counts.home > counts.away:
                return RESULT_WIN
            if counts.home < counts.away:
                return RESULT_LOSS
            return RESULT_VOID
        if side == "AWAY":
            if counts.away > counts.home:
                return RESULT_WIN
            if counts.away < counts.home:
                return RESULT_LOSS
            return RESULT_VOID
        if side == "DRAW":
            if counts.home == counts.away:
                return RESULT_WIN
            return RESULT_LOSS

    line = parse_line_value(opp_number) or parse_line_value(opp_name)
    if line is None:
        return None

    if market == "TOTAL":
        total = counts.total
        if side == "OVER":
            if total > line:
                return RESULT_WIN
            if total < line:
                return RESULT_LOSS
            return RESULT_VOID
        if side == "UNDER":
            if total < line:
                return RESULT_WIN
            if total > line:
                return RESULT_LOSS
            return RESULT_VOID
        return None

    if market == "SPREAD":
        if side == "HOME":
            margin = counts.home + line - counts.away
        elif side == "AWAY":
            margin = counts.away + line - counts.home
        else:
            return None
        if margin > 0:
            return RESULT_WIN
        if margin < 0:
            return RESULT_LOSS
        return RESULT_VOID

    return None
