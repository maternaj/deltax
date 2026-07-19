"""Unit tests for drop detection."""

import pytest

from deltax.config import DropTier
from deltax.drop_detector import (
    MonitorStore,
    PriceSample,
    SelectionState,
    compute_drop_pct,
    evaluate_selection,
    mark_market_alerted,
    odds_at_or_before,
    pick_market_alerts,
    update_selection_state,
)
from deltax.parser import SelectionRow


def _row(**kwargs) -> SelectionRow:
    defaults = {
        "opp_id": 1,
        "match_id": 100,
        "market_type": "WINNER_3W",
        "match_name": "A - B",
        "competition_name": "League",
        "event_name": "Match result",
        "opp_name": "A",
        "odd": 2.0,
        "betting_enabled": True,
        "match_url": "/kurzy/zapas/a-b/100",
        "my_selection_id": "16-WINNER_3W-1",
        "date_start": None,
    }
    defaults.update(kwargs)
    return SelectionRow(**defaults)


TIERS = (
    DropTier(window_seconds=60, drop_pct=10),
    DropTier(window_seconds=180, drop_pct=15),
)


def test_compute_drop_pct_shortening() -> None:
    assert compute_drop_pct(2.0, 1.8) == pytest.approx(10.0)


def test_odds_at_or_before() -> None:
    history = [
        PriceSample(ts=100.0, odd=2.5),
        PriceSample(ts=200.0, odd=2.2),
        PriceSample(ts=300.0, odd=2.0),
    ]
    assert odds_at_or_before(history, 150.0) == 2.5
    assert odds_at_or_before(history, 250.0) == 2.2
    assert odds_at_or_before(history, 50.0) is None


def test_tier_fires_on_window_baseline() -> None:
    state = SelectionState(row=_row(odd=1.8))
    state.history = [
        PriceSample(ts=0.0, odd=2.0),
        PriceSample(ts=120.0, odd=1.8),
    ]
    hit = evaluate_selection(state, now_ts=120.0, tiers=TIERS, market_armed=True)
    assert hit is not None
    assert hit.baseline_odds == 2.0
    assert hit.drop_pct == pytest.approx(10.0)


def test_no_alert_when_not_enough_history() -> None:
    state = SelectionState(row=_row(odd=1.5))
    state.history = [PriceSample(ts=10.0, odd=1.5)]
    hit = evaluate_selection(state, now_ts=10.0, tiers=TIERS, market_armed=True)
    assert hit is None


def test_realert_after_recovery() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(opp_id=1, odd=1.8))
    store.selections[1] = state
    state.history = [
        PriceSample(ts=0.0, odd=2.0),
        PriceSample(ts=60.0, odd=1.8),
    ]
    hits = pick_market_alerts(store, now_ts=60.0, tiers=TIERS)
    assert len(hits) == 1
    mark_market_alerted(store, hits[0])

    update_selection_state(store, state, _row(odd=2.0), now_ts=120.0, max_window_seconds=600)
    assert store.markets[(100, "WINNER_3W")].armed

    update_selection_state(store, state, _row(odd=1.7), now_ts=180.0, max_window_seconds=600)
    hits2 = pick_market_alerts(store, now_ts=180.0, tiers=TIERS)
    assert len(hits2) == 1


def test_market_picks_highest_drop() -> None:
    store = MonitorStore()
    home = SelectionState(row=_row(opp_id=1, opp_name="Home", odd=1.9))
    away = SelectionState(row=_row(opp_id=2, opp_name="Away", odd=1.6))
    for state, current in ((home, 1.9), (away, 1.6)):
        state.history = [
            PriceSample(ts=0.0, odd=2.0),
            PriceSample(ts=120.0, odd=current),
        ]
        store.selections[state.opp_id] = state
    hits = pick_market_alerts(store, now_ts=120.0, tiers=TIERS)
    assert len(hits) == 1
    assert hits[0].opp_id == 2
    assert hits[0].drop_pct == pytest.approx(20.0)


def test_ignore_disabled_selection_updates() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=1.5, betting_enabled=False), now_ts=10.0, max_window_seconds=600)
    assert state.history == []
