"""Parse Tipsport bulk match payload into flat selection rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

_MATCH_SNAPSHOT_KEYS = (
    "id",
    "name",
    "matchType",
    "matchUrl",
    "dateStart",
    "idCompetition",
    "nameCompetition",
    "idSport",
    "nameSport",
    "idSuperSport",
    "nameSuperSport",
    "homeParticipant",
    "visitingParticipant",
    "homeParticipantId",
    "visitingParticipantId",
)
_EVENT_SNAPSHOT_KEYS = ("id", "name", "mySelectionId")
_OPP_SNAPSHOT_KEYS = (
    "id",
    "name",
    "odd",
    "bettingEnabled",
    "type",
    "oppNumber",
    "winning",
    "mostBet",
    "idEvent",
)


def _snapshot_slice(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def build_tipsport_snapshot(
    match: dict[str, Any],
    event: dict[str, Any],
    opp: dict[str, Any],
) -> dict[str, Any]:
    return {
        "match": _snapshot_slice(match, _MATCH_SNAPSHOT_KEYS),
        "event": _snapshot_slice(event, _EVENT_SNAPSHOT_KEYS),
        "opp": _snapshot_slice(opp, _OPP_SNAPSHOT_KEYS),
    }


@dataclass(frozen=True)
class TrackedSelection:
    """In-memory selection fields — no tipsport_snapshot (built only when persisting alerts)."""

    opp_id: int
    event_id: int
    match_id: int
    my_selection_id: str
    match_name: str
    home_participant: str | None
    visiting_participant: str | None
    competition_name: str
    sport_name: str | None
    super_sport_name: str | None
    match_type: str | None
    event_name: str
    opp_name: str
    odd: float
    betting_enabled: bool
    opp_type: str | None
    opp_number: str | None
    match_url: str
    date_start: int | None


@dataclass(frozen=True)
class SelectionRow(TrackedSelection):
    tipsport_snapshot: dict[str, Any]


def tracked_from_row(row: SelectionRow) -> TrackedSelection:
    return TrackedSelection(
        opp_id=row.opp_id,
        event_id=row.event_id,
        match_id=row.match_id,
        my_selection_id=row.my_selection_id,
        match_name=row.match_name,
        home_participant=row.home_participant,
        visiting_participant=row.visiting_participant,
        competition_name=row.competition_name,
        sport_name=row.sport_name,
        super_sport_name=row.super_sport_name,
        match_type=row.match_type,
        event_name=row.event_name,
        opp_name=row.opp_name,
        odd=row.odd,
        betting_enabled=row.betting_enabled,
        opp_type=row.opp_type,
        opp_number=row.opp_number,
        match_url=row.match_url,
        date_start=row.date_start,
    )


def tipsport_snapshot_from_tracked(tracked: TrackedSelection) -> dict[str, Any]:
    """Rebuild alert JSON from flat tracked fields (no raw feed retained in memory)."""
    return {
        "match": {
            "id": tracked.match_id,
            "name": tracked.match_name,
            "matchType": tracked.match_type,
            "matchUrl": tracked.match_url,
            "dateStart": tracked.date_start,
            "nameCompetition": tracked.competition_name,
            "nameSport": tracked.sport_name,
            "nameSuperSport": tracked.super_sport_name,
            "homeParticipant": tracked.home_participant,
            "visitingParticipant": tracked.visiting_participant,
        },
        "event": {
            "id": tracked.event_id,
            "name": tracked.event_name,
            "mySelectionId": tracked.my_selection_id,
        },
        "opp": {
            "id": tracked.opp_id,
            "name": tracked.opp_name,
            "odd": tracked.odd,
            "bettingEnabled": tracked.betting_enabled,
            "type": tracked.opp_type,
            "oppNumber": tracked.opp_number,
            "idEvent": tracked.event_id,
        },
    }


def _iter_events(match: dict[str, Any]) -> Iterable[dict[str, Any]]:
    events = match.get("events") or []
    for event in events:
        if isinstance(event, dict):
            yield event
    main = match.get("mainEvent")
    if isinstance(main, dict) and not events:
        yield main


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_selections(payload: dict[str, Any]) -> list[SelectionRow]:
    rows: list[SelectionRow] = []
    for match in payload.get("matches") or []:
        if not isinstance(match, dict):
            continue
        match_id = int(match["id"])
        match_name = str(match.get("name") or "")
        competition_name = str(match.get("nameCompetition") or "")
        match_url = str(match.get("matchUrl") or "")
        date_start_raw = match.get("dateStart")
        date_start = int(date_start_raw) if date_start_raw is not None else None
        home_participant = _optional_str(match.get("homeParticipant"))
        visiting_participant = _optional_str(match.get("visitingParticipant"))
        sport_name = _optional_str(match.get("nameSport"))
        super_sport_name = _optional_str(match.get("nameSuperSport"))
        match_type = _optional_str(match.get("matchType"))

        for event in _iter_events(match):
            event_id_raw = event.get("id")
            if event_id_raw is None:
                continue
            my_sel_id = str(event.get("mySelectionId") or "")
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
                        event_id=int(event_id_raw),
                        match_id=match_id,
                        my_selection_id=my_sel_id,
                        match_name=match_name,
                        home_participant=home_participant,
                        visiting_participant=visiting_participant,
                        competition_name=competition_name,
                        sport_name=sport_name,
                        super_sport_name=super_sport_name,
                        match_type=match_type,
                        event_name=event_name,
                        opp_name=str(opp.get("name") or ""),
                        odd=float(odd),
                        betting_enabled=bool(opp.get("bettingEnabled")),
                        opp_type=_optional_str(opp.get("type")),
                        opp_number=_optional_str(opp.get("oppNumber")),
                        match_url=match_url,
                        date_start=date_start,
                        tipsport_snapshot=build_tipsport_snapshot(match, event, opp),
                    )
                )
    return rows
