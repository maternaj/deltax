"""Settlement worker — results API, odds_at_off, void rules."""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from deltax.config import AppConfig, SettleConfig, load_config, load_env
from deltax.db import DatabaseError, connect
from deltax.settle.asian_lines import is_quarter_line_alert
from deltax.settle.constants import (
    RESULT_EXPIRED,
    RESULT_LOSS,
    RESULT_UNKNOWN,
    RESULT_WIN,
    SOURCE_ASIAN_QUARTER,
    SOURCE_EXPIRED_WINDOW,
    SOURCE_TIPSPORT_RESULTS,
)
from deltax.settle.db import (
    PendingAlert,
    apply_settlement_updates,
    expire_old_alerts,
    fetch_pending_alerts,
    validate_settler_connection,
    _settler_env,
)
from deltax.settle.results_api import ResultCell, match_has_results, parse_result_cells
from deltax.settle.void_rules import SettlementDraft, apply_void_rules
from deltax.tipsport_client import TipsportClient, default_settle_state_file

logger = logging.getLogger(__name__)


def setup_logging(level: str | None = None) -> None:
    log_level = (level or os.getenv("DELTAX_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def select_ready_alerts(
    alerts: list[PendingAlert],
    *,
    settle: SettleConfig,
    now: datetime,
) -> dict[int, list[PendingAlert]]:
    ready: dict[int, list[PendingAlert]] = defaultdict(list)
    for alert in alerts:
        delay = timedelta(hours=settle.delay_hours_for(alert.my_selection_id))
        if alert.kickoff_at + delay <= now:
            ready[alert.match_id].append(alert)
    return ready


def resolve_alert_draft(
    alert: PendingAlert,
    cell: ResultCell | None,
    *,
    settled_at: datetime,
) -> SettlementDraft | None:
    if is_quarter_line_alert(
        my_selection_id=alert.my_selection_id,
        opp_name=alert.opp_name,
    ):
        return SettlementDraft(
            alert_id=alert.alert_id,
            opp_id=alert.opp_id,
            event_id=alert.event_id,
            match_id=alert.match_id,
            my_selection_id=alert.my_selection_id,
            opp_name=alert.opp_name,
            selection_result=RESULT_UNKNOWN,
            result_source=SOURCE_ASIAN_QUARTER,
        )

    if cell is None or cell.winning is None:
        return None

    selection_result = RESULT_WIN if cell.winning else RESULT_LOSS
    return SettlementDraft(
        alert_id=alert.alert_id,
        opp_id=alert.opp_id,
        event_id=alert.event_id,
        match_id=alert.match_id,
        my_selection_id=alert.my_selection_id,
        opp_name=alert.opp_name,
        selection_result=selection_result,
        result_source=SOURCE_TIPSPORT_RESULTS,
    )


def draft_to_update(
    draft: SettlementDraft,
    cell: ResultCell | None,
    *,
    settled_at: datetime,
) -> dict[str, Any]:
    observed_at = cell.observed_at if cell and cell.observed_at else settled_at
    odds_at_off = cell.odd if cell and cell.odd is not None else None
    return {
        "alert_id": draft.alert_id,
        "odds_at_off": odds_at_off,
        "odds_at_off_observed_at": observed_at if odds_at_off is not None else None,
        "selection_result": draft.selection_result,
        "result_settled_at": settled_at,
        "result_source": draft.result_source,
    }


def process_match_settlement(
    alerts: list[PendingAlert],
    match_data: dict[str, Any],
    *,
    settled_at: datetime | None = None,
) -> list[dict[str, Any]]:
    settled_at = settled_at or _utcnow()
    if not match_has_results(match_data):
        return []

    cells = parse_result_cells(match_data)
    drafts: list[SettlementDraft] = []
    cells_by_alert: dict[int, ResultCell | None] = {}
    for alert in alerts:
        cell = cells.get(alert.opp_id)
        draft = resolve_alert_draft(alert, cell, settled_at=settled_at)
        if draft is None:
            continue
        drafts.append(draft)
        cells_by_alert[alert.alert_id] = cell

    apply_void_rules(drafts)
    return [
        draft_to_update(draft, cells_by_alert[draft.alert_id], settled_at=settled_at)
        for draft in drafts
        if draft.selection_result is not None
    ]


class DeltaXSettle:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: TipsportClient | None = None,
        env: dict[str, str] | None = None,
    ):
        self.config = config
        self.env = env or dict(os.environ)
        self.client = client or TipsportClient(
            config.tipsport_base_url,
            state_file=default_settle_state_file(),
        )
        self.running = True

    def stop(self) -> None:
        self.running = False
        self.client.close()

    def validate_startup(self) -> None:
        validate_settler_connection(self.env)
        logger.info("Settler database connectivity OK")

    def run_once(self) -> dict[str, int]:
        settle = self.config.settle
        now = _utcnow()
        min_kickoff = now - timedelta(days=settle.max_age_days)
        stats = {
            "expired": 0,
            "matches": 0,
            "updated": 0,
            "skipped_no_results": 0,
        }

        with connect(_settler_env(self.env)) as conn:
            expired_ids = expire_old_alerts(
                conn,
                cutoff=min_kickoff,
                settled_at=now,
                selection_result=RESULT_EXPIRED,
                result_source=SOURCE_EXPIRED_WINDOW,
            )
            pending = fetch_pending_alerts(conn, min_kickoff=min_kickoff)
            conn.commit()
        stats["expired"] = len(expired_ids)
        if expired_ids:
            logger.info("Expired %d alerts outside %d-day window", len(expired_ids), settle.max_age_days)

        ready_by_match = select_ready_alerts(pending, settle=settle, now=now)
        if not ready_by_match:
            return stats

        match_ids = sorted(
            ready_by_match,
            key=lambda match_id: min(alert.kickoff_at for alert in ready_by_match[match_id]),
        )[: settle.batch_match_limit]

        for match_id in match_ids:
            alerts = ready_by_match[match_id]
            payload = self.client.fetch_match_results(match_id)
            if payload is None:
                logger.warning("Results fetch failed for match_id=%s", match_id)
                continue
            if not match_has_results(payload):
                stats["skipped_no_results"] += 1
                logger.debug("Match %s has no resultParts yet (%d alerts waiting)", match_id, len(alerts))
                continue

            updates = process_match_settlement(alerts, payload, settled_at=now)
            if not updates:
                continue

            with connect(_settler_env(self.env)) as conn:
                updated = apply_settlement_updates(conn, updates)
                conn.commit()
            stats["matches"] += 1
            stats["updated"] += updated
            logger.info(
                "Settled match_id=%s alerts=%d updated=%d",
                match_id,
                len(alerts),
                updated,
            )

            if settle.match_request_delay_seconds > 0:
                delay = random.uniform(
                    settle.match_request_delay_seconds * 0.6,
                    settle.match_request_delay_seconds * 1.4,
                )
                time.sleep(delay)

        return stats

    def run_forever(self) -> None:
        settle = self.config.settle
        logger.info(
            "DeltaX settler started sleep=%ss default_delay=%sh max_age=%sd batch=%d",
            settle.sleep_seconds,
            settle.default_delay_hours,
            settle.max_age_days,
            settle.batch_match_limit,
        )
        while self.running:
            started = time.monotonic()
            try:
                stats = self.run_once()
                logger.info(
                    "Settle cycle expired=%d matches=%d updated=%d skipped_no_results=%d",
                    stats["expired"],
                    stats["matches"],
                    stats["updated"],
                    stats["skipped_no_results"],
                )
            except Exception:
                logger.exception("Settle cycle failed")

            elapsed = time.monotonic() - started
            sleep_for = max(settle.sleep_seconds - elapsed, 1.0)
            logger.debug("Settle sleeping %.0fs until next cycle", sleep_for)
            deadline = time.monotonic() + sleep_for
            while self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(description="DeltaX settlement worker")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    load_env()
    setup_logging()
    config = load_config()
    settler = DeltaXSettle(config)
    try:
        settler.validate_startup()
    except (DatabaseError, psycopg.Error) as exc:
        logger.error("Startup validation failed: %s", exc)
        raise SystemExit(1) from exc

    if args.once:
        try:
            settler.run_once()
        except Exception as exc:
            logger.error("Settle run failed: %s", exc)
            raise SystemExit(1) from exc
        return

    def _handle_signal(_signum, _frame) -> None:
        logger.info("Shutdown signal received")
        settler.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        settler.run_forever()
    finally:
        settler.stop()


if __name__ == "__main__":
    main()
