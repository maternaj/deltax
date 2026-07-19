"""Main monitor loop — fetch, detect drops, alert, persist."""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field

import psycopg

from deltax.config import AppConfig, load_config, load_env
from deltax.db import SQL_INSERT_ALERT, connect
from deltax.drop_detector import MonitorStore, SelectionState, mark_market_alerted, pick_market_alerts, update_selection_state
from deltax.messages import format_drop_alert_message, format_match_url
from deltax.parser import SelectionRow, parse_selections
from deltax.telegram import broadcast_alert, parse_telegram_groups, resolve_alert_groups, telegram_configured
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
    return max(tier.window_seconds for tier in config.drop_tiers)


class DeltaXMonitor:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: TipsportClient | None = None,
        env: dict[str, str] | None = None,
    ):
        self.config = config
        self.env = env or dict(os.environ)
        self.client = client or TipsportClient(config.tipsport_base_url)
        self.runtime = MonitorRuntime()
        self.group_map = parse_telegram_groups(self.env.get("DELTAX_TELEGRAM_GROUPS") or "")
        self.alert_groups = resolve_alert_groups(config.default_alert_groups, self.group_map)
        self._max_window = max_tier_window(config)

    def stop(self) -> None:
        self.runtime.running = False

    def ingest_rows(self, rows: list[SelectionRow], *, now_ts: float) -> None:
        store = self.runtime.store
        seen: set[int] = set()
        for row in rows:
            seen.add(row.opp_id)
            state = store.selections.get(row.opp_id)
            if state is None:
                state = SelectionState(row=row)
                store.selections[row.opp_id] = state
            update_selection_state(store, state, row, now_ts=now_ts, max_window_seconds=self._max_window)

        stale = [opp_id for opp_id in store.selections if opp_id not in seen]
        for opp_id in stale:
            del store.selections[opp_id]

    def process_alerts(self, *, now_ts: float) -> int:
        hits = pick_market_alerts(
            self.runtime.store,
            now_ts=now_ts,
            tiers=self.config.drop_tiers,
        )
        if not hits:
            return 0

        sent = 0
        for hit in hits:
            message = format_drop_alert_message(hit, match_url_base=self.config.match_url_base)
            match_url = format_match_url(self.config.match_url_base, hit.row.match_url)

            telegram_ok = False
            groups_sent = ""
            if telegram_configured(self.env) and self.alert_groups:
                telegram_ok, groups_sent = broadcast_alert(message, alert_groups=self.alert_groups)
            elif not telegram_configured(self.env):
                logger.warning("Telegram not configured — alert logged to DB only")

            self._persist_alert(hit, message, match_url, telegram_ok, groups_sent)
            mark_market_alerted(self.runtime.store, hit)
            sent += 1
            logger.info(
                "Alert opp_id=%s match=%s market=%s drop=%.1f%% telegram_ok=%s",
                hit.opp_id,
                hit.match_id,
                hit.market_type,
                hit.drop_pct,
                telegram_ok,
            )
        return sent

    def _persist_alert(
        self,
        hit,
        message: str,
        match_url: str,
        telegram_ok: bool,
        groups_sent: str,
    ) -> None:
        row = hit.row
        params = {
            "opp_id": hit.opp_id,
            "match_id": hit.match_id,
            "market_type": hit.market_type,
            "match_name": row.match_name,
            "competition_name": row.competition_name,
            "event_name": row.event_name,
            "opp_name": row.opp_name,
            "baseline_odds": hit.baseline_odds,
            "current_odds": hit.current_odds,
            "drop_pct": hit.drop_pct,
            "tier_window_seconds": hit.tier.window_seconds,
            "tier_drop_pct": hit.tier.drop_pct,
            "match_url": match_url or row.match_url,
            "message": message,
            "telegram_ok": telegram_ok,
            "telegram_groups": groups_sent,
        }
        try:
            with connect(self.env) as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_INSERT_ALERT, params)
                conn.commit()
        except psycopg.Error:
            logger.exception("Failed to persist alert opp_id=%s", hit.opp_id)

    def run_cycle(self) -> dict[str, int | bool]:
        payload = self.client.fetch(self.config.tipsport_endpoint)
        if payload is None:
            return {"ok": False, "selections": 0, "alerts": 0}

        rows = parse_selections(payload)
        now_ts = time.time()
        self.ingest_rows(rows, now_ts=now_ts)
        alerts = self.process_alerts(now_ts=now_ts)
        return {
            "ok": True,
            "selections": len(rows),
            "tracked": len(self.runtime.store.selections),
            "alerts": alerts,
        }

    def run_forever(self) -> None:
        logger.info(
            "DeltaX monitor started endpoint=%s refresh=%ss tiers=%s",
            self.config.tipsport_endpoint,
            self.config.refresh_seconds,
            [(t.window_seconds, t.drop_pct) for t in self.config.drop_tiers],
        )
        while self.runtime.running:
            started = time.monotonic()
            stats = self.run_cycle()
            if stats.get("ok"):
                logger.info(
                    "Cycle OK selections=%s tracked=%s alerts=%s",
                    stats.get("selections"),
                    stats.get("tracked"),
                    stats.get("alerts"),
                )
            else:
                logger.error("Cycle failed — Tipsport fetch returned no data")

            elapsed = time.monotonic() - started
            sleep_for = max(self.config.refresh_seconds - elapsed, 1.0)
            deadline = time.monotonic() + sleep_for
            while self.runtime.running and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))


def main() -> None:
    load_env()
    setup_logging()
    config = load_config()
    monitor = DeltaXMonitor(config)

    def _handle_signal(_signum, _frame) -> None:
        logger.info("Shutdown signal received")
        monitor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    monitor.run_forever()


if __name__ == "__main__":
    main()
