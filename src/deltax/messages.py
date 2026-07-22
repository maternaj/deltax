"""HTML Telegram message formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from deltax.drop_detector import DropHit

PRAGUE_TZ = ZoneInfo("Europe/Prague")

EMOJI_PREMATCH = "🔵"
EMOJI_INPLAY = "🔴"
DEFAULT_SPORT_EMOJI = "🏷️"

# Tipsport super_sport_name (Czech) + English aliases → emoji.
SPORT_EMOJI_BY_NAME: dict[str, str] = {
    # Football & variants
    "fotbal": "⚽",
    "soccer": "⚽",
    "futsal": "⚽",
    "malý fotbal": "⚽",
    "mini football": "⚽",
    "plážový fotbal": "⚽",
    # American / Australian football
    "americký fotbal": "🏈",
    "football": "🏈",
    "australský fotbal": "🏈",
    "aussie rules": "🏈",
    # Hockey & stick sports
    "lední hokej": "🏒",
    "ice hockey": "🏒",
    "hokej": "🏒",
    "florbal": "🏒",
    "floorball": "🏒",
    "hokejbal": "🏒",
    "bandy": "🏒",
    "pozemní hokej": "🏑",
    "hockey": "🏑",
    "lakros": "🥍",
    # Court & field
    "basketbal": "🏀",
    "basketball": "🏀",
    "tenis": "🎾",
    "tennis": "🎾",
    "padel": "🎾",
    "squash": "🎾",
    "stolní tenis": "🏓",
    "table tennis": "🏓",
    "volejbal": "🏐",
    "volleyball": "🏐",
    "plážový volejbal": "🏐",
    "beach volleyball": "🏐",
    "házená": "🤾",
    "handball": "🤾",
    "badminton": "🏸",
    "baseball": "⚾",
    "softball": "🥎",
    "rugby": "🏉",
    "rugby union": "🏉",
    "rugby league": "🏉",
    "kriket": "🏏",
    "cricket": "🏏",
    "vodní pólo": "🤽",
    "water polo": "🤽",
    "bowls": "🎳",
    # Combat & fitness
    "box": "🥊",
    "boxing": "🥊",
    "bojové sporty": "🥊",
    "mixed martial arts": "🥊",
    "atletika": "🏃",
    # Winter sports
    "alpské lyžování": "⛷️",
    "akrobatické lyžování": "🎿",
    "klasické lyžování": "🎿",
    "skoky na lyžích": "🎿",
    "biatlon": "🎿",
    "snowboarding": "🏂",
    "curling": "🥌",
    "krasobruslení": "⛸️",
    "figure skating": "⛸️",
    "rychlobruslení": "⛸️",
    "speed skating": "⛸️",
    "short track": "⛸️",
    "short-track speed skating": "⛸️",
    "boby": "🛷",
    "bobsleigh": "🛷",
    "saně": "🛷",
    "luge": "🛷",
    "skeleton": "🛷",
    "skialpinismus": "🧗",
    "winter sports": "❄️",
    # Wheels & motors
    "cyklistika": "🚴",
    "cycling": "🚴",
    "motorsport": "🏎️",
    "motor racing": "🏎️",
    "plochá dráha": "🏍️",
    # Target & cue sports
    "šipky": "🎯",
    "darts": "🎯",
    "snooker": "🎱",
    "pool": "🎱",
    # Other
    "esporty": "🎮",
    "esports": "🎮",
    "golf": "⛳",
    "plavání": "🏊",
    "dostihy": "🏇",
    "šachy": "♟️",
    "společenské sázky": "🎰",
    "sazka specials": "🎰",
    "entertainment": "🎬",
    "novelties & specials": "🎲",
    "politics": "🗳️",
}


def format_match_url(match_url_base: str, relative_url: str) -> str:
    rel = (relative_url or "").strip()
    if not rel:
        return match_url_base
    if rel.startswith("http"):
        return rel
    if not rel.startswith("/"):
        rel = f"/{rel}"
    return f"{match_url_base}{rel}"


def normalize_sport_name(name: object) -> str:
    return str(name or "").strip().lower()


def sport_emoji(super_sport_name: object) -> str:
    key = normalize_sport_name(super_sport_name)
    if not key:
        return DEFAULT_SPORT_EMOJI
    return SPORT_EMOJI_BY_NAME.get(key, DEFAULT_SPORT_EMOJI)


def selection_icon(selection: object) -> str:
    text = str(selection or "").strip()
    lower = text.lower()
    if lower.startswith("over"):
        return "⬆️"
    if lower.startswith("under"):
        return "⬇️"
    if lower == "draw":
        return "↔️"
    if lower == "yes":
        return "✅"
    if lower == "no":
        return "❌"
    return "➡️"


def is_inplay_match(match_type: object) -> bool:
    text = str(match_type or "").strip().upper()
    if not text:
        return False
    if text in {"LIVE", "INPLAY", "IN_PLAY", "IN-PLAY"}:
        return True
    return "LIVE" in text or "INPLAY" in text


def match_phase_emoji(match_type: object) -> str:
    return EMOJI_INPLAY if is_inplay_match(match_type) else EMOJI_PREMATCH


def format_kickoff_prague(date_start_ms: int | None) -> str:
    if not date_start_ms:
        return "?"
    dt = datetime.fromtimestamp(date_start_ms / 1000, tz=timezone.utc).astimezone(PRAGUE_TZ)
    return dt.strftime("%Y-%m-%d %H:%M")


def drop_window_minutes(baseline_observed_at: float, current_observed_at: float) -> int:
    seconds = max(0.0, current_observed_at - baseline_observed_at)
    return int(seconds // 60)


def format_drop_delta(drop_pct: float, implied_drop_pct: float) -> str:
    return f"Δ -{drop_pct:.1f}%/-{implied_drop_pct:.1f}%"


def _seconds_to_kickoff(date_start_ms: int, reference_ts: float) -> int:
    kickoff_ts = date_start_ms / 1000.0
    return int(kickoff_ts - reference_ts)


def _format_countdown(total_seconds: int) -> str:
    if total_seconds < 3600:
        return f"T-{total_seconds // 60}m"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days >= 7:
        return f"T-{days}d"
    if days >= 1:
        if hours:
            return f"T-{days}d {hours}h"
        return f"T-{days}d"
    if minutes:
        return f"T-{hours}h {minutes}m"
    return f"T-{hours}h"


def _format_live_elapsed(total_seconds: int) -> str:
    if total_seconds < 3600:
        return f"LIVE +{total_seconds // 60}m"
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days >= 1:
        if hours:
            return f"LIVE +{days}d {hours}h"
        return f"LIVE +{days}d"
    if minutes:
        return f"LIVE +{hours}h {minutes}m"
    return f"LIVE +{hours}h"


def format_time_to_kickoff(date_start_ms: int | None, reference_ts: float) -> str:
    """Human-readable countdown or elapsed time; both instants compared in UTC."""
    if not date_start_ms:
        return "?"
    seconds_to_ko = _seconds_to_kickoff(date_start_ms, reference_ts)
    if seconds_to_ko < 0:
        return _format_live_elapsed(abs(seconds_to_ko))
    return _format_countdown(seconds_to_ko)


def format_line4_timing(
    date_start_ms: int | None,
    reference_ts: float,
    *,
    drop_min: int,
    drop_delta: str,
) -> str:
    kickoff = format_kickoff_prague(date_start_ms)
    ttk = format_time_to_kickoff(date_start_ms, reference_ts)
    tail = f"drop <b>{drop_min}</b> min · <b>{drop_delta}</b>"

    if not date_start_ms:
        return f"⏰ ? ({ttk}) · {tail}"

    seconds_to_ko = _seconds_to_kickoff(date_start_ms, reference_ts)
    if 0 < seconds_to_ko < 3600:
        return f"⏰ {kickoff} · <b>🔜 {ttk}</b> · {tail}"
    return f"⏰ {kickoff} (<b>{ttk}</b>) · {tail}"


def format_drop_alert_message(hit: DropHit, *, match_url_base: str) -> str:
    row = hit.row
    url = format_match_url(match_url_base, row.match_url)
    match_link = f'<a href="{escape(url, quote=True)}">{escape(row.match_name)}</a>'
    drop_delta = format_drop_delta(hit.drop_pct, hit.implied_drop_pct)
    drop_min = drop_window_minutes(hit.baseline_observed_at, hit.current_observed_at)

    line1 = f"{sport_emoji(row.super_sport_name)} <b>{escape(row.competition_name)}</b>"
    line2 = (
        f"{match_phase_emoji(row.match_type)} "
        f"{match_link}, <b>{escape(row.event_name)}</b>"
    )
    line3 = (
        f"{selection_icon(row.opp_name)} "
        f"<b>{escape(row.opp_name)} @ {hit.odds_now:.2f}</b> "
        f"(<s>{hit.odds_previous:.2f}</s>↓)"
    )
    line4 = format_line4_timing(
        row.date_start,
        hit.current_observed_at,
        drop_min=drop_min,
        drop_delta=drop_delta,
    )
    return "\n".join((line1, line2, line3, line4))
