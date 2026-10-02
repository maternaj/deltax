"""Team alias loading — YAML bootstrap + approved morex_team_alias_candidates rows."""

from __future__ import annotations

import logging
from typing import Mapping

import psycopg

logger = logging.getLogger(__name__)

_ALIAS_TABLE = "morex_team_alias_candidates"


def _is_missing_relation_error(exc: BaseException, *, relation: str) -> bool:
    if not isinstance(exc, psycopg.Error):
        return False
    message = str(exc).lower()
    return relation.lower() in message and (
        "does not exist" in message or "permission denied" in message
    )


def load_approved_aliases(conn: psycopg.Connection) -> dict[str, str]:
    sql = """
    SELECT source_key, target_key
    FROM morex_team_alias_candidates
    WHERE status = 'approved'
    """
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for source_key, target_key in cur.fetchall():
            out[str(source_key)] = str(target_key)
    return out


def merge_team_aliases(
    *,
    yaml_aliases: Mapping[str, str],
    conn: psycopg.Connection | None = None,
) -> dict[str, str]:
    """YAML bootstrap + DB-approved aliases (DB wins on key collision)."""
    merged = dict(yaml_aliases)
    if conn is None:
        return merged
    try:
        merged.update(load_approved_aliases(conn))
    except Exception as exc:
        if _is_missing_relation_error(exc, relation=_ALIAS_TABLE):
            logger.info(
                "Approved alias DB load skipped (%s unavailable to settler)",
                _ALIAS_TABLE,
            )
        else:
            raise
    return merged


def load_merged_team_aliases(
    conn: psycopg.Connection | None,
    *,
    yaml_aliases: Mapping[str, str],
) -> dict[str, str]:
    """Return merged aliases; YAML-only when conn is None."""
    return merge_team_aliases(yaml_aliases=yaml_aliases, conn=conn)
