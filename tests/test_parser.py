"""Parser tests."""

from deltax.parser import (
    build_tipsport_snapshot,
    parse_selections,
    tipsport_snapshot_from_tracked,
    tracked_from_row,
)

SAMPLE = {
    "count": 1,
    "matches": [
        {
            "id": 7154537,
            "name": "Ostrava - Slavia Praha",
            "nameCompetition": "Česká Chance Liga",
            "nameSport": "Fotbal",
            "nameSuperSport": "Fotbal",
            "matchType": "PREMATCH",
            "homeParticipant": "Ostrava",
            "visitingParticipant": "Slavia Praha",
            "matchUrl": "/kurzy/zapas/fotbal-ostrava-slavia-praha/7154537",
            "dateStart": 1775395800000,
            "events": [
                {
                    "id": 1,
                    "name": "Výsledek zápasu",
                    "mySelectionId": "16-WINNER_3W-1",
                    "opps": [
                        {"id": 101, "name": "Ostrava", "odd": 4.5, "bettingEnabled": True, "type": "1"},
                        {"id": 102, "name": "Remíza", "odd": 3.8, "bettingEnabled": False, "type": "0"},
                    ],
                },
                {
                    "id": 2,
                    "name": "Počet gólů",
                    "mySelectionId": "16-ASIAN_TOTAL-1",
                    "opps": [
                        {
                            "id": 201,
                            "name": "Více než 2.5",
                            "odd": 1.9,
                            "bettingEnabled": True,
                            "type": "o",
                            "oppNumber": "001",
                        },
                    ],
                },
            ],
        }
    ],
}


def test_parse_all_selections() -> None:
    rows = parse_selections(SAMPLE)
    assert len(rows) == 3
    assert {r.opp_id for r in rows} == {101, 102, 201}


def test_my_selection_id_preserved() -> None:
    rows = parse_selections(SAMPLE)
    by_id = {r.opp_id: r for r in rows}
    assert by_id[101].my_selection_id == "16-WINNER_3W-1"
    assert by_id[201].my_selection_id == "16-ASIAN_TOTAL-1"


def test_enriched_match_fields() -> None:
    rows = parse_selections(SAMPLE)
    row = next(r for r in rows if r.opp_id == 101)
    assert row.event_id == 1
    assert row.sport_name == "Fotbal"
    assert row.match_type == "PREMATCH"
    assert row.home_participant == "Ostrava"


def test_tipsport_snapshot_shape() -> None:
    rows = parse_selections(SAMPLE)
    row = next(r for r in rows if r.opp_id == 201)
    assert set(row.tipsport_snapshot) == {"match", "event", "opp"}
    assert row.tipsport_snapshot["event"]["mySelectionId"] == "16-ASIAN_TOTAL-1"
    assert row.tipsport_snapshot["opp"]["id"] == 201


def test_null_participants_allowed() -> None:
    payload = {
        "matches": [
            {
                "id": 1,
                "name": "Top scorer",
                "nameCompetition": "Premier League",
                "events": [
                    {
                        "id": 9,
                        "name": "Nejlepší střelec",
                        "mySelectionId": "16-TOP_GOALSCORER-a",
                        "opps": [{"id": 11, "name": "Player A", "odd": 8.0, "bettingEnabled": True}],
                    }
                ],
            }
        ]
    }
    row = parse_selections(payload)[0]
    assert row.home_participant is None
    assert row.visiting_participant is None


def test_tipsport_snapshot_from_tracked_roundtrip_fields() -> None:
    row = parse_selections(SAMPLE)[0]
    tracked = tracked_from_row(row)
    snap = tipsport_snapshot_from_tracked(tracked)
    assert snap["match"]["id"] == row.match_id
    assert snap["event"]["mySelectionId"] == row.my_selection_id
    assert snap["opp"]["id"] == row.opp_id
    assert snap["opp"]["odd"] == row.odd


def test_build_tipsport_snapshot() -> None:
    match = {"id": 1, "name": "A - B", "idCompetition": 5}
    event = {"id": 2, "mySelectionId": "16-WINNER_3W-1"}
    opp = {"id": 3, "odd": 2.0}
    snap = build_tipsport_snapshot(match, event, opp)
    assert snap["match"]["idCompetition"] == 5
    assert snap["opp"]["odd"] == 2.0
