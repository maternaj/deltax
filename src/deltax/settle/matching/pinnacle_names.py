"""Resolve canonical Pinnacle team names via morex_prematch_relative_odds."""

from __future__ import annotations

import logging

import psycopg

logger = logging.getLogger(__name__)

_PREMATCH_TABLE = "morex_prematch_relative_odds"


def _is_missing_relation_error(exc: BaseException, *, relation: str) -> bool:
    if not isinstance(exc, psycopg.Error):
        return False
    message = str(exc).lower()
    return relation.lower() in message and (
        "does not exist" in message or "permission denied" in message
    )


def load_pinnacle_team_names(
    conn: psycopg.Connection,
    match_ids: list[int],
) -> dict[str, tuple[str, str]]:
    """Return book_event_id -> (home_team, away_team) from latest MoreX pinn scan."""
    if not match_ids:
        return {}
    ids = [str(match_id) for match_id in match_ids]
    sql = """
    SELECT DISTINCT ON (book_event_id)
        book_event_id,
        home_team,
        away_team
    FROM morex_prematch_relative_odds
    WHERE book = 'pinn'
      AND book_event_id = ANY(%(ids)s)
      AND home_team IS NOT NULL
      AND away_team IS NOT NULL
    ORDER BY book_event_id, extracted_at DESC
    """
    out: dict[str, tuple[str, str]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"ids": ids})
            for book_event_id, home_team, away_team in cur.fetchall():
                home = str(home_team or "").strip()
                away = str(away_team or "").strip()
                if home and away:
                    out[str(book_event_id)] = (home, away)
    except Exception as exc:
        if _is_missing_relation_error(exc, relation=_PREMATCH_TABLE):
            logger.info(
                "Pinnacle name lookup skipped (%s unavailable to settler)",
                _PREMATCH_TABLE,
            )
            return {}
        raise
    return out
