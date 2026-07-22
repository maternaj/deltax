"""Settlement worker logic tests."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deltax.config import SettleConfig
from deltax.settle.constants import RESULT_UNKNOWN, RESULT_WIN, SOURCE_ASIAN_QUARTER, SOURCE_TIPSPORT_RESULTS
from deltax.settle.db import PendingAlert
from deltax.settle.worker import (
    process_match_settlement,
    resolve_alert_draft,
    select_ready_alerts,
)
from deltax.settle.results_api import ResultCell

FIXTURE = Path(__file__).parent / "fixtures" / "match_results_sample.json"
SETTLED_AT = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)


def _pending(**overrides: object) -> PendingAlert:
    base = {
        "alert_id": 1,
        "opp_id": 2567010869,
        "event_id": 100,
        "match_id": 7765938,
        "my_selection_id": "16-WINNER_3W-1",
        "opp_name": "Home",
        "kickoff_at": SETTLED_AT - timedelta(hours=8),
    }
    base.update(overrides)
    return PendingAlert(**base)


def test_select_ready_alerts_respects_market_delay() -> None:
    settle = SettleConfig(
        sleep_seconds=900,
        default_delay_hours=6,
        max_age_days=3,
        batch_match_limit=50,
        match_request_delay_seconds=0,
        market_delay_hours={"16-GOAL_SCORERS-1": 12},
    )
    now = SETTLED_AT
    alerts = [
        _pending(kickoff_at=now - timedelta(hours=7), my_selection_id="16-WINNER_3W-1"),
        _pending(
            alert_id=2,
            kickoff_at=now - timedelta(hours=7),
            my_selection_id="16-GOAL_SCORERS-1",
        ),
        _pending(
            alert_id=3,
            kickoff_at=now - timedelta(hours=13),
            my_selection_id="16-GOAL_SCORERS-1",
        ),
    ]
    ready = select_ready_alerts(alerts, settle=settle, now=now)
    assert 7765938 in ready
    assert len(ready[7765938]) == 2
    assert {item.alert_id for item in ready[7765938]} == {1, 3}


def test_resolve_alert_draft_quarter_line() -> None:
    alert = _pending(
        opp_id=9001,
        my_selection_id="16-ASIAN_TOTAL-1",
        opp_name="Více než 2.25 (2.0, 2.5)",
    )
    draft = resolve_alert_draft(alert, None, settled_at=SETTLED_AT)
    assert draft is not None
    assert draft.selection_result == RESULT_UNKNOWN
    assert draft.result_source == SOURCE_ASIAN_QUARTER


def test_process_match_settlement_end_to_end() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    alerts = [
        _pending(alert_id=1, opp_id=2567010869, opp_name="Home"),
        _pending(
            alert_id=2,
            opp_id=9001,
            my_selection_id="16-ASIAN_TOTAL-1",
            opp_name="Více než 2.25 (2.0, 2.5)",
        ),
        _pending(
            alert_id=3,
            opp_id=9003,
            event_id=200,
            my_selection_id="16-ASIAN_TOTAL-1",
            opp_name="Více než 1.5",
        ),
        _pending(
            alert_id=4,
            opp_id=9004,
            event_id=200,
            my_selection_id="16-ASIAN_TOTAL-1",
            opp_name="Méně než 1.5",
        ),
    ]
    updates = process_match_settlement(alerts, payload, settled_at=SETTLED_AT)
    by_id = {item["alert_id"]: item for item in updates}

    assert by_id[1]["selection_result"] == RESULT_WIN
    assert by_id[1]["result_source"] == SOURCE_TIPSPORT_RESULTS
    assert by_id[1]["odds_at_off"] == 2.14

    assert by_id[2]["selection_result"] == RESULT_UNKNOWN
    assert by_id[2]["result_source"] == SOURCE_ASIAN_QUARTER
    assert by_id[2]["odds_at_off"] == 1.0

    assert by_id[3]["selection_result"] == "V"
    assert by_id[4]["selection_result"] == "V"


def test_resolve_alert_draft_keeps_one_point_zero_odds() -> None:
    alert = _pending()
    cell = ResultCell(
        opp_id=alert.opp_id,
        odd=1.0,
        winning=False,
        observed_at=SETTLED_AT,
    )
    draft = resolve_alert_draft(alert, cell, settled_at=SETTLED_AT)
    assert draft is not None
    assert draft.selection_result == "L"
