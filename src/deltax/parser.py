"""Parse Tipsport bulk match payload into flat selection rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_MARKET_TYPE_RE = re.compile(r"\d+-(.+)-\d+$")


def extract_market_type(my_selection_id: str) -> str:
    match = _MARKET_TYPE_RE.match(my_selection_id or "")
    if match:
        return match.group(1)
    return my_selection_id or ""


@dataclass(frozen=True)
class SelectionRow:
    opp_id: int
    match_id: int
    market_type: str
    match_name: str
    competition_name: str
    event_name: str
    opp_name: str
    odd: float
    betting_enabled: bool
    match_url: str
    my_selection_id: str
    date_start: int | None


def _iter_events(match: dict[str, Any]) -> Iterable[dict[str, Any]]:
    events = match.get("events") or []
    for event in events:
        if isinstance(event, dict):
            yield event
    main = match.get("mainEvent")
    if isinstance(main, dict) and not events:
        yield main


def parse_selections(payload: dict[str, Any]) -> list[SelectionRow]:
    rows: list[SelectionRow] = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        match_fields = {
            "match_id": int(match["id"]),
            "match_name": str(match.get("name") or ""),
            "competition_name": str(match.get("nameCompetition") or ""),
            "match_url": str(match.get("matchUrl") or ""),
            "date_start": match.get("dateStart"),
        }
        for event in _iter_events(match):
            my_sel_id = str(event.get("mySelectionId") or "")
            market_type = extract_market_type(my_sel_id)
            event_name = str(event.get("name") or "")
            for opp in event.get("opps") or []:
                if not isinstance(opp, dict):
                    continue
                opp_id = opp.get("id")
                odd = opp.get("odd")
                if opp_id is None or odd is None:
                    continue
                rows.append(
                    SelectionRow(
                        opp_id=int(opp_id),
                        match_id=match_fields["match_id"],
                        market_type=market_type,
                        match_name=match_fields["match_name"],
                        competition_name=match_fields["competition_name"],
                        event_name=event_name,
                        opp_name=str(opp.get("name") or ""),
                        odd=float(odd),
                        betting_enabled=bool(opp.get("bettingEnabled")),
                        match_url=match_fields["match_url"],
                        my_selection_id=my_sel_id,
                        date_start=int(match_fields["date_start"])
                        if match_fields["date_start"] is not None
                        else None,
                    )
                )
    return rows
