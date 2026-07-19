"""Parser tests."""

from deltax.parser import extract_market_type, parse_selections

SAMPLE = {
    "count": 1,
    "matches": [
        {
            "id": 7154537,
            "name": "Ostrava - Slavia Praha",
            "nameCompetition": "Česká Chance Liga",
            "matchUrl": "/kurzy/zapas/fotbal-ostrava-slavia-praha/7154537",
            "dateStart": 1775395800000,
            "events": [
                {
                    "id": 1,
                    "name": "Výsledek zápasu",
                    "mySelectionId": "16-WINNER_3W-1",
                    "opps": [
                        {"id": 101, "name": "Ostrava", "odd": 4.5, "bettingEnabled": True},
                        {"id": 102, "name": "Remíza", "odd": 3.8, "bettingEnabled": False},
                    ],
                },
                {
                    "id": 2,
                    "name": "Počet gólů",
                    "mySelectionId": "16-ASIAN_TOTAL-1",
                    "opps": [
                        {"id": 201, "name": "Více než 2.5", "odd": 1.9, "bettingEnabled": True},
                    ],
                },
            ],
        }
    ],
}


def test_extract_market_type() -> None:
    assert extract_market_type("16-WINNER_3W-1") == "WINNER_3W"


def test_parse_all_selections() -> None:
    rows = parse_selections(SAMPLE)
    assert len(rows) == 3
    assert {r.opp_id for r in rows} == {101, 102, 201}


def test_market_types_preserved() -> None:
    rows = parse_selections(SAMPLE)
    by_id = {r.opp_id: r for r in rows}
    assert by_id[101].market_type == "WINNER_3W"
    assert by_id[201].market_type == "ASIAN_TOTAL"
