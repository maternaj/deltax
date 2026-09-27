"""PinnacleSource relative-unit fetch tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from deltax.config import AppConfig, load_config
from deltax.parser import SelectionRow
from deltax.sources import PinnacleSource


def _pinnacle_config() -> AppConfig:
    raw = yaml.safe_load(open("config.pinnacle.yaml", encoding="utf-8"))
    return load_config(env={"DELTAX_CONFIG_PATH": "config.pinnacle.yaml"})


def _selection_row(**kwargs) -> SelectionRow:
    defaults = {
        "opp_id": 1,
        "event_id": 10,
        "match_id": 100,
        "my_selection_id": "29-0-SPREAD-HOME",
        "match_name": "A (Corners) - B (Corners)",
        "home_participant": "A (Corners)",
        "visiting_participant": "B (Corners)",
        "competition_name": "League",
        "sport_name": "Soccer",
        "super_sport_name": "Soccer",
        "match_type": "PREMATCH",
        "event_name": "Handicap",
        "opp_name": "A (Corners)",
        "odd": 1.8,
        "betting_enabled": True,
        "opp_type": "1",
        "opp_number": None,
        "match_url": "/en/soccer/league/10",
        "date_start": 1_700_000_000_000,
        "tipsport_snapshot": {"match": {"id": 100}, "event": {"id": 10}, "opp": {"id": 1}},
    }
    defaults.update(kwargs)
    return SelectionRow(**defaults)


def test_load_config_rejects_empty_relative_units(tmp_path) -> None:
    config_path = tmp_path / "config.pinnacle.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "source": "pinnacle",
                "pinnacle": {
                    "relative_units": [],
                    "sports": [{"sport_id": 29, "market_kinds": [0, 1]}],
                },
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
                "markets": {
                    "wanted": ["29-0-SPREAD-HOME"],
                    "pending": [],
                    "blacklisted": [],
                    "blacklisted_prefixes": [],
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="relative_units"):
        load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})


def test_fetch_fails_when_relative_unit_fully_fails(monkeypatch) -> None:
    config = _pinnacle_config()
    client = MagicMock()
    client.fetch_relative_markets_bulk.return_value = None
    source = PinnacleSource(config, config.pinnacle, client=client)

    rows, ok = source.fetch_selections()

    assert ok is False
    assert rows == []
    assert client.fetch_relative_markets_bulk.call_count == 4


def test_fetch_ok_when_one_feed_fails_other_succeeds(monkeypatch) -> None:
    config = _pinnacle_config()
    client = MagicMock()
    row = _selection_row()

    def _fetch(sport_id: int, market_kind: int, relative_unit: str):
        if relative_unit == "Bookings" and market_kind == 0:
            return None
        return {"n": []}

    client.fetch_relative_markets_bulk.side_effect = _fetch
    source = PinnacleSource(config, config.pinnacle, client=client)
    monkeypatch.setattr(
        PinnacleSource,
        "_flatten_sport_feed",
        lambda self, body, sport, sport_slug_overrides: [row],
    )

    rows, ok = source.fetch_selections()

    assert ok is True
    assert len(rows) == 1


def test_dedupe_prefers_later_mk(monkeypatch) -> None:
    config = _pinnacle_config()
    client = MagicMock()
    client.fetch_relative_markets_bulk.return_value = {"n": []}
    source = PinnacleSource(config, config.pinnacle, client=client)

    calls: list[int] = []

    def _flatten(self, body, sport, sport_slug_overrides):
        calls.append(len(calls))
        return [_selection_row(opp_id=99, odd=1.5 + 0.1 * len(calls))]

    monkeypatch.setattr(PinnacleSource, "_flatten_sport_feed", _flatten)

    rows, ok = source.fetch_selections()

    assert ok is True
    assert len(rows) == 1
    assert len(calls) == 4
    assert rows[0].odd == pytest.approx(1.9)
