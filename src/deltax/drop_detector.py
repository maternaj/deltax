"""In-memory odds history and drop detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from deltax.config import DropTier
from deltax.parser import SelectionRow


@dataclass
class PriceSample:
    ts: float
    odd: float


@dataclass
class SelectionState:
    row: SelectionRow
    history: list[PriceSample] = field(default_factory=list)
    last_odd: float | None = None
    last_seen_ts: float = 0.0

    @property
    def opp_id(self) -> int:
        return self.row.opp_id

    @property
    def market_key(self) -> tuple[int, str]:
        return self.row.match_id, self.row.my_selection_id


@dataclass
class MarketAlertState:
    alerted_opp_id: int | None = None
    last_alert_odds: float | None = None
    armed: bool = True


@dataclass
class MonitorStore:
    selections: dict[int, SelectionState] = field(default_factory=dict)
    markets: dict[tuple[int, str], MarketAlertState] = field(default_factory=dict)
    changed_opp_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class DropHit:
    opp_id: int
    match_id: int
    my_selection_id: str
    drop_pct: float
    implied_drop_pct: float
    odds_previous: float
    odds_now: float
    baseline_observed_at: float
    current_observed_at: float
    tier: DropTier
    row: SelectionRow


def sample_at_or_before(history: list[PriceSample], target_ts: float) -> PriceSample | None:
    result: PriceSample | None = None
    for sample in history:
        if sample.ts <= target_ts:
            result = sample
        else:
            break
    return result


def odds_at_or_before(history: list[PriceSample], target_ts: float) -> float | None:
    sample = sample_at_or_before(history, target_ts)
    return sample.odd if sample is not None else None


def compute_drop_pct(baseline: float, current: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - current) / baseline * 100.0


def compute_implied_drop_pct(baseline: float, current: float) -> float:
    """Implied-probability shift: (1/current - 1/baseline) × 100."""
    if baseline <= 0 or current <= 0:
        return 0.0
    return (1.0 / current - 1.0 / baseline) * 100.0


def _passes_drop_threshold(actual: float, threshold: float) -> bool:
    if threshold <= 0:
        return True
    return actual + 1e-9 >= threshold


def _baseline_sample_for_tier(
    state: SelectionState,
    *,
    now_ts: float,
    tier: DropTier,
) -> PriceSample | None:
    if tier.window_seconds == 0:
        if len(state.history) < 2:
            return None
        return state.history[-2]
    baseline_ts = now_ts - tier.window_seconds
    return sample_at_or_before(state.history, baseline_ts)


def evaluate_selection(
    state: SelectionState,
    *,
    now_ts: float,
    tiers: tuple[DropTier, ...],
    market_armed: bool,
) -> DropHit | None:
    if not market_armed:
        return None
    if len(state.history) < 2:
        return None

    current_sample = state.history[-1]
    current = current_sample.odd
    best: DropHit | None = None

    for tier in tiers:
        baseline_sample = _baseline_sample_for_tier(state, now_ts=now_ts, tier=tier)
        if baseline_sample is None:
            continue
        drop_pct = compute_drop_pct(baseline_sample.odd, current)
        implied_drop_pct = compute_implied_drop_pct(baseline_sample.odd, current)
        if not _passes_drop_threshold(drop_pct, tier.drop_pct):
            continue
        if not _passes_drop_threshold(implied_drop_pct, tier.implied_drop_pct):
            continue
        hit = DropHit(
            opp_id=state.opp_id,
            match_id=state.row.match_id,
            my_selection_id=state.row.my_selection_id,
            drop_pct=drop_pct,
            implied_drop_pct=implied_drop_pct,
            odds_previous=baseline_sample.odd,
            odds_now=current,
            baseline_observed_at=baseline_sample.ts,
            current_observed_at=current_sample.ts,
            tier=tier,
            row=state.row,
        )
        if best is None or hit.drop_pct > best.drop_pct:
            best = hit
    return best


def trim_history(history: list[PriceSample], *, cutoff_ts: float) -> None:
    if not history:
        return
    idx = 0
    while idx < len(history) and history[idx].ts < cutoff_ts:
        idx += 1
    if idx:
        del history[:idx]


def update_market_recovery(
    store: MonitorStore,
    *,
    market_key: tuple[int, str],
    opp_id: int,
    odd: float,
) -> None:
    market = store.markets.get(market_key)
    if market is None or market.armed:
        return
    if market.alerted_opp_id != opp_id or market.last_alert_odds is None:
        return
    if odd > market.last_alert_odds:
        market.armed = True
        market.alerted_opp_id = None
        market.last_alert_odds = None


def update_selection_state(
    store: MonitorStore,
    state: SelectionState,
    row: SelectionRow,
    *,
    now_ts: float,
    max_window_seconds: int,
) -> bool:
    """Update in-memory state. Returns True when odds changed vs previous sample."""
    state.row = row
    state.last_seen_ts = now_ts
    if not row.betting_enabled:
        return False

    previous_odd = state.last_odd
    state.last_odd = row.odd
    state.history.append(PriceSample(ts=now_ts, odd=row.odd))
    cutoff = now_ts - max_window_seconds - 120
    trim_history(state.history, cutoff_ts=cutoff)
    update_market_recovery(store, market_key=state.market_key, opp_id=state.opp_id, odd=row.odd)

    changed = previous_odd is not None and previous_odd != row.odd
    if changed:
        store.changed_opp_ids.add(state.opp_id)
    return changed


def purge_stale_selections(store: MonitorStore, *, now_ts: float, ttl_seconds: int) -> int:
    cutoff = now_ts - ttl_seconds
    stale = [opp_id for opp_id, state in store.selections.items() if state.last_seen_ts < cutoff]
    for opp_id in stale:
        del store.selections[opp_id]
    return len(stale)


def mark_market_alerted(store: MonitorStore, hit: DropHit) -> None:
    key = hit.match_id, hit.my_selection_id
    store.markets[key] = MarketAlertState(
        alerted_opp_id=hit.opp_id,
        last_alert_odds=hit.odds_now,
        armed=False,
    )


def pick_market_alerts(
    store: MonitorStore,
    *,
    now_ts: float,
    tiers: tuple[DropTier, ...],
    max_odds: float = 0.0,
) -> list[DropHit]:
    """One alert per (match_id, my_selection_id) among selections whose odds changed."""
    if not store.changed_opp_ids:
        return []

    best_by_market: dict[tuple[int, str], DropHit] = {}
    for opp_id in store.changed_opp_ids:
        state = store.selections.get(opp_id)
        if state is None:
            continue
        if len(state.history) < 2:
            continue
        current = state.history[-1].odd
        if max_odds > 0 and current - 1e-9 > max_odds:
            continue
        market = store.markets.get(state.market_key)
        market_armed = market.armed if market is not None else True
        hit = evaluate_selection(
            state,
            now_ts=now_ts,
            tiers=tiers,
            market_armed=market_armed,
        )
        if hit is None:
            continue
        key = hit.match_id, hit.my_selection_id
        existing = best_by_market.get(key)
        if existing is None or hit.drop_pct > existing.drop_pct:
            best_by_market[key] = hit
    store.changed_opp_ids.clear()
    return list(best_by_market.values())
