"""Postgres connectivity for deltax_writer."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import psycopg


class DatabaseError(Exception):
    """Raised when database configuration or connectivity fails."""


def _connection_kwargs(env: dict[str, str], *, timeout_s: float) -> dict[str, Any]:
    url = (env.get("DELTAX_DATABASE_URL") or "").strip()
    if url:
        if "@HOST:" in url or "://deltax_writer:PASSWORD@" in url:
            raise DatabaseError("DELTAX_DATABASE_URL still contains placeholder values")
        return {"conninfo": url, "connect_timeout": int(timeout_s)}

    host = (env.get("DELTAX_DB_HOST") or "").strip()
    port = (env.get("DELTAX_DB_PORT") or "5432").strip()
    name = (env.get("DELTAX_DB_NAME") or "alex").strip()
    user = (env.get("DELTAX_DB_USER") or "").strip()
    password = env.get("DELTAX_DB_PASSWORD") or ""
    sslmode = (env.get("DELTAX_DB_SSLMODE") or "prefer").strip()

    missing = [label for label, val in [("host", host), ("user", user)] if not val]
    if missing:
        raise DatabaseError(
            "Set DELTAX_DATABASE_URL or DELTAX_DB_HOST/DELTAX_DB_USER in .env"
        )
    if host.upper() == "HOST" or password.upper() == "PASSWORD":
        raise DatabaseError("Database settings still contain placeholder HOST/PASSWORD")

    safe_password = quote_plus(password)
    conninfo = f"postgresql://{user}:{safe_password}@{host}:{port}/{name}?sslmode={sslmode}"
    return {"conninfo": conninfo, "connect_timeout": int(timeout_s)}


def connect(env: dict[str, str] | None = None, *, timeout_s: float = 15.0) -> psycopg.Connection:
    env = env or dict(os.environ)
    return psycopg.connect(**_connection_kwargs(env, timeout_s=timeout_s))


def epoch_to_timestamptz(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def kickoff_from_date_start(date_start_ms: int | None) -> datetime | None:
    if date_start_ms is None:
        return None
    return datetime.fromtimestamp(date_start_ms / 1000.0, tz=timezone.utc)


def validate_connection(env: dict[str, str] | None = None, *, timeout_s: float = 10.0) -> None:
    """Fail fast when database is unreachable, misconfigured, or missing INSERT/RETURNING rights."""
    now = datetime.now(timezone.utc)
    with connect(env, timeout_s=timeout_s) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute(
                """
                INSERT INTO deltax_alerts (
                    opp_id, event_id, match_id, my_selection_id,
                    odds_previous, odds_now, drop_pct, implied_drop_pct,
                    tier_window_seconds, tier_drop_pct, tier_implied_drop_pct,
                    baseline_observed_at, current_observed_at,
                    tipsport_snapshot, message
                ) VALUES (
                    -1, -1, -1, 'STARTUP_CHECK',
                    2.0, 1.8, 10, 0, 0, 10, 0,
                    %(baseline_at)s, %(current_at)s,
                    '{}'::jsonb, 'startup check'
                )
                RETURNING alert_id
                """,
                {"baseline_at": now, "current_at": now},
            )
        conn.rollback()


SQL_INSERT_ALERT = """
INSERT INTO deltax_alerts (
    opp_id, event_id, match_id, my_selection_id,
    match_name, home_participant, visiting_participant,
    competition_name, sport_name, super_sport_name,
    match_type, kickoff_at, match_url,
    event_name, opp_name, opp_type, opp_number,
    betting_enabled_at_alert,
    odds_previous, odds_now, drop_pct, implied_drop_pct,
    tier_window_seconds, tier_drop_pct, tier_implied_drop_pct,
    baseline_observed_at, current_observed_at,
    tipsport_snapshot,
    message, telegram_ok, telegram_groups
) VALUES (
    %(opp_id)s, %(event_id)s, %(match_id)s, %(my_selection_id)s,
    %(match_name)s, %(home_participant)s, %(visiting_participant)s,
    %(competition_name)s, %(sport_name)s, %(super_sport_name)s,
    %(match_type)s, %(kickoff_at)s, %(match_url)s,
    %(event_name)s, %(opp_name)s, %(opp_type)s, %(opp_number)s,
    %(betting_enabled_at_alert)s,
    %(odds_previous)s, %(odds_now)s, %(drop_pct)s, %(implied_drop_pct)s,
    %(tier_window_seconds)s, %(tier_drop_pct)s, %(tier_implied_drop_pct)s,
    %(baseline_observed_at)s, %(current_observed_at)s,
    %(tipsport_snapshot)s,
    %(message)s, %(telegram_ok)s, %(telegram_groups)s
)
RETURNING alert_id
"""

SQL_UPDATE_TELEGRAM = """
UPDATE deltax_alerts
SET telegram_ok = %(telegram_ok)s,
    telegram_groups = %(telegram_groups)s
WHERE alert_id = %(alert_id)s
"""
