"""Market classification — wanted, pending, and blacklisted my_selection_id lists."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class MarketRegistry:
    """Tracks my_selection_id categories and persists newly discovered ids to config."""

    wanted: set[str] = field(default_factory=set)
    pending: set[str] = field(default_factory=set)
    blacklisted: set[str] = field(default_factory=set)
    config_path: Path | None = None
    _raw_config: dict[str, Any] = field(default_factory=dict, repr=False)
    _new_this_session: set[str] = field(default_factory=set, repr=False)

    def should_process(self, my_selection_id: str) -> bool:
        """Wanted and pending templates are processed; blacklisted are ignored."""
        return my_selection_id not in self.blacklisted

    def register_seen(self, my_selection_id: str) -> None:
        """Add unknown my_selection_id values to pending and persist to config.yaml."""
        if not my_selection_id:
            return
        if my_selection_id in self.wanted or my_selection_id in self.blacklisted:
            return
        if my_selection_id in self.pending:
            return
        if my_selection_id in self._new_this_session:
            return

        self.pending.add(my_selection_id)
        self._new_this_session.add(my_selection_id)
        logger.warning(
            "New unknown my_selection_id discovered: %s — added to markets.pending in config",
            my_selection_id,
        )
        self._persist_pending()

    def _persist_pending(self) -> None:
        if self.config_path is None:
            return
        markets = self._raw_config.setdefault("markets", {})
        markets["pending"] = sorted(self.pending)
        try:
            with self.config_path.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(
                    self._raw_config,
                    fh,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                )
        except OSError:
            logger.exception("Failed to persist pending markets to %s", self.config_path)


def _parse_market_list(raw: dict[str, Any], key: str) -> set[str]:
    values = raw.get(key) or []
    if not isinstance(values, list):
        raise ValueError(f"markets.{key} must be a list")
    return {str(item) for item in values if item}


def load_market_registry(
    raw: dict[str, Any],
    *,
    config_path: Path,
) -> MarketRegistry:
    markets = raw.get("markets") or {}
    if not isinstance(markets, dict):
        raise ValueError("markets must be a mapping")

    wanted = _parse_market_list(markets, "wanted")
    pending = _parse_market_list(markets, "pending")
    blacklisted = _parse_market_list(markets, "blacklisted")

    overlap = (wanted & blacklisted) | (wanted & pending) | (pending & blacklisted)
    if overlap:
        raise ValueError(f"my_selection_id appears in multiple lists: {sorted(overlap)}")

    return MarketRegistry(
        wanted=wanted,
        pending=pending,
        blacklisted=blacklisted,
        config_path=config_path,
        _raw_config=raw,
    )
