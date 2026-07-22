"""Settlement void rule tests."""

from deltax.settle.constants import RESULT_LOSS, RESULT_VOID, SOURCE_VOID_RULE
from deltax.settle.void_rules import SettlementDraft, apply_void_rules


def _draft(
    *,
    alert_id: int,
    event_id: int,
    my_selection_id: str,
    opp_name: str,
    selection_result: str = RESULT_LOSS,
) -> SettlementDraft:
    return SettlementDraft(
        alert_id=alert_id,
        opp_id=alert_id,
        event_id=event_id,
        match_id=1,
        my_selection_id=my_selection_id,
        opp_name=opp_name,
        selection_result=selection_result,
        result_source="tipsport_results",
    )


def test_asian_push_void_when_both_sides_lost() -> None:
    drafts = [
        _draft(
            alert_id=1,
            event_id=10,
            my_selection_id="16-ASIAN_HANDICAP_2W_HOME-1",
            opp_name="Team A -1.5",
        ),
        _draft(
            alert_id=2,
            event_id=10,
            my_selection_id="16-ASIAN_HANDICAP_2W_AWAY-1",
            opp_name="Team B +1.5",
        ),
    ]
    apply_void_rules(drafts)
    assert drafts[0].selection_result == RESULT_VOID
    assert drafts[1].selection_result == RESULT_VOID
    assert drafts[0].result_source == SOURCE_VOID_RULE


def test_quarter_line_not_voided_by_push_rule() -> None:
    drafts = [
        _draft(
            alert_id=1,
            event_id=11,
            my_selection_id="16-ASIAN_TOTAL-1",
            opp_name="Více než 2.25 (2.0, 2.5)",
        ),
        _draft(
            alert_id=2,
            event_id=11,
            my_selection_id="16-ASIAN_TOTAL-1",
            opp_name="Méně než 2.25 (2.0, 2.5)",
        ),
    ]
    apply_void_rules(drafts)
    assert drafts[0].selection_result == RESULT_LOSS
    assert drafts[1].selection_result == RESULT_LOSS


def test_half_goal_void_when_both_sides_lost() -> None:
    drafts = [
        _draft(
            alert_id=3,
            event_id=20,
            my_selection_id="16-TOTAL_GOALS-1",
            opp_name="Více než 0.5",
        ),
        _draft(
            alert_id=4,
            event_id=20,
            my_selection_id="16-TOTAL_GOALS-1",
            opp_name="Méně než 0.5",
        ),
    ]
    apply_void_rules(drafts)
    assert drafts[0].selection_result == RESULT_VOID
    assert drafts[1].selection_result == RESULT_VOID


def test_half_goal_void_not_applied_to_duplicate_same_side_alerts() -> None:
    drafts = [
        _draft(
            alert_id=29,
            event_id=2253385915,
            my_selection_id="16-TOTAL_PARTICIPANT-1",
            opp_name="Více než 0.5",
        ),
        _draft(
            alert_id=156,
            event_id=2253385915,
            my_selection_id="16-TOTAL_PARTICIPANT-1",
            opp_name="Více než 0.5",
        ),
        _draft(
            alert_id=31,
            event_id=2253385915,
            my_selection_id="16-TOTAL_PARTICIPANT-1",
            opp_name="Méně než 0.5",
            selection_result="W",
        ),
    ]
    apply_void_rules(drafts)
    assert drafts[0].selection_result == RESULT_LOSS
    assert drafts[1].selection_result == RESULT_LOSS
    assert drafts[0].result_source == "tipsport_results"


def test_half_goal_void_not_applied_to_duplicate_under_alerts() -> None:
    drafts = [
        _draft(
            alert_id=103,
            event_id=2255338658,
            my_selection_id="16-TOTAL_PARTICIPANT-1",
            opp_name="Méně než 0.5",
        ),
        _draft(
            alert_id=120,
            event_id=2255338658,
            my_selection_id="16-TOTAL_PARTICIPANT-1",
            opp_name="Méně než 0.5",
        ),
    ]
    apply_void_rules(drafts)
    assert drafts[0].selection_result == RESULT_LOSS
    assert drafts[1].selection_result == RESULT_LOSS
