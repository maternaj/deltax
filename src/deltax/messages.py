"""HTML Telegram message formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from deltax.drop_detector import DropHit


def format_match_url(match_url_base: str, relative_url: str) -> str:
    rel = (relative_url or "").strip()
    if not rel:
        return match_url_base
    if rel.startswith("http"):
        return rel
    if not rel.startswith("/"):
        rel = f"/{rel}"
    return f"{match_url_base}{rel}"


def format_kickoff(date_start_ms: int | None) -> str:
    if not date_start_ms:
        return "—"
    dt = datetime.fromtimestamp(date_start_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def format_drop_alert_message(hit: DropHit, *, match_url_base: str) -> str:
    row = hit.row
    url = format_match_url(match_url_base, row.match_url)
    tier_seconds = hit.tier.window_seconds
    if tier_seconds == 0:
        tier_label = "poll"
    elif tier_seconds < 60:
        tier_label = f"{tier_seconds}s"
    else:
        tier_label = f"{tier_seconds // 60}m"

    lines = [
        "<b>DeltaX — prematch odds drop</b>",
        "",
        f"<b>{escape(row.match_name)}</b>",
        escape(row.competition_name),
        f"Kickoff: {format_kickoff(row.date_start)}",
        "",
        f"Market: {escape(row.event_name)}",
        f"Selection: {escape(row.opp_name)}",
        "",
        f"Odds: {hit.baseline_odds:.2f} → {hit.current_odds:.2f}",
        f"Drop: <b>{hit.drop_pct:.1f}%</b> (tier {tier_label} / {hit.tier.drop_pct:g}%)",
        "",
        f'<a href="{escape(url, quote=True)}">Tipsport prematch</a>',
    ]
    return "\n".join(lines)
