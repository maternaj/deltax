"""Parse Tipsport match results API responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ResultCell:
    opp_id: int
    odd: float | None
    winning: bool | None
    observed_at: datetime | None


def _parse_date_closed(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def match_has_results(match_data: dict[str, Any]) -> bool:
    match = match_data.get("match") or {}
    result_parts = match.get("resultParts")
    return bool(result_parts)


def parse_result_cells(match_data: dict[str, Any]) -> dict[int, ResultCell]:
    """Map opp_id -> result cell from fromResults=true payload."""
    if not match_has_results(match_data):
        return {}

    cells: dict[int, ResultCell] = {}
    match = match_data.get("match") or {}
    for event_table in match.get("eventTables") or []:
        for box in event_table.get("boxes") or []:
            for cell in box.get("cells") or []:
                if "winning" not in cell:
                    continue
                opp_id_raw = cell.get("id")
                if opp_id_raw is None:
                    continue
                opp_id = int(opp_id_raw)
                winning_raw = cell.get("winning")
                winning = winning_raw if isinstance(winning_raw, bool) else None
                odd_raw = cell.get("odd")
                odd = float(odd_raw) if odd_raw is not None else None
                cells[opp_id] = ResultCell(
                    opp_id=opp_id,
                    odd=odd,
                    winning=winning,
                    observed_at=_parse_date_closed(cell.get("dateClosed")),
                )
    return cells
