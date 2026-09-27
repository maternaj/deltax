"""Odds source adapters for the DeltaX monitor."""

from __future__ import annotations

import logging
from typing import Protocol

from deltax.config import AppConfig, PinnacleConfig, PinnacleSportConfig
from deltax.parser import SelectionRow, parse_selections
from deltax.pinnacle.client import PinnacleClient
from deltax.pinnacle.flatten import flatten_selections
from deltax.pinnacle.parser import normalize_sport_feed, sport_by_id
from deltax.tipsport_client import TipsportClient, default_monitor_state_file

logger = logging.getLogger(__name__)


class OddsSource(Protocol):
    def fetch_selections(self) -> tuple[list[SelectionRow], bool]: ...
    def close(self) -> None: ...


class TipsportSource:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: TipsportClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or TipsportClient(
            config.tipsport_base_url,
            state_file=default_monitor_state_file(),
        )

    def fetch_selections(self) -> tuple[list[SelectionRow], bool]:
        rows: list[SelectionRow] = []
        failed_endpoints = 0
        for endpoint in self.config.tipsport_endpoints:
            payload = self.client.fetch(endpoint)
            if payload is None:
                failed_endpoints += 1
                logger.error("Tipsport fetch failed for endpoint=%s", endpoint)
                continue
            rows.extend(parse_selections(payload))
        ok = failed_endpoints < len(self.config.tipsport_endpoints)
        return rows, ok

    def close(self) -> None:
        self.client.close()


def _dedupe_rows_by_opp_id(rows: list[SelectionRow]) -> list[SelectionRow]:
    """Later rows win — used when mk=1 overlays mk=0 in the same cycle."""
    by_opp: dict[int, SelectionRow] = {}
    for row in rows:
        by_opp[row.opp_id] = row
    return list(by_opp.values())


class PinnacleSource:
    def __init__(
        self,
        config: AppConfig,
        pinnacle: PinnacleConfig,
        *,
        client: PinnacleClient | None = None,
    ) -> None:
        self.config = config
        self.pinnacle = pinnacle
        self.client = client or PinnacleClient(
            origins=pinnacle.origins,
            fresh_attempts=pinnacle.fresh_attempts,
            max_origin_age_seconds=pinnacle.max_origin_age_seconds,
        )

    def _flatten_sport_feed(
        self,
        body: dict,
        *,
        sport: PinnacleSportConfig,
        sport_slug_overrides: dict[int, str],
    ) -> list[SelectionRow]:
        sports = normalize_sport_feed(body)
        selected = sport_by_id(sports, sport.sport_id)
        if selected is None:
            raise ValueError(f"Pinnacle response missing sport_id={sport.sport_id}")
        return flatten_selections(
            [selected],
            prematch_only=self.pinnacle.prematch_only,
            main_lines_only=self.pinnacle.main_lines_only,
            period_keys=self.pinnacle.period_keys,
            league_allowlist=sport.league_allowlist or self.pinnacle.league_allowlist,
            league_blocklist=sport.league_blocklist or self.pinnacle.league_blocklist,
            league_allow_name_substrings=sport.league_allow_name_substrings,
            league_block_name_substrings=sport.league_block_name_substrings,
            match_url_base=self.config.match_url_base,
            sport_slug_overrides=sport_slug_overrides or None,
        )

    def fetch_selections(self) -> tuple[list[SelectionRow], bool]:
        rows: list[SelectionRow] = []
        failed_requests = 0
        total_requests = 0
        sport_slug_overrides = {
            sport.sport_id: sport.name for sport in self.pinnacle.sports if sport.name
        }
        use_relative = bool(self.pinnacle.relative_units)
        for sport in self.pinnacle.sports:
            for market_kind in sport.market_kinds:
                if use_relative:
                    for relative_unit in self.pinnacle.relative_units:
                        total_requests += 1
                        body = self.client.fetch_relative_markets_bulk(
                            sport.sport_id,
                            market_kind,
                            relative_unit,
                        )
                        if body is None:
                            failed_requests += 1
                            logger.error(
                                "Pinnacle fetch failed sport_id=%s mk=%s ru=%s",
                                sport.sport_id,
                                market_kind,
                                relative_unit,
                            )
                            continue
                        try:
                            rows.extend(
                                self._flatten_sport_feed(
                                    body,
                                    sport=sport,
                                    sport_slug_overrides=sport_slug_overrides,
                                )
                            )
                        except Exception:
                            failed_requests += 1
                            logger.exception(
                                "Pinnacle parse failed sport_id=%s mk=%s ru=%s",
                                sport.sport_id,
                                market_kind,
                                relative_unit,
                            )
                    continue

                total_requests += 1
                body = self.client.fetch_events(sport.sport_id, market_kind)
                if body is None:
                    failed_requests += 1
                    logger.error(
                        "Pinnacle fetch failed sport_id=%s mk=%s",
                        sport.sport_id,
                        market_kind,
                    )
                    continue
                try:
                    rows.extend(
                        self._flatten_sport_feed(
                            body,
                            sport=sport,
                            sport_slug_overrides=sport_slug_overrides,
                        )
                    )
                except Exception:
                    failed_requests += 1
                    logger.exception(
                        "Pinnacle parse failed sport_id=%s mk=%s",
                        sport.sport_id,
                        market_kind,
                    )
        ok = total_requests == 0 or failed_requests < total_requests
        return _dedupe_rows_by_opp_id(rows), ok

    def close(self) -> None:
        self.client.close()


def build_odds_source(
    config: AppConfig,
    *,
    client: TipsportClient | PinnacleClient | None = None,
) -> OddsSource:
    if config.source == "pinnacle":
        if config.pinnacle is None:
            raise ValueError("source=pinnacle requires a pinnacle section in config")
        return PinnacleSource(config, config.pinnacle, client=client)  # type: ignore[arg-type]
    return TipsportSource(config, client=client)  # type: ignore[arg-type]
