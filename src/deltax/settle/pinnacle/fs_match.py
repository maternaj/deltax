"""Match-link Pinnacle alerts to finished Flashscore rows (fs_soccer_all / fs_soccer_raw)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

import psycopg

from deltax.settle.matching.config import FsMatchingConfig, load_fs_matching_config
from deltax.settle.matching.scoring import pair_score
from deltax.settle.pinnacle.corners import CornerCounts, strip_relative_unit_suffix

DEFAULT_MATCHING = load_fs_matching_config()


@dataclass(frozen=True)
class FsFinishedMatch:
    match_id: str
    match_date: datetime
    home_team: str
    away_team: str
    corners: CornerCounts


@dataclass(frozen=True)
class LinkedFsMatch:
    """FS row with corner counts aligned to the alert's home/away participants."""

    match_id: str
    match_date: datetime
    corners: CornerCounts


@dataclass(frozen=True)
class AlertMatchKey:
    home_name: str
    away_name: str
    kickoff_at: datetime


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_alert_match_key(
    *,
    home_participant: str,
    visiting_participant: str,
    kickoff_at: datetime,
    home_name: str | None = None,
    away_name: str | None = None,
) -> AlertMatchKey:
    return AlertMatchKey(
        home_name=home_name or strip_relative_unit_suffix(home_participant),
        away_name=away_name or strip_relative_unit_suffix(visiting_participant),
        kickoff_at=_aware(kickoff_at),
    )


def _orient_corners(corners: CornerCounts, *, swapped: bool) -> CornerCounts:
    if swapped:
        return CornerCounts(home=corners.away, away=corners.home)
    return corners


def _row_corners(home_val: object, away_val: object) -> CornerCounts | None:
    if home_val is None or away_val is None:
        return None
    return CornerCounts(home=int(home_val), away=int(away_val))


def load_finished_fs_matches(
    conn: psycopg.Connection,
    *,
    min_kickoff: datetime,
    max_kickoff: datetime,
    matching: FsMatchingConfig = DEFAULT_MATCHING,
) -> list[FsFinishedMatch]:
    load_window = timedelta(hours=matching.load_window_hours)
    sql = """
    SELECT
        a.match_id,
        a.match_date,
        a.home_team,
        a.away_team,
        COALESCE(a.target_corners_home, r.corner_kicks_home_ft) AS corners_home,
        COALESCE(a.target_corners_away, r.corner_kicks_away_ft) AS corners_away
    FROM fs_soccer_all a
    LEFT JOIN fs_soccer_raw r ON r.match_id = a.match_id
    WHERE a.status = '3'
      AND a.match_id NOT LIKE '%%*%%'
      AND a.match_date >= %(min_ts)s
      AND a.match_date <= %(max_ts)s
      AND COALESCE(a.target_corners_home, r.corner_kicks_home_ft) IS NOT NULL
      AND COALESCE(a.target_corners_away, r.corner_kicks_away_ft) IS NOT NULL
    """
    min_ts = _aware(min_kickoff) - load_window
    max_ts = _aware(max_kickoff) + load_window
    rows: list[FsFinishedMatch] = []
    with conn.cursor() as cur:
        cur.execute(sql, {"min_ts": min_ts, "max_ts": max_ts})
        for match_id, match_date, home_team, away_team, corners_home, corners_away in cur.fetchall():
            corners = _row_corners(corners_home, corners_away)
            if corners is None:
                continue
            kickoff = match_date
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
            rows.append(
                FsFinishedMatch(
                    match_id=str(match_id),
                    match_date=kickoff,
                    home_team=str(home_team or ""),
                    away_team=str(away_team or ""),
                    corners=corners,
                )
            )
    return rows


def _kickoff_delta(alert_kickoff: datetime, fs_kickoff: datetime) -> timedelta:
    return abs(_aware(alert_kickoff) - _aware(fs_kickoff))


def _same_physical_match(
    left: FsFinishedMatch,
    right: FsFinishedMatch,
    *,
    left_swapped: bool,
    right_swapped: bool,
) -> bool:
    if left.match_id != right.match_id:
        return False
    return left_swapped == right_swapped


def link_alert_to_fs_match(
    alert: AlertMatchKey,
    candidates: list[FsFinishedMatch],
    *,
    matching: FsMatchingConfig = DEFAULT_MATCHING,
    aliases: Mapping[str, str] | None = None,
) -> LinkedFsMatch | None:
    window = timedelta(minutes=matching.kickoff_window_minutes)
    scored: list[tuple[float, FsFinishedMatch, bool]] = []

    for row in candidates:
        for swapped in (False, True):
            delta = _kickoff_delta(alert.kickoff_at, row.match_date)
            if delta > window:
                continue
            time_diff_min = delta.total_seconds() / 60.0
            score = pair_score(
                alert.home_name,
                alert.away_name,
                row.home_team,
                row.away_team,
                time_diff_min,
                matching=matching,
                aliases=aliases,
                swapped=swapped,
            )
            scored.append((score, row, swapped))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < matching.min_match_score:
        return None

    best_score, best_row, best_swapped = scored[0]
    second_score: float | None = None
    for alt_score, alt_row, alt_swapped in scored[1:]:
        if _same_physical_match(
            best_row,
            alt_row,
            left_swapped=best_swapped,
            right_swapped=alt_swapped,
        ):
            continue
        second_score = alt_score
        break

    second_gap = best_score - second_score if second_score is not None else best_score
    if second_gap < matching.min_second_best_gap:
        return None

    return LinkedFsMatch(
        match_id=best_row.match_id,
        match_date=best_row.match_date,
        corners=_orient_corners(best_row.corners, swapped=best_swapped),
    )
