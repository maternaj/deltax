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

# English (Sharpener) + Czech Tipsport super-sport names → emoji.
SPORT_EMOJI_BY_NAME: dict[str, str] = {
    "soccer": "⚽",
    "fotbal": "⚽",
    "futsal": "⚽",
    "mini football": "⚽",
    "ice hockey": "🏒",
    "hokej": "🏒",
    "floorball": "🏒",
    "tennis": "🎾",
    "basketball": "🏀",
    "esports": "🎮",
    "table tennis": "🏓",
    "stolní tenis": "🏓",
    "baseball": "⚾",
    "handball": "🤾",
    "házená": "🤾",
    "volleyball": "🏐",
    "volejbal": "🏐",
    "beach volleyball": "🏐",
    "darts": "🎯",
    "šipky": "🎯",
    "winter sports": "❄️",
    "mixed martial arts": "🥊",
    "cricket": "🏏",
    "badminton": "🏸",
    "sazka specials": "🎰",
    "curling": "🥌",
    "motor racing": "🏎️",
    "rugby union": "🏉",
    "snooker": "🎱",
    "speed skating": "⛸️",
    "football": "🏈",
    "americký fotbal": "🏈",
    "rugby league": "🏉",
    "boxing": "🥊",
    "snowboarding": "🏂",
    "cycling": "🚴",
    "cyklistika": "🚴",
    "water polo": "🤽",
    "aussie rules": "🏈",
    "hockey": "🏑",
    "squash": "🎾",
    "golf": "⛳",
    "entertainment": "🎬",
    "politics": "🗳️",
    "novelties & specials": "🎲",
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


def format_drop_alert_message(hit: DropHit, *, match_url_base: str) -> str:
    row = hit.row
    url = format_match_url(match_url_base, row.match_url)
    opp_link = f'<a href="{escape(url, quote=True)}">{hit.opp_id}</a>'
    drop_delta = f"→ Δ -{hit.drop_pct:.1f}%/-{hit.implied_drop_pct:.1f}%"
    drop_min = drop_window_minutes(hit.baseline_observed_at, hit.current_observed_at)

    line1 = f"{sport_emoji(row.super_sport_name)} {escape(row.competition_name)}"
    line2 = (
        f"{match_phase_emoji(row.match_type)} "
        f"{escape(row.match_name)}, <b>{escape(row.event_name)}</b>"
    )
    line3 = (
        f"{selection_icon(row.opp_name)} {escape(row.opp_name)} "
        f"<b>@ {hit.odds_now:.2f}</b> · was {hit.odds_previous:.2f} {drop_delta}"
    )
    line4 = (
        f"⏰ {format_kickoff_prague(row.date_start)} · "
        f"drop <b>{drop_min}</b> min · opp {opp_link}"
    )
    return "\n".join((line1, line2, line3, line4))
