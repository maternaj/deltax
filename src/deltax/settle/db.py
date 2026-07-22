"""Database access for deltax_settle worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from urllib.parse import quote_plus

import psycopg

from deltax.db import DatabaseError, connect

SQL_EXPIRE_OLD_ALERTS = """
UPDATE deltax_alerts
SET result_flag = true,
    selection_result = %(selection_result)s,
    result_settled_at = %(settled_at)s,
    result_source = %(result_source)s
WHERE result_flag = false
  AND kickoff_at IS NOT NULL
  AND kickoff_at < %(cutoff)s
RETURNING alert_id
"""

SQL_SELECT_PENDING_ALERTS = """
SELECT
    alert_id,
    opp_id,
    event_id,
    match_id,
    my_selection_id,
    opp_name,
    kickoff_at
FROM deltax_alerts
WHERE result_flag = false
  AND kickoff_at IS NOT NULL
  AND kickoff_at >= %(min_kickoff)s
ORDER BY kickoff_at ASC, alert_id ASC
"""

SQL_UPDATE_SETTLEMENT = """
UPDATE deltax_alerts
SET odds_at_off = %(odds_at_off)s,
    odds_at_off_observed_at = %(odds_at_off_observed_at)s,
    selection_result = %(selection_result)s,
    result_flag = true,
    result_settled_at = %(result_settled_at)s,
    result_source = %(result_source)s
WHERE alert_id = %(alert_id)s
  AND result_flag = false
  AND (selection_result IS NULL OR selection_result <> 'W')
"""


@dataclass(frozen=True)
class PendingAlert:
    alert_id: int
    opp_id: int
    event_id: int
    match_id: int
    my_selection_id: str
    opp_name: str
    kickoff_at: datetime


def validate_settler_connection(env: dict[str, str]) -> None:
    with connect(_settler_env(env)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT alert_id FROM deltax_alerts LIMIT 0")


def _settler_env(env: dict[str, str]) -> dict[str, str]:
    settle_url = (env.get("DELTAX_SETTLE_DATABASE_URL") or "").strip()
    if settle_url:
        merged = dict(env)
        merged["DELTAX_DATABASE_URL"] = settle_url
        return merged

    host = (env.get("DELTAX_SETTLE_DB_HOST") or "").strip()
    user = (env.get("DELTAX_SETTLE_DB_USER") or "").strip()
    if not host and not user:
        return env

    port = (env.get("DELTAX_SETTLE_DB_PORT") or "5432").strip()
    name = (env.get("DELTAX_SETTLE_DB_NAME") or "alex").strip()
    password = env.get("DELTAX_SETTLE_DB_PASSWORD") or ""
    sslmode = (env.get("DELTAX_SETTLE_DB_SSLMODE") or "prefer").strip()

    if not host or not user:
        raise DatabaseError(
            "Set DELTAX_SETTLE_DATABASE_URL or DELTAX_SETTLE_DB_HOST/DELTAX_SETTLE_DB_USER in .env"
        )
    if host.upper() == "HOST" or password.upper() == "PASSWORD":
        raise DatabaseError("Settler database settings still contain placeholder HOST/PASSWORD")

    safe_password = quote_plus(password)
    conninfo = f"postgresql://{user}:{safe_password}@{host}:{port}/{name}?sslmode={sslmode}"
    merged = dict(env)
    merged["DELTAX_DATABASE_URL"] = conninfo
    return merged


def expire_old_alerts(
    conn: psycopg.Connection,
    *,
    cutoff: datetime,
    settled_at: datetime,
    selection_result: str,
    result_source: str,
) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            SQL_EXPIRE_OLD_ALERTS,
            {
                "cutoff": cutoff,
                "settled_at": settled_at,
                "selection_result": selection_result,
                "result_source": result_source,
            },
        )
        rows = cur.fetchall()
    return [int(row[0]) for row in rows]


def fetch_pending_alerts(conn: psycopg.Connection, *, min_kickoff: datetime) -> list[PendingAlert]:
    with conn.cursor() as cur:
        cur.execute(SQL_SELECT_PENDING_ALERTS, {"min_kickoff": min_kickoff})
        rows = cur.fetchall()
    alerts: list[PendingAlert] = []
    for row in rows:
        kickoff_at = row[6]
        if kickoff_at.tzinfo is None:
            kickoff_at = kickoff_at.replace(tzinfo=timezone.utc)
        alerts.append(
            PendingAlert(
                alert_id=int(row[0]),
                opp_id=int(row[1]),
                event_id=int(row[2]),
                match_id=int(row[3]),
                my_selection_id=str(row[4]),
                opp_name=str(row[5] or ""),
                kickoff_at=kickoff_at,
            )
        )
    return alerts


def apply_settlement_updates(conn: psycopg.Connection, updates: list[dict[str, Any]]) -> int:
    updated = 0
    with conn.cursor() as cur:
        for params in updates:
            cur.execute(SQL_UPDATE_SETTLEMENT, params)
            updated += cur.rowcount
    return updated
