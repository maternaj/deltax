"""Flatten normalized Pinnacle sport feeds into DeltaX SelectionRow objects."""

from __future__ import annotations

from typing import Any

from deltax.parser import SelectionRow
from deltax.pinnacle.urls import build_match_url


def stable_opp_id(event_id: int, my_selection_id: str) -> int:
    """Stable in-memory key — survives Pinnacle line_id changes on handicap moves."""
    digest = hash((event_id, my_selection_id)) & 0x7FFFFFFFFFFFFFFF
    return digest or 1


def build_my_selection_id(sport_id: int, period_key: str, market: str, side: str) -> str:
    return f"{sport_id}-{period_key}-{market}-{side}"


MARKET_EVENT_LABELS: dict[str, str] = {
    "MONEYLINE": "Moneyline",
    "SPREAD": "Handicap",
    "TOTAL": "Over/Under",
}


def format_market_event_name(*, market: str, period: dict[str, Any]) -> str:
    """Human-readable market label for Telegram line 2 (Tipsport uses event.name)."""
    label = MARKET_EVENT_LABELS.get(market, market.replace("_", " ").title())
    period_key = str(period.get("period_key") or "0")
    name = period.get("name")
    period_label = ""
    if isinstance(name, str):
        cleaned = name.strip()
        if cleaned and not cleaned.isdigit():
            generic = cleaned.casefold() in {"match", "game"}
            if period_key != "0" or not generic:
                period_label = cleaned
    if not period_label and period_key != "0":
        period_label = f"Period {period_key}"
    if period_label:
        return f"{period_label} · {label}"
    return label

def _is_truthy_flag(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "o", "live", "running"}
    return bool(value)


def is_prematch_event(event: dict[str, Any], *, prematch_only: bool) -> bool:
    if event.get("market_section") == "live":
        return False
    if prematch_only and event.get("market_section") != "normal":
        return False
    # `running` = in-play clock; primary guard against live odds.
    if _is_truthy_flag(event.get("running")):
        return False
    # In mk=1 (today) feeds, normal-section prematch rows often keep live=1
    # (live betting offered) while running=0 — do not treat that as in-play.
    if _is_truthy_flag(event.get("live")) and event.get("market_section") != "normal":
        return False
    return True


def _league_allowed(
    league: dict[str, Any],
    *,
    allowlist: tuple[int, ...],
    blocklist: tuple[int, ...],
    allow_name_substrings: tuple[str, ...],
    block_name_substrings: tuple[str, ...],
) -> bool:
    league_id = int(league.get("league_id") or 0)
    league_name = str(league.get("league_name") or "").casefold()
    if blocklist and league_id in blocklist:
        return False
    if allow_name_substrings:
        folded = [part.casefold() for part in allow_name_substrings]
        if not any(part in league_name for part in folded):
            return False
    if block_name_substrings:
        folded = [part.casefold() for part in block_name_substrings]
        if any(part in league_name for part in folded):
            return False
    if allowlist:
        return league_id in allowlist
    return True


def _pick_main_line(lines: list[dict[str, Any]], main_line_index: Any) -> dict[str, Any] | None:
    if not lines:
        return None
    if isinstance(main_line_index, int) and 0 <= main_line_index < len(lines):
        candidate = lines[main_line_index]
        if candidate.get("alternate") in (None, 0, False):
            return candidate
    for line in lines:
        if line.get("alternate") in (None, 0, False):
            return line
    return lines[0]


def _parse_odd(value: Any) -> float | None:
    if value is None:
        return None
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    if odd <= 1.0:
        return None
    return odd


def _line_open(line: dict[str, Any] | None) -> bool:
    if line is None:
        return False
    indicator = line.get("indicator")
    if indicator is None:
        return True
    if isinstance(indicator, str) and indicator.strip().upper() in {"X", "S", "C"}:
        return False
    return True


def _build_snapshot(
    *,
    sport: dict[str, Any],
    league: dict[str, Any],
    event: dict[str, Any],
    period: dict[str, Any],
    line: dict[str, Any] | None,
    my_selection_id: str,
    line_id: int | None,
) -> dict[str, Any]:
    return {
        "source": "pinnacle",
        "sport_id": sport.get("sport_id"),
        "sport_name": sport.get("sport_name"),
        "league_id": league.get("league_id"),
        "league_name": league.get("league_name"),
        "event_id": event.get("event_id"),
        "market_section": event.get("market_section"),
        "my_selection_id": my_selection_id,
        "line_id": line_id,
        "period_key": period.get("period_key"),
        "line": line,
        "event": {
            "event_id": event.get("event_id"),
            "home": event.get("home"),
            "away": event.get("away"),
            "start_time_unix_ms": event.get("start_time_unix_ms"),
            "market_section": event.get("market_section"),
        },
    }


def _append_row(
    rows: list[SelectionRow],
    *,
    sport: dict[str, Any],
    league: dict[str, Any],
    event: dict[str, Any],
    period: dict[str, Any],
    my_selection_id: str,
    opp_name: str,
    odd: float,
    line: dict[str, Any] | None,
    line_id: int | None,
    market: str,
    match_url_base: str,
    match_url_style: str | None,
    sport_slug_overrides: dict[int, str] | None,
    betting_enabled: bool,
) -> None:
    event_id = int(event["event_id"])
    template = my_selection_id
    rows.append(
        SelectionRow(
            opp_id=stable_opp_id(event_id, template),
            event_id=event_id,
            match_id=event_id,
            my_selection_id=template,
            match_name=str(event.get("match_name") or ""),
            home_participant=str(event.get("home") or ""),
            visiting_participant=str(event.get("away") or ""),
            competition_name=str(league.get("league_name") or ""),
            sport_name=str(sport.get("sport_name") or ""),
            super_sport_name=str(sport.get("sport_name") or ""),
            match_type="PREMATCH",
            event_name=format_market_event_name(market=market, period=period),
            opp_name=opp_name,
            odd=odd,
            betting_enabled=betting_enabled,
            opp_type=None,
            opp_number=str(line.get("handicap_label") or line.get("points") or "") if line else None,
            match_url=build_match_url(
                match_url_base=match_url_base,
                sport=sport,
                league=league,
                event=event,
                style=match_url_style,
                sport_slug_overrides=sport_slug_overrides,
            ),
            date_start=int(event["start_time_unix_ms"])
            if event.get("start_time_unix_ms") is not None
            else None,
            tipsport_snapshot=_build_snapshot(
                sport=sport,
                league=league,
                event=event,
                period=period,
                line=line,
                my_selection_id=template,
                line_id=line_id,
            ),
        )
    )


def _flatten_period(
    rows: list[SelectionRow],
    *,
    sport: dict[str, Any],
    league: dict[str, Any],
    event: dict[str, Any],
    period: dict[str, Any],
    match_url_base: str,
    match_url_style: str | None,
    sport_slug_overrides: dict[int, str] | None,
    main_lines_only: bool,
) -> None:
    sport_id = int(sport["sport_id"])
    period_key = str(period.get("period_key") or "0")
    main_line_index = period.get("main_line_index")

    moneyline = period.get("moneyline")
    if isinstance(moneyline, dict) and _line_open(moneyline):
        line_id = _integer_line_id(moneyline.get("line_id"))
        for side, key, label in (
            ("HOME", "home_odds", event.get("home")),
            ("AWAY", "away_odds", event.get("away")),
            ("DRAW", "draw_odds", "Draw"),
        ):
            odd = _parse_odd(moneyline.get(key))
            if odd is None:
                continue
            template = build_my_selection_id(sport_id, period_key, "MONEYLINE", side)
            _append_row(
                rows,
                sport=sport,
                league=league,
                event=event,
                period=period,
                my_selection_id=template,
                opp_name=str(label or side.title()),
                odd=odd,
                line=moneyline,
                line_id=line_id,
                market="MONEYLINE",
                match_url_base=match_url_base,
                match_url_style=match_url_style,
                sport_slug_overrides=sport_slug_overrides,
                betting_enabled=True,
            )

    spreads = list(period.get("spreads") or [])
    if main_lines_only:
        spread = _pick_main_line(spreads, main_line_index)
        spread_lines = [spread] if spread else []
    else:
        spread_lines = spreads

    for spread in spread_lines:
        if not _line_open(spread):
            continue
        line_id = _integer_line_id(spread.get("line_id"))
        label = str(spread.get("handicap_label") or "")
        for side, key, name in (
            ("HOME", "home_odds", event.get("home")),
            ("AWAY", "away_odds", event.get("away")),
        ):
            odd = _parse_odd(spread.get(key))
            if odd is None:
                continue
            template = build_my_selection_id(sport_id, period_key, "SPREAD", side)
            _append_row(
                rows,
                sport=sport,
                league=league,
                event=event,
                period=period,
                my_selection_id=template,
                opp_name=f"{name} {label}".strip(),
                odd=odd,
                line=spread,
                line_id=line_id,
                market="SPREAD",
                match_url_base=match_url_base,
                match_url_style=match_url_style,
                sport_slug_overrides=sport_slug_overrides,
                betting_enabled=True,
            )

    totals = list(period.get("totals") or [])
    if main_lines_only:
        total = _pick_main_line(totals, main_line_index)
        total_lines = [total] if total else []
    else:
        total_lines = totals

    for total in total_lines:
        if not _line_open(total):
            continue
        line_id = _integer_line_id(total.get("line_id"))
        points = total.get("points")
        label = str(total.get("handicap_label") or points or "")
        for side, key in (("OVER", "over_odds"), ("UNDER", "under_odds")):
            odd = _parse_odd(total.get(key))
            if odd is None:
                continue
            template = build_my_selection_id(sport_id, period_key, "TOTAL", side)
            opp_name = f"{side.title()} {label}".strip()
            _append_row(
                rows,
                sport=sport,
                league=league,
                event=event,
                period=period,
                my_selection_id=template,
                opp_name=opp_name,
                odd=odd,
                line=total,
                line_id=line_id,
                market="TOTAL",
                match_url_base=match_url_base,
                match_url_style=match_url_style,
                sport_slug_overrides=sport_slug_overrides,
                betting_enabled=True,
            )


def _integer_line_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def flatten_selections(
    sports: list[dict[str, Any]],
    *,
    prematch_only: bool = True,
    main_lines_only: bool = True,
    period_keys: tuple[str, ...] = ("0",),
    league_allowlist: tuple[int, ...] = (),
    league_blocklist: tuple[int, ...] = (),
    league_allow_name_substrings: tuple[str, ...] = (),
    league_block_name_substrings: tuple[str, ...] = (),
    match_url_base: str = "https://www.ps3838.com/en",
    match_url_style: str | None = None,
    sport_slug_overrides: dict[int, str] | None = None,
) -> list[SelectionRow]:
    rows: list[SelectionRow] = []
    for sport in sports:
        for league in sport.get("leagues") or []:
            if not _league_allowed(
                league,
                allowlist=league_allowlist,
                blocklist=league_blocklist,
                allow_name_substrings=league_allow_name_substrings,
                block_name_substrings=league_block_name_substrings,
            ):
                continue
            for event in league.get("events") or []:
                if not is_prematch_event(event, prematch_only=prematch_only):
                    continue
                for period in event.get("periods") or []:
                    if period_keys and str(period.get("period_key")) not in period_keys:
                        continue
                    _flatten_period(
                        rows,
                        sport=sport,
                        league=league,
                        event=event,
                        period=period,
                        match_url_base=match_url_base,
                        match_url_style=match_url_style,
                        sport_slug_overrides=sport_slug_overrides,
                        main_lines_only=main_lines_only,
                    )
    return rows
