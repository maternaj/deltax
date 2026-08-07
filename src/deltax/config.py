"""Load config.yaml and environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from deltax.markets import MarketRegistry, load_market_registry


@dataclass(frozen=True)
class DropTier:
    window_seconds: int
    drop_pct: float
    implied_drop_pct: float = 0.0


@dataclass(frozen=True)
class SettleConfig:
    sleep_seconds: int
    default_delay_hours: float
    max_age_days: int
    batch_match_limit: int
    match_request_delay_seconds: float
    market_delay_hours: dict[str, float]

    def delay_hours_for(self, my_selection_id: str) -> float:
        return self.market_delay_hours.get(my_selection_id, self.default_delay_hours)


@dataclass(frozen=True)
class AppConfig:
    tipsport_base_url: str
    tipsport_endpoints: tuple[str, ...]
    refresh_seconds: int
    selection_ttl_seconds: int
    max_odds: float
    excluded_event_name_substrings: tuple[str, ...]
    drop_tiers: tuple[DropTier, ...]
    match_url_base: str
    default_alert_groups: str
    settle: SettleConfig
    config_path: Path
    market_registry: MarketRegistry


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_tipsport_endpoints(tipsport: dict[str, Any], env: dict[str, str]) -> tuple[str, ...]:
    """Resolve Tipsport feed paths from endpoints list or legacy endpoint string."""
    env_raw = (env.get("DELTAX_TIPSPORT_ENDPOINTS") or "").strip()
    if env_raw:
        endpoints = [part.strip() for part in env_raw.split(",") if part.strip()]
    else:
        raw_endpoints = tipsport.get("endpoints")
        if raw_endpoints is not None:
            if not isinstance(raw_endpoints, list):
                raise ValueError("tipsport.endpoints must be a list of path strings")
            endpoints = [str(item).strip() for item in raw_endpoints if str(item).strip()]
        else:
            single = str(tipsport.get("endpoint") or "").strip()
            endpoints = [single] if single else []

    if not endpoints:
        raise ValueError("tipsport.endpoints (or legacy tipsport.endpoint) must be set")
    return tuple(endpoints)


def _parse_settle_config(settle: dict[str, Any], env: dict[str, str]) -> SettleConfig:
    sleep_seconds = int(env.get("DELTAX_SETTLE_SLEEP_SECONDS") or settle.get("sleep_seconds") or 900)
    if sleep_seconds < 60:
        raise ValueError("settle.sleep_seconds must be >= 60")

    default_delay_hours = float(
        env.get("DELTAX_SETTLE_DEFAULT_DELAY_HOURS") or settle.get("default_delay_hours") or 6
    )
    if default_delay_hours < 0:
        raise ValueError("settle.default_delay_hours must be >= 0")

    max_age_days = int(env.get("DELTAX_SETTLE_MAX_AGE_DAYS") or settle.get("max_age_days") or 3)
    if max_age_days < 1:
        raise ValueError("settle.max_age_days must be >= 1")

    batch_match_limit = int(settle.get("batch_match_limit") or 50)
    if batch_match_limit < 1:
        raise ValueError("settle.batch_match_limit must be >= 1")

    match_request_delay_seconds = float(settle.get("match_request_delay_seconds") or 5)
    if match_request_delay_seconds < 0:
        raise ValueError("settle.match_request_delay_seconds must be >= 0")

    raw_delays = settle.get("market_delay_hours") or {}
    if not isinstance(raw_delays, dict):
        raise ValueError("settle.market_delay_hours must be a mapping of my_selection_id -> hours")
    market_delay_hours: dict[str, float] = {}
    for key, value in raw_delays.items():
        market_id = str(key).strip()
        if not market_id:
            continue
        hours = float(value)
        if hours < 0:
            raise ValueError(f"settle.market_delay_hours[{market_id!r}] must be >= 0")
        market_delay_hours[market_id] = hours

    return SettleConfig(
        sleep_seconds=sleep_seconds,
        default_delay_hours=default_delay_hours,
        max_age_days=max_age_days,
        batch_match_limit=batch_match_limit,
        match_request_delay_seconds=match_request_delay_seconds,
        market_delay_hours=market_delay_hours,
    )


def _parse_excluded_event_name_substrings(monitor: dict[str, Any]) -> tuple[str, ...]:
    values = monitor.get("excluded_event_name_substrings") or []
    if not isinstance(values, list):
        raise ValueError("monitor.excluded_event_name_substrings must be a list")
    substrings = [str(item) for item in values if str(item)]
    return tuple(substrings)


def load_config(env: dict[str, str] | None = None) -> AppConfig:
    env = env or dict(os.environ)
    root = _project_root()
    config_path = Path(env.get("DELTAX_CONFIG_PATH") or root / "config.yaml")
    if not config_path.is_file():
        raise ValueError(f"Config file not found: {config_path}")

    with config_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    tipsport = raw.get("tipsport") or {}
    monitor = raw.get("monitor") or {}
    telegram = raw.get("telegram") or {}
    settle = _parse_settle_config(raw.get("settle") or {}, env)

    tiers: list[DropTier] = []
    for row in raw.get("drop_tiers") or []:
        window_seconds = int(row["window_seconds"])
        if window_seconds < 0:
            raise ValueError(f"drop tier window_seconds must be >= 0, got {window_seconds}")
        drop_pct = float(row["drop_pct"])
        implied_drop_pct = float(row.get("implied_drop_pct") or 0)
        if drop_pct < 0 or implied_drop_pct < 0:
            raise ValueError("drop tier thresholds must be >= 0")
        tiers.append(
            DropTier(
                window_seconds=window_seconds,
                drop_pct=drop_pct,
                implied_drop_pct=implied_drop_pct,
            )
        )
    if not tiers:
        raise ValueError("drop_tiers must contain at least one entry")

    refresh = int(env.get("DELTAX_REFRESH_SECONDS") or monitor.get("refresh_seconds") or 30)
    if refresh < 5:
        raise ValueError("refresh_seconds must be >= 5")

    selection_ttl = int(
        env.get("DELTAX_SELECTION_TTL_SECONDS") or monitor.get("selection_ttl_seconds") or 600
    )
    if selection_ttl < refresh:
        raise ValueError("selection_ttl_seconds must be >= refresh_seconds")

    max_odds = float(
        env.get("DELTAX_MAX_ODDS") or monitor.get("max_odds") or monitor.get("min_odds") or 5.0
    )
    if max_odds < 0:
        raise ValueError("max_odds must be >= 0 (0 = no cap)")

    excluded_event_name_substrings = _parse_excluded_event_name_substrings(monitor)
    market_registry = load_market_registry(raw, config_path=config_path)

    return AppConfig(
        tipsport_base_url=str(tipsport.get("base_url") or "https://www.tipsport.cz").rstrip("/"),
        tipsport_endpoints=_parse_tipsport_endpoints(tipsport, env),
        refresh_seconds=refresh,
        selection_ttl_seconds=selection_ttl,
        max_odds=max_odds,
        excluded_event_name_substrings=excluded_event_name_substrings,
        drop_tiers=tuple(sorted(tiers, key=lambda t: t.window_seconds)),
        match_url_base=str(telegram.get("match_url_base") or "https://www.tipsport.cz").rstrip("/"),
        default_alert_groups=str(
            env.get("DELTAX_ALERT_GROUPS") or telegram.get("default_alert_groups") or "A"
        ),
        settle=settle,
        config_path=config_path,
        market_registry=market_registry,
    )


def load_env(dotenv_path: Path | None = None) -> None:
    root = _project_root()
    path = dotenv_path or root / ".env"
    if path.is_file():
        load_dotenv(path)
