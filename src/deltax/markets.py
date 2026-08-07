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
    blacklisted_prefixes: tuple[str, ...] = field(default_factory=tuple)
    config_path: Path | None = None
    _raw_config: dict[str, Any] = field(default_factory=dict, repr=False)
    _new_this_session: set[str] = field(default_factory=set, repr=False)

    def is_blacklisted(self, my_selection_id: str) -> bool:
        """True when my_selection_id matches an exact or prefix blacklist entry."""
        if my_selection_id in self.blacklisted:
            return True
        return any(my_selection_id.startswith(prefix) for prefix in self.blacklisted_prefixes)

    def should_process(self, my_selection_id: str) -> bool:
        """Wanted and pending templates are processed; blacklisted are ignored."""
        return not self.is_blacklisted(my_selection_id)

    def register_seen(self, my_selection_id: str) -> None:
        """Add unknown my_selection_id values to pending and persist to the active config file."""
        if not my_selection_id:
            return
        if my_selection_id in self.wanted or self.is_blacklisted(my_selection_id):
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


def _parse_blacklisted_prefixes(raw: dict[str, Any]) -> tuple[str, ...]:
    values = raw.get("blacklisted_prefixes") or []
    if not isinstance(values, list):
        raise ValueError("markets.blacklisted_prefixes must be a list")
    prefixes = {str(item).strip() for item in values if str(item).strip()}
    return tuple(sorted(prefixes))


def event_name_excluded(event_name: object, substrings: tuple[str, ...]) -> bool:
    """Case-sensitive substring match against Tipsport event name (Telegram line 2)."""
    if not substrings:
        return False
    name = str(event_name or "")
    return any(substring in name for substring in substrings)


def _blacklist_conflicts(
    ids: set[str],
    *,
    blacklisted: set[str],
    blacklisted_prefixes: tuple[str, ...],
) -> set[str]:
    return {item for item in ids if item in blacklisted or any(item.startswith(p) for p in blacklisted_prefixes)}


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
    blacklisted_prefixes = _parse_blacklisted_prefixes(markets)

    overlap = (wanted & blacklisted) | (wanted & pending) | (pending & blacklisted)
    if overlap:
        raise ValueError(f"my_selection_id appears in multiple lists: {sorted(overlap)}")

    prefix_overlap = _blacklist_conflicts(
        wanted | pending,
        blacklisted=blacklisted,
        blacklisted_prefixes=blacklisted_prefixes,
    )
    if prefix_overlap:
        raise ValueError(
            "my_selection_id in wanted/pending matches markets.blacklisted_prefixes: "
            f"{sorted(prefix_overlap)}"
        )

    return MarketRegistry(
        wanted=wanted,
        pending=pending,
        blacklisted=blacklisted,
        blacklisted_prefixes=blacklisted_prefixes,
        config_path=config_path,
        _raw_config=raw,
    )
