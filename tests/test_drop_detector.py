"""Unit tests for drop detection."""

import pytest

from deltax.config import DropTier
from deltax.drop_detector import (
    MonitorStore,
    PriceSample,
    SelectionState,
    compute_drop_pct,
    compute_implied_drop_pct,
    evaluate_selection,
    mark_market_alerted,
    odds_at_or_before,
    pick_market_alerts,
    purge_stale_selections,
    sample_at_or_before,
    update_selection_state,
)
from deltax.parser import SelectionRow


def _row(**kwargs) -> SelectionRow:
    defaults = {
        "opp_id": 1,
        "event_id": 10,
        "match_id": 100,
        "my_selection_id": "16-WINNER_3W-1",
        "match_name": "A - B",
        "home_participant": "A",
        "visiting_participant": "B",
        "competition_name": "League",
        "sport_name": "Fotbal",
        "super_sport_name": "Fotbal",
        "match_type": "PREMATCH",
        "event_name": "Match result",
        "opp_name": "A",
        "odd": 2.0,
        "betting_enabled": True,
        "opp_type": "1",
        "opp_number": None,
        "match_url": "/kurzy/zapas/a-b/100",
        "date_start": None,
        "tipsport_snapshot": {"match": {}, "event": {}, "opp": {}},
    }
    defaults.update(kwargs)
    return SelectionRow(**defaults)


TIERS = (
    DropTier(window_seconds=0, drop_pct=10),
    DropTier(window_seconds=180, drop_pct=15),
)


def test_compute_drop_pct_shortening() -> None:
    assert compute_drop_pct(2.0, 1.8) == pytest.approx(10.0)


def test_compute_implied_drop_pct() -> None:
    assert compute_implied_drop_pct(1.9, 1.73) == pytest.approx(5.2, abs=0.1)


def test_tier_requires_both_drop_methods() -> None:
    state = SelectionState(row=_row(odd=1.73))
    state.history = [PriceSample(ts=0.0, odd=1.9), PriceSample(ts=30.0, odd=1.73)]
    tier = DropTier(window_seconds=0, drop_pct=10, implied_drop_pct=6)
    assert evaluate_selection(state, now_ts=30.0, tiers=(tier,), market_armed=True) is None

    tier_ok = DropTier(window_seconds=0, drop_pct=8, implied_drop_pct=5)
    hit = evaluate_selection(state, now_ts=30.0, tiers=(tier_ok,), market_armed=True)
    assert hit is not None
    assert hit.drop_pct == pytest.approx(8.95, abs=0.1)
    assert hit.implied_drop_pct == pytest.approx(5.2, abs=0.1)


def test_zero_implied_threshold_disables_check() -> None:
    state = SelectionState(row=_row(odd=1.73))
    state.history = [PriceSample(ts=0.0, odd=1.9), PriceSample(ts=30.0, odd=1.73)]
    tier = DropTier(window_seconds=0, drop_pct=8, implied_drop_pct=0)
    hit = evaluate_selection(state, now_ts=30.0, tiers=(tier,), market_armed=True)
    assert hit is not None


def test_zero_odds_threshold_disables_check() -> None:
    state = SelectionState(row=_row(odd=1.73))
    state.history = [PriceSample(ts=0.0, odd=1.9), PriceSample(ts=30.0, odd=1.73)]
    tier = DropTier(window_seconds=0, drop_pct=0, implied_drop_pct=5)
    hit = evaluate_selection(state, now_ts=30.0, tiers=(tier,), market_armed=True)
    assert hit is not None
    assert hit.implied_drop_pct == pytest.approx(5.2, abs=0.1)


def test_odds_at_or_before() -> None:
    history = [
        PriceSample(ts=100.0, odd=2.5),
        PriceSample(ts=200.0, odd=2.2),
        PriceSample(ts=300.0, odd=2.0),
    ]
    assert odds_at_or_before(history, 150.0) == 2.5
    assert odds_at_or_before(history, 250.0) == 2.2
    assert odds_at_or_before(history, 50.0) is None


def test_sample_at_or_before() -> None:
    history = [PriceSample(ts=100.0, odd=2.5), PriceSample(ts=200.0, odd=2.2)]
    sample = sample_at_or_before(history, 150.0)
    assert sample is not None
    assert sample.ts == 100.0


def test_zero_window_compares_previous_poll() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=2.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, state, _row(odd=1.8), now_ts=30.0, max_window_seconds=600)

    hit = evaluate_selection(state, now_ts=30.0, tiers=TIERS, market_armed=True)
    assert hit is not None
    assert hit.odds_previous == 2.0
    assert hit.baseline_observed_at == 0.0
    assert hit.current_observed_at == 30.0
    assert hit.tier.window_seconds == 0


def test_no_alert_on_first_poll() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=2.0), now_ts=10.0, max_window_seconds=600)
    hits = pick_market_alerts(store, now_ts=10.0, tiers=TIERS, max_odds=0.0)
    assert hits == []


def test_tier_fires_on_window_baseline() -> None:
    state = SelectionState(row=_row(odd=1.8))
    state.history = [
        PriceSample(ts=0.0, odd=2.0),
        PriceSample(ts=180.0, odd=1.9),
        PriceSample(ts=210.0, odd=1.8),
    ]
    hit = evaluate_selection(
        state,
        now_ts=210.0,
        tiers=(DropTier(window_seconds=180, drop_pct=10),),
        market_armed=True,
    )
    assert hit is not None
    assert hit.odds_previous == 2.0
    assert hit.baseline_observed_at == 0.0
    assert hit.drop_pct == pytest.approx(10.0)


def test_realert_after_recovery() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(opp_id=1, odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=2.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, state, _row(odd=1.8), now_ts=30.0, max_window_seconds=600)
    hits = pick_market_alerts(store, now_ts=30.0, tiers=TIERS, max_odds=0.0)
    assert len(hits) == 1
    mark_market_alerted(store, hits[0])

    update_selection_state(store, state, _row(odd=2.0), now_ts=120.0, max_window_seconds=600)
    assert store.markets[(100, "16-WINNER_3W-1")].armed

    update_selection_state(store, state, _row(odd=1.7), now_ts=180.0, max_window_seconds=600)
    hits2 = pick_market_alerts(store, now_ts=180.0, tiers=TIERS, max_odds=0.0)
    assert len(hits2) == 1


def test_market_picks_highest_drop() -> None:
    store = MonitorStore()
    home = SelectionState(row=_row(opp_id=1, opp_name="Home", odd=2.0))
    away = SelectionState(row=_row(opp_id=2, opp_name="Away", odd=2.0))
    store.selections[1] = home
    store.selections[2] = away
    update_selection_state(store, home, _row(opp_id=1, odd=2.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, away, _row(opp_id=2, odd=2.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, home, _row(opp_id=1, odd=1.9), now_ts=30.0, max_window_seconds=600)
    update_selection_state(store, away, _row(opp_id=2, odd=1.6), now_ts=30.0, max_window_seconds=600)

    hits = pick_market_alerts(store, now_ts=30.0, tiers=TIERS, max_odds=0.0)
    assert len(hits) == 1
    assert hits[0].opp_id == 2
    assert hits[0].drop_pct == pytest.approx(20.0)


def test_max_odds_filters_before_market_winner() -> None:
    store = MonitorStore()
    home = SelectionState(row=_row(opp_id=1, opp_name="Home", odd=3.0))
    away = SelectionState(row=_row(opp_id=2, opp_name="Away", odd=6.0))
    store.selections[1] = home
    store.selections[2] = away
    update_selection_state(store, home, _row(opp_id=1, odd=3.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, away, _row(opp_id=2, odd=6.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, home, _row(opp_id=1, odd=2.5), now_ts=30.0, max_window_seconds=600)
    update_selection_state(store, away, _row(opp_id=2, odd=5.0), now_ts=30.0, max_window_seconds=600)

    hits = pick_market_alerts(store, now_ts=30.0, tiers=TIERS, max_odds=5.0)
    assert len(hits) == 1
    assert hits[0].opp_id == 1
    assert hits[0].odds_now == pytest.approx(2.5)


def test_max_odds_excludes_longshot_selections() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=8.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=8.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, state, _row(odd=7.0), now_ts=30.0, max_window_seconds=600)

    hits = pick_market_alerts(store, now_ts=30.0, tiers=TIERS, max_odds=5.0)
    assert hits == []


def test_ignore_disabled_selection_updates() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=1.5, betting_enabled=False), now_ts=10.0, max_window_seconds=600)
    assert state.history == []


def test_only_changed_selections_are_evaluated() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=2.0), now_ts=0.0, max_window_seconds=600)
    update_selection_state(store, state, _row(odd=1.8), now_ts=30.0, max_window_seconds=600)
    store.changed_opp_ids.clear()

    update_selection_state(store, state, _row(odd=1.8), now_ts=60.0, max_window_seconds=600)
    hits = pick_market_alerts(store, now_ts=60.0, tiers=TIERS, max_odds=0.0)
    assert hits == []


def test_soft_delete_keeps_history_until_ttl() -> None:
    store = MonitorStore()
    state = SelectionState(row=_row(odd=2.0))
    store.selections[1] = state
    update_selection_state(store, state, _row(odd=2.0), now_ts=0.0, max_window_seconds=600)
    state.last_seen_ts = 0.0

    assert purge_stale_selections(store, now_ts=100.0, ttl_seconds=600) == 0
    assert 1 in store.selections

    assert purge_stale_selections(store, now_ts=700.0, ttl_seconds=600) == 1
    assert 1 not in store.selections
