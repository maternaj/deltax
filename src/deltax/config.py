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
class AppConfig:
    tipsport_base_url: str
    tipsport_endpoint: str
    refresh_seconds: int
    selection_ttl_seconds: int
    max_odds: float
    drop_tiers: tuple[DropTier, ...]
    match_url_base: str
    default_alert_groups: str
    config_path: Path
    market_registry: MarketRegistry


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


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

    market_registry = load_market_registry(raw, config_path=config_path)

    return AppConfig(
        tipsport_base_url=str(tipsport.get("base_url") or "https://www.tipsport.cz").rstrip("/"),
        tipsport_endpoint=str(tipsport.get("endpoint") or ""),
        refresh_seconds=refresh,
        selection_ttl_seconds=selection_ttl,
        max_odds=max_odds,
        drop_tiers=tuple(sorted(tiers, key=lambda t: t.window_seconds)),
        match_url_base=str(telegram.get("match_url_base") or "https://www.tipsport.cz").rstrip("/"),
        default_alert_groups=str(
            env.get("DELTAX_ALERT_GROUPS") or telegram.get("default_alert_groups") or "A"
        ),
        config_path=config_path,
        market_registry=market_registry,
    )


def load_env(dotenv_path: Path | None = None) -> None:
    root = _project_root()
    path = dotenv_path or root / ".env"
    if path.is_file():
        load_dotenv(path)
