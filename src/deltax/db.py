"""Postgres connectivity for deltax_writer."""

from __future__ import annotations

import os
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


def validate_connection(env: dict[str, str] | None = None, *, timeout_s: float = 10.0) -> None:
    """Fail fast when database is unreachable or misconfigured."""
    with connect(env, timeout_s=timeout_s) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


SQL_INSERT_ALERT = """
INSERT INTO deltax_alerts (
    opp_id, match_id, market_type,
    match_name, competition_name, event_name, opp_name,
    baseline_odds, current_odds, drop_pct,
    tier_window_seconds, tier_drop_pct,
    match_url, message, telegram_ok, telegram_groups
) VALUES (
    %(opp_id)s, %(match_id)s, %(market_type)s,
    %(match_name)s, %(competition_name)s, %(event_name)s, %(opp_name)s,
    %(baseline_odds)s, %(current_odds)s, %(drop_pct)s,
    %(tier_window_seconds)s, %(tier_drop_pct)s,
    %(match_url)s, %(message)s, %(telegram_ok)s, %(telegram_groups)s
)
RETURNING alert_id
"""

SQL_UPDATE_TELEGRAM = """
UPDATE deltax_alerts
SET telegram_ok = %(telegram_ok)s,
    telegram_groups = %(telegram_groups)s
WHERE alert_id = %(alert_id)s
"""
