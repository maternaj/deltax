"""Main monitor loop — fetch, detect drops, alert, persist."""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Json

from deltax.config import AppConfig, load_config, load_env
from deltax.db import (
    DatabaseError,
    SQL_INSERT_ALERT,
    SQL_UPDATE_TELEGRAM,
    connect,
    epoch_to_timestamptz,
    kickoff_from_date_start,
    validate_connection,
)
from deltax.drop_detector import MonitorStore, SelectionState, mark_market_alerted, pick_market_alerts, purge_stale_selections, update_selection_state
from deltax.messages import format_drop_alert_message, format_match_url
from deltax.parser import SelectionRow, parse_selections
from deltax.telegram import TelegramSender, parse_telegram_groups, resolve_alert_groups, telegram_enabled
from deltax.tipsport_client import TipsportClient

logger = logging.getLogger(__name__)


@dataclass
class MonitorRuntime:
    store: MonitorStore = field(default_factory=MonitorStore)
    running: bool = True


def setup_logging(level: str | None = None) -> None:
    log_level = (level or os.getenv("DELTAX_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


def max_tier_window(config: AppConfig) -> int:
    windows = [tier.window_seconds for tier in config.drop_tiers if tier.window_seconds > 0]
    return max(windows) if windows else 0


class DeltaXMonitor:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: TipsportClient | None = None,
        env: dict[str, str] | None = None,
        telegram: TelegramSender | None = None,
    ):
        self.config = config
        self.env = env or dict(os.environ)
        self.client = client or TipsportClient(config.tipsport_base_url)
        self.runtime = MonitorRuntime()
        self.telegram = telegram or TelegramSender()
        self._telegram_enabled = telegram_enabled(self.env)
        self.group_map = parse_telegram_groups(self.env.get("DELTAX_TELEGRAM_GROUPS") or "") if self._telegram_enabled else {}
        self.alert_groups = (
            resolve_alert_groups(config.default_alert_groups, self.group_map)
            if self._telegram_enabled
            else []
        )
        self._max_window = max(max_tier_window(config), config.refresh_seconds)

    def stop(self) -> None:
        self.runtime.running = False
        self.telegram.close()

    def validate_startup(self) -> None:
        validate_connection(self.env)
        logger.info("Database connectivity OK")
        if self._telegram_enabled:
            if not self.alert_groups:
                raise ValueError(
                    "DELTAX_TELEGRAM_GROUPS is set but DELTAX_ALERT_GROUPS did not resolve to any group"
                )
            logger.info("Telegram enabled for groups: %s", ",".join(g for g, _ in self.alert_groups))
        else:
            logger.info("Telegram disabled — alerts will be persisted to DB only")

    def ingest_rows(self, rows: list[SelectionRow], *, now_ts: float) -> int:
        store = self.runtime.store
        registry = self.config.market_registry
        seen: set[int] = set()
        changed = 0
        for row in rows:
            registry.register_seen(row.my_selection_id)
            if not registry.should_process(row.my_selection_id):
                continue
            seen.add(row.opp_id)
            state = store.selections.get(row.opp_id)
            if state is None:
                state = SelectionState(row=row)
                store.selections[row.opp_id] = state
            if update_selection_state(
                store,
                state,
                row,
                now_ts=now_ts,
                max_window_seconds=self._max_window,
            ):
                changed += 1

        purged = purge_stale_selections(
            store,
            now_ts=now_ts,
            ttl_seconds=self.config.selection_ttl_seconds,
        )
        if purged:
            logger.debug("Purged %d stale selections from memory", purged)
        return changed

    def process_alerts(self, *, now_ts: float) -> int:
        hits = pick_market_alerts(
            self.runtime.store,
            now_ts=now_ts,
            tiers=self.config.drop_tiers,
            max_odds=self.config.max_odds,
        )
        if not hits:
            return 0

        sent = 0
        for hit in hits:
            message = format_drop_alert_message(hit, match_url_base=self.config.match_url_base)
            match_url = format_match_url(self.config.match_url_base, hit.row.match_url)

            alert_id = self._persist_alert(hit, message, match_url)
            if alert_id is None:
                logger.error(
                    "Skipping market disarm for opp_id=%s — alert was not persisted",
                    hit.opp_id,
                )
                continue

            telegram_ok = False
            groups_sent = ""
            if self._telegram_enabled and self.alert_groups:
                telegram_ok, groups_sent = self.telegram.broadcast(
                    message,
                    alert_groups=self.alert_groups,
                )
                if not telegram_ok:
                    logger.warning(
                        "Telegram delivery failed for opp_id=%s (alert_id=%s persisted)",
                        hit.opp_id,
                        alert_id,
                    )
                self._update_telegram_status(alert_id, telegram_ok, groups_sent)

            mark_market_alerted(self.runtime.store, hit)
            sent += 1
            logger.info(
                "Alert opp_id=%s match=%s selection_id=%s drop=%.1f%% telegram_ok=%s",
                hit.opp_id,
                hit.match_id,
                hit.my_selection_id,
                hit.drop_pct,
                telegram_ok,
            )
        return sent

    def _persist_alert(
        self,
        hit,
        message: str,
        match_url: str,
    ) -> int | None:
        row = hit.row
        params = {
            "opp_id": hit.opp_id,
            "event_id": row.event_id,
            "match_id": hit.match_id,
            "my_selection_id": hit.my_selection_id,
            "match_name": row.match_name,
            "home_participant": row.home_participant,
            "visiting_participant": row.visiting_participant,
            "competition_name": row.competition_name,
            "sport_name": row.sport_name,
            "super_sport_name": row.super_sport_name,
            "match_type": row.match_type,
            "kickoff_at": kickoff_from_date_start(row.date_start),
            "match_url": match_url or row.match_url,
            "event_name": row.event_name,
            "opp_name": row.opp_name,
            "opp_type": row.opp_type,
            "opp_number": row.opp_number,
            "betting_enabled_at_alert": row.betting_enabled,
            "odds_previous": hit.odds_previous,
            "odds_now": hit.odds_now,
            "drop_pct": hit.drop_pct,
            "implied_drop_pct": hit.implied_drop_pct,
            "tier_window_seconds": hit.tier.window_seconds,
            "tier_drop_pct": hit.tier.drop_pct,
            "tier_implied_drop_pct": hit.tier.implied_drop_pct,
            "baseline_observed_at": epoch_to_timestamptz(hit.baseline_observed_at),
            "current_observed_at": epoch_to_timestamptz(hit.current_observed_at),
            "tipsport_snapshot": Json(row.tipsport_snapshot),
            "message": message,
            "telegram_ok": False,
            "telegram_groups": "",
        }
        try:
            with connect(self.env) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_INSERT_ALERT, params)
                    row = cur.fetchone()
                conn.commit()
            return int(row[0]) if row else None
        except psycopg.Error:
            logger.exception("Failed to persist alert opp_id=%s", hit.opp_id)
            return None

    def _update_telegram_status(self, alert_id: int, telegram_ok: bool, groups_sent: str) -> None:
        if not self._telegram_enabled:
            return
        params = {
            "alert_id": alert_id,
            "telegram_ok": telegram_ok,
            "telegram_groups": groups_sent,
        }
        try:
            with connect(self.env) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_UPDATE_TELEGRAM, params)
                conn.commit()
        except psycopg.Error:
            logger.exception("Failed to update telegram status for alert_id=%s", alert_id)

    def run_cycle(self) -> dict[str, int | bool]:
        rows: list[SelectionRow] = []
        failed_endpoints = 0
        for endpoint in self.config.tipsport_endpoints:
            payload = self.client.fetch(endpoint)
            if payload is None:
                failed_endpoints += 1
                logger.error("Tipsport fetch failed for endpoint=%s", endpoint)
                continue
            rows.extend(parse_selections(payload))

        if failed_endpoints == len(self.config.tipsport_endpoints):
            return {"ok": False, "selections": 0, "alerts": 0}

        now_ts = time.time()
        changed = self.ingest_rows(rows, now_ts=now_ts)
        alerts = self.process_alerts(now_ts=now_ts)
        return {
            "ok": True,
            "selections": len(rows),
            "tracked": len(self.runtime.store.selections),
            "changed": changed,
            "alerts": alerts,
            "endpoints_ok": len(self.config.tipsport_endpoints) - failed_endpoints,
            "endpoints_failed": failed_endpoints,
        }

    def run_forever(self) -> None:
        logger.info(
            "DeltaX monitor started endpoints=%s refresh=%ss max_odds=%s tiers=%s ttl=%ss "
            "markets wanted=%d pending=%d blacklisted=%d blacklisted_prefixes=%d",
            list(self.config.tipsport_endpoints),
            self.config.refresh_seconds,
            self.config.max_odds,
            [(t.window_seconds, t.drop_pct) for t in self.config.drop_tiers],
            self.config.selection_ttl_seconds,
            len(self.config.market_registry.wanted),
            len(self.config.market_registry.pending),
            len(self.config.market_registry.blacklisted),
            len(self.config.market_registry.blacklisted_prefixes),
        )
        while self.runtime.running:
            started = time.monotonic()
            stats = self.run_cycle()
            if stats.get("ok"):
                logger.info(
                    "Cycle OK selections=%s tracked=%s changed=%s alerts=%s endpoints_ok=%s endpoints_failed=%s",
                    stats.get("selections"),
                    stats.get("tracked"),
                    stats.get("changed"),
                    stats.get("alerts"),
                    stats.get("endpoints_ok"),
                    stats.get("endpoints_failed"),
                )
            else:
                logger.error("Cycle failed — Tipsport fetch returned no data")

            elapsed = time.monotonic() - started
            sleep_for = max(self.config.refresh_seconds - elapsed, 1.0)
            deadline = time.monotonic() + sleep_for
            while self.runtime.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1.0, remaining))


def main() -> None:
    load_env()
    setup_logging()
    config = load_config()
    monitor = DeltaXMonitor(config)
    try:
        monitor.validate_startup()
    except (DatabaseError, psycopg.Error, ValueError) as exc:
        logger.error("Startup validation failed: %s", exc)
        raise SystemExit(1) from exc

    def _handle_signal(_signum, _frame) -> None:
        logger.info("Shutdown signal received")
        monitor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        monitor.run_forever()
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
