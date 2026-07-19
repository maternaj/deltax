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
        return self.row.match_id, self.row.market_type


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
    market_type: str
    drop_pct: float
    baseline_odds: float
    current_odds: float
    tier: DropTier
    row: SelectionRow


def odds_at_or_before(history: list[PriceSample], target_ts: float) -> float | None:
    result: float | None = None
    for sample in history:
        if sample.ts <= target_ts:
            result = sample.odd
        else:
            break
    return result


def compute_drop_pct(baseline: float, current: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - current) / baseline * 100.0


def _baseline_for_tier(state: SelectionState, *, now_ts: float, tier: DropTier) -> float | None:
    if tier.window_seconds == 0:
        if len(state.history) < 2:
            return None
        return state.history[-2].odd
    baseline_ts = now_ts - tier.window_seconds
    return odds_at_or_before(state.history, baseline_ts)


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

    current = state.history[-1].odd
    best: DropHit | None = None

    for tier in tiers:
        baseline = _baseline_for_tier(state, now_ts=now_ts, tier=tier)
        if baseline is None:
            continue
        drop_pct = compute_drop_pct(baseline, current)
        if drop_pct + 1e-9 < tier.drop_pct:
            continue
        hit = DropHit(
            opp_id=state.opp_id,
            match_id=state.row.match_id,
            market_type=state.row.market_type,
            drop_pct=drop_pct,
            baseline_odds=baseline,
            current_odds=current,
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
    key = hit.match_id, hit.market_type
    store.markets[key] = MarketAlertState(
        alerted_opp_id=hit.opp_id,
        last_alert_odds=hit.current_odds,
        armed=False,
    )


def pick_market_alerts(
    store: MonitorStore,
    *,
    now_ts: float,
    tiers: tuple[DropTier, ...],
) -> list[DropHit]:
    """One alert per (match_id, market_type) among selections whose odds changed."""
    if not store.changed_opp_ids:
        return []

    best_by_market: dict[tuple[int, str], DropHit] = {}
    for opp_id in store.changed_opp_ids:
        state = store.selections.get(opp_id)
        if state is None:
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
        key = hit.match_id, hit.market_type
        existing = best_by_market.get(key)
        if existing is None or hit.drop_pct > existing.drop_pct:
            best_by_market[key] = hit
    store.changed_opp_ids.clear()
    return list(best_by_market.values())
