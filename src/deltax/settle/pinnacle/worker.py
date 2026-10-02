"""Pinnacle corner settlement worker — Flashscore fs_* tables only (no web/API)."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any

import psycopg

from deltax.config import AppConfig, load_config, load_env
from deltax.db import DatabaseError, connect
from deltax.settle.constants import SOURCE_FLASHSCORE_STATS
from deltax.settle.db import (
    PinnacleCornerPendingAlert,
    PinnaclePendingAlert,
    apply_settlement_updates,
    fetch_pending_pinnacle_corner_alerts,
    validate_settler_connection,
    _settler_env,
)
from deltax.settle.pinnacle.corners import grade_corner_alert
from deltax.settle.matching.aliases import load_merged_team_aliases
from deltax.settle.matching.config import load_fs_matching_config
from deltax.settle.matching.pinnacle_names import load_pinnacle_team_names
from deltax.settle.pinnacle.fs_match import (
    LinkedFsMatch,
    build_alert_match_key,
    link_alert_to_fs_match,
    load_finished_fs_matches,
)
from deltax.settle.worker import select_ready_alerts, setup_logging

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def settle_alert_from_fs(
    alert: PinnaclePendingAlert,
    *,
    settled_at: datetime,
) -> dict[str, Any] | None:
    result = grade_corner_alert(
        my_selection_id=alert.my_selection_id,
        opp_name=alert.opp_name,
        opp_number=alert.opp_number,
        counts=alert.fs_match.corners,
    )
    if result is None:
        return None
    return {
        "alert_id": alert.alert_id,
        "odds_at_off": None,
        "odds_at_off_observed_at": None,
        "selection_result": result,
        "result_settled_at": settled_at,
        "result_source": SOURCE_FLASHSCORE_STATS,
    }


def _ready_alerts_sorted(
    pending: list[PinnacleCornerPendingAlert],
    *,
    settle,
    now: datetime,
    batch_limit: int,
) -> list[PinnacleCornerPendingAlert]:
    ready = [
        alert
        for alerts in select_ready_alerts(pending, settle=settle, now=now).values()
        for alert in alerts
    ]
    ready.sort(key=lambda item: (item.kickoff_at, item.alert_id))
    return ready[:batch_limit]


class DeltaXPinnacleSettle:
    def __init__(self, config: AppConfig, *, env: dict[str, str] | None = None):
        self.config = config
        self.env = env or dict(os.environ)
        self.running = True
        self.fs_matching = load_fs_matching_config()

    def stop(self) -> None:
        self.running = False

    def validate_startup(self) -> None:
        validate_settler_connection(self.env)
        with connect(_settler_env(self.env)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT match_id FROM fs_soccer_all LIMIT 0")
        logger.info("Pinnacle settler database connectivity OK (deltax_alerts + fs_soccer_all)")

    def run_once(self) -> dict[str, int]:
        settle = self.config.settle
        now = _utcnow()
        stats = {
            "pending": 0,
            "ready": 0,
            "linked": 0,
            "updated": 0,
            "skipped_no_fs_match": 0,
            "skipped_ungraded": 0,
        }

        with connect(_settler_env(self.env)) as conn:
            pending = fetch_pending_pinnacle_corner_alerts(conn)
        stats["pending"] = len(pending)
        if not pending:
            return stats

        ready = _ready_alerts_sorted(
            pending,
            settle=settle,
            now=now,
            batch_limit=settle.batch_match_limit,
        )
        stats["ready"] = len(ready)
        if not ready:
            return stats

        min_ko = min(alert.kickoff_at for alert in ready)
        max_ko = max(alert.kickoff_at for alert in ready)

        with connect(_settler_env(self.env)) as conn:
            fs_rows = load_finished_fs_matches(
                conn,
                min_kickoff=min_ko,
                max_kickoff=max_ko,
                matching=self.fs_matching,
            )
            aliases = load_merged_team_aliases(
                conn,
                yaml_aliases=self.fs_matching.team_aliases,
            )
            pinnacle_names = load_pinnacle_team_names(
                conn,
                [alert.match_id for alert in ready],
            )

        updates: list[dict[str, Any]] = []
        for alert in ready:
            morex_names = pinnacle_names.get(str(alert.match_id))
            key = build_alert_match_key(
                home_participant=alert.home_participant,
                visiting_participant=alert.visiting_participant,
                kickoff_at=alert.kickoff_at,
                home_name=morex_names[0] if morex_names else None,
                away_name=morex_names[1] if morex_names else None,
            )
            fs_match: LinkedFsMatch | None = link_alert_to_fs_match(
                key,
                fs_rows,
                matching=self.fs_matching,
                aliases=aliases,
            )
            if fs_match is None:
                stats["skipped_no_fs_match"] += 1
                logger.debug(
                    "No FS match for alert_id=%s home=%r away=%r kickoff=%s",
                    alert.alert_id,
                    alert.home_participant,
                    alert.visiting_participant,
                    alert.kickoff_at.isoformat(),
                )
                continue
            stats["linked"] += 1
            linked = PinnaclePendingAlert(
                alert_id=alert.alert_id,
                opp_id=alert.opp_id,
                event_id=alert.event_id,
                match_id=alert.match_id,
                my_selection_id=alert.my_selection_id,
                opp_name=alert.opp_name,
                opp_number=alert.opp_number,
                kickoff_at=alert.kickoff_at,
                home_participant=alert.home_participant,
                visiting_participant=alert.visiting_participant,
                match_name=alert.match_name,
                fs_match=fs_match,
            )
            update = settle_alert_from_fs(linked, settled_at=now)
            if update is None:
                stats["skipped_ungraded"] += 1
                continue
            updates.append(update)

        if updates:
            with connect(_settler_env(self.env)) as conn:
                updated = apply_settlement_updates(conn, updates)
                conn.commit()
            stats["updated"] = updated
            logger.info(
                "Settled %d Pinnacle corner alerts (linked=%d ready=%d pending=%d)",
                updated,
                stats["linked"],
                stats["ready"],
                stats["pending"],
            )

        return stats

    def run_forever(self) -> None:
        settle = self.config.settle
        logger.info(
            "DeltaX Pinnacle settler started sleep=%ss default_delay=%sh batch=%d (no max_age — fs_* backfill)",
            settle.sleep_seconds,
            settle.default_delay_hours,
            settle.batch_match_limit,
        )
        while self.running:
            started = time.monotonic()
            try:
                stats = self.run_once()
                logger.info(
                    "Pinnacle settle cycle pending=%d ready=%d linked=%d updated=%d skipped_no_fs=%d skipped_ungraded=%d",
                    stats["pending"],
                    stats["ready"],
                    stats["linked"],
                    stats["updated"],
                    stats["skipped_no_fs_match"],
                    stats["skipped_ungraded"],
                )
            except Exception:
                logger.exception("Pinnacle settle cycle failed")

            elapsed = time.monotonic() - started
            sleep_for = max(settle.sleep_seconds - elapsed, 1.0)
            deadline = time.monotonic() + sleep_for
            while self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(description="DeltaX Pinnacle corner settlement worker (fs_* tables)")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()

    load_env()
    setup_logging()
    config = load_config()
    if config.source != "pinnacle":
        logger.warning("Config source=%s — expected pinnacle; continuing anyway", config.source)
    settler = DeltaXPinnacleSettle(config)
    try:
        settler.validate_startup()
    except (DatabaseError, psycopg.Error) as exc:
        logger.error("Startup validation failed: %s", exc)
        raise SystemExit(1) from exc

    if args.once:
        try:
            settler.run_once()
        except Exception as exc:
            logger.error("Pinnacle settle run failed: %s", exc)
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
