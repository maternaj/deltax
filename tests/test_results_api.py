"""Tipsport results API parsing tests."""

import json
from pathlib import Path

from deltax.settle.results_api import match_has_results, parse_result_cells

FIXTURE = Path(__file__).parent / "fixtures" / "match_results_sample.json"


def test_match_has_results() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert match_has_results(data)
    assert not match_has_results({"match": {}})


def test_parse_result_cells() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cells = parse_result_cells(data)
    assert set(cells) == {2567010869, 2567010868, 9001, 9002, 9003, 9004}
    assert cells[2567010869].winning is True
    assert cells[2567010869].odd == 2.14
    assert cells[2567010868].odd == 1.0
    assert cells[9001].observed_at is None
