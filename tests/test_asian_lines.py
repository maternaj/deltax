"""Asian line classification tests — patterns from Tipsport offer feed."""

import json
from pathlib import Path

from deltax.settle.asian_lines import (
    is_asian_market,
    is_quarter_line_alert,
    is_quarter_line_opp,
)

QUARTER_LINE_NAMES = (
    "Nieciecza -0.75 (-0.5, -1.0)",
    "Piast Gliwice -0.75 (-0.5, -1.0)",
    "Více než 2.25 (2.0, 2.5)",
    "Méně než 2.25 (2.0, 2.5)",
    "Méně než 2.75 (2.5, 3.0)",
    "Piast Gliwice -0.25 (-0.0, -0.5)",
    "Radom -1.25 (-1.0, -1.5)",
    "Piast Gliwice +0.75 (+0.5, +1.0)",
)

WHOLE_OR_HALF_NAMES = (
    "Více než 1.5",
    "Méně než 1.5",
    "Nieciecza -2.5",
    "Dagenham & Redbridge +1.5",
    "Hampton & Richmond -2.5",
)


def test_is_asian_market() -> None:
    assert is_asian_market("16-ASIAN_TOTAL-1")
    assert is_asian_market("16-ASIAN_HANDICAP_2W_HOME-1")
    assert not is_asian_market("16-WINNER_3W-1")


def test_is_quarter_line_opp_split_paren() -> None:
    for name in QUARTER_LINE_NAMES:
        assert is_quarter_line_opp(name), name


def test_is_quarter_line_opp_whole_half_and_team_ampersand() -> None:
    for name in WHOLE_OR_HALF_NAMES:
        assert not is_quarter_line_opp(name), name


def test_is_quarter_line_alert_requires_asian_market() -> None:
    assert is_quarter_line_alert(
        my_selection_id="16-ASIAN_TOTAL-1",
        opp_name="Více než 2.25 (2.0, 2.5)",
    )
    assert not is_quarter_line_alert(
        my_selection_id="16-TOTAL_GOALS-1",
        opp_name="Více než 2.25 (2.0, 2.5)",
    )
    assert not is_quarter_line_alert(
        my_selection_id="16-ASIAN_HANDICAP_2W_HOME-1",
        opp_name="Nieciecza -2.5",
    )


def test_fixture_opp_name_examples() -> None:
    fixture = Path(__file__).parent / "fixtures" / "asian_opp_names.json"
    names = json.loads(fixture.read_text(encoding="utf-8"))
    expected_quarter = {
        "Nieciecza -0.75 (-0.5, -1.0)",
        "Více než 2.25 (2.0, 2.5)",
        "Méně než 2.75 (2.5, 3.0)",
        "Radom -1.25 (-1.0, -1.5)",
    }
    expected_whole = {
        "Více než 1.5",
        "Dagenham & Redbridge +1.5",
    }
    for name in names:
        if name in expected_quarter:
            assert is_quarter_line_opp(name)
        elif name in expected_whole:
            assert not is_quarter_line_opp(name)
        else:
            raise AssertionError(f"Unhandled fixture name: {name}")
