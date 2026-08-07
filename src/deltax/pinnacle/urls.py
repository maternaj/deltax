"""Build Pinnacle / PS3838 web deeplinks for Telegram alerts."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def strip_participant_suffix(name: str) -> str:
    """Match site behavior: drop parenthetical team suffixes before slugging."""
    return name.split("(", 1)[0].strip()


def ps3838_path_slug(text: str) -> str:
    """Mirror ps3838 generateSportsDetailsPageURL slugging (case preserved)."""
    text = unicodedata.normalize("NFKC", strip_participant_suffix(text or ""))
    return text.replace(" - ", "-").replace(" ", "-").replace("/", "-")


def slugify(text: str) -> str:
    """Lowercase slug used by pinnacle.com classic URLs."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def build_event_slug(home: str, away: str, *, style: str) -> str:
    home = strip_participant_suffix(home)
    away = strip_participant_suffix(away)
    if style == "stats":
        return ps3838_path_slug(f"{home} vs {away}")
    return slugify(f"{home}-vs-{away}")


def sport_slug(sport: dict[str, Any], *, overrides: dict[int, str] | None = None) -> str:
    sport_id = int(sport["sport_id"])
    if overrides and sport_id in overrides:
        return slugify(overrides[sport_id])
    configured = str(sport.get("url_slug") or "").strip()
    if configured:
        return slugify(configured)
    name = str(sport.get("sport_name") or "").strip().lower()
    if name in {"soccer", "football"}:
        return "soccer"
    if name:
        return slugify(name)
    return str(sport_id)


def detect_match_url_style(match_url_base: str) -> str:
    lowered = (match_url_base or "").casefold()
    if "ps3838" in lowered:
        return "stats"
    if "/compact" in lowered:
        return "compact_matchup"
    return "classic"


def build_match_url(
    *,
    match_url_base: str,
    sport: dict[str, Any],
    league: dict[str, Any],
    event: dict[str, Any],
    style: str | None = None,
    sport_slug_overrides: dict[int, str] | None = None,
) -> str:
    """Return a bookmaker event deeplink.

    stats (PS3838 default web):
      /en/sports/{sport}/stats/{league}/{home-vs-away}/{event_id}

    compact_matchup (PS3838 compact — often blank in B2B):
      /en/compact/sports/{sport}/matchup/{league}/{teams}/{league_id}/{event_id}

    classic (pinnacle.com):
      /en/{sport}/{league}/{teams}/{event_id}/
    """
    base = (match_url_base or "").rstrip("/")
    resolved_style = style or detect_match_url_style(base)
    sport_part = sport_slug(sport, overrides=sport_slug_overrides)
    league_name = str(league.get("league_name") or "")
    event_id = int(event["event_id"])
    parent_event_id = event.get("parent_event_id")
    event_id_part = (
        f"{event_id},{int(parent_event_id)}"
        if parent_event_id not in (None, 0, event_id)
        else str(event_id)
    )

    if resolved_style == "stats":
        league_slug = ps3838_path_slug(league_name)
        event_slug = build_event_slug(
            str(event.get("home") or ""),
            str(event.get("away") or ""),
            style="stats",
        )
        return f"{base}/sports/{sport_part}/stats/{league_slug}/{event_slug}/{event_id_part}"

    league_slug = slugify(league_name) if resolved_style != "compact_matchup" else ps3838_path_slug(league_name)
    event_slug = build_event_slug(
        str(event.get("home") or ""),
        str(event.get("away") or ""),
        style="compact_matchup" if resolved_style == "compact_matchup" else "classic",
    )

    if resolved_style == "compact_matchup":
        league_id = int(league["league_id"])
        compact_base = base if "/compact" in base else f"{base}/compact"
        return (
            f"{compact_base}/sports/{sport_part}/matchup/"
            f"{league_slug}/{event_slug}/{league_id}/{event_id_part}"
        )

    return f"{base}/{sport_part}/{league_slug}/{event_slug}/{event_id}/"
