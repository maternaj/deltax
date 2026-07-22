"""Post-processing void rules after Tipsport W/L mapping."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from deltax.settle.asian_lines import is_asian_market, is_quarter_line_alert
from deltax.settle.constants import RESULT_LOSS, RESULT_VOID, SOURCE_VOID_RULE

_HALF_GOAL_RE = re.compile(r"0\.5")


@dataclass
class SettlementDraft:
    alert_id: int
    opp_id: int
    event_id: int
    match_id: int
    my_selection_id: str
    opp_name: str
    selection_result: str | None
    result_source: str | None


def _half_goal_side(opp_name: str) -> str | None:
    text = str(opp_name or "").strip().lower()
    if not _HALF_GOAL_RE.search(text):
        return None
    if text.startswith(("více než", "over")):
        return "over"
    if text.startswith(("méně než", "under")):
        return "under"
    return None


def apply_void_rules(drafts: list[SettlementDraft]) -> None:
    """Mutate drafts in place — Asian push and goal/no-goal voids."""
    _apply_asian_push_voids(drafts)
    _apply_half_goal_voids(drafts)


def _apply_asian_push_voids(drafts: list[SettlementDraft]) -> None:
    by_event: dict[int, list[SettlementDraft]] = defaultdict(list)
    for draft in drafts:
        if draft.selection_result != RESULT_LOSS:
            continue
        if not is_asian_market(draft.my_selection_id):
            continue
        if is_quarter_line_alert(
            my_selection_id=draft.my_selection_id,
            opp_name=draft.opp_name,
        ):
            continue
        by_event[draft.event_id].append(draft)

    for group in by_event.values():
        if len(group) < 2:
            continue
        if not all(item.selection_result == RESULT_LOSS for item in group):
            continue
        for item in group:
            item.selection_result = RESULT_VOID
            item.result_source = SOURCE_VOID_RULE


def _apply_half_goal_voids(drafts: list[SettlementDraft]) -> None:
    """Void only when both over 0.5 and under 0.5 are L on the same event (magu DNP pattern).

    Duplicate alerts on the same side must not trigger this — e.g. two 'Více než 0.5' losses.
    """
    by_event: dict[int, dict[str, list[SettlementDraft]]] = defaultdict(lambda: defaultdict(list))
    for draft in drafts:
        if draft.selection_result != RESULT_LOSS:
            continue
        side = _half_goal_side(draft.opp_name)
        if side is None:
            continue
        by_event[draft.event_id][side].append(draft)

    for sides in by_event.values():
        over_losses = sides.get("over", [])
        under_losses = sides.get("under", [])
        if not over_losses or not under_losses:
            continue
        for item in over_losses + under_losses:
            item.selection_result = RESULT_VOID
            item.result_source = SOURCE_VOID_RULE
