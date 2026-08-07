"""Odds source adapters for the DeltaX monitor."""

from __future__ import annotations

import logging
from typing import Protocol

from deltax.config import AppConfig, PinnacleConfig
from deltax.parser import SelectionRow, parse_selections
from deltax.pinnacle.client import PinnacleClient
from deltax.pinnacle.flatten import flatten_selections
from deltax.pinnacle.parser import normalize_sport_feed, sport_by_id
from deltax.tipsport_client import TipsportClient

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
        self.client = client or TipsportClient(config.tipsport_base_url)

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

    def fetch_selections(self) -> tuple[list[SelectionRow], bool]:
        rows: list[SelectionRow] = []
        failed_requests = 0
        total_requests = 0
        for sport in self.pinnacle.sports:
            for market_kind in sport.market_kinds:
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
                    sports = normalize_sport_feed(body)
                except Exception:
                    failed_requests += 1
                    logger.exception(
                        "Pinnacle parse failed sport_id=%s mk=%s",
                        sport.sport_id,
                        market_kind,
                    )
                    continue
                selected = sport_by_id(sports, sport.sport_id)
                if selected is None:
                    failed_requests += 1
                    logger.error(
                        "Pinnacle response missing sport_id=%s mk=%s",
                        sport.sport_id,
                        market_kind,
                    )
                    continue
                rows.extend(
                    flatten_selections(
                        [selected],
                        prematch_only=self.pinnacle.prematch_only,
                        main_lines_only=self.pinnacle.main_lines_only,
                        period_keys=self.pinnacle.period_keys,
                        league_allowlist=sport.league_allowlist or self.pinnacle.league_allowlist,
                        league_blocklist=sport.league_blocklist or self.pinnacle.league_blocklist,
                        league_allow_name_substrings=sport.league_allow_name_substrings,
                        league_block_name_substrings=sport.league_block_name_substrings,
                        match_url_template=(
                            self.config.match_url_base
                            if "{event_id}" in self.config.match_url_base
                            else f"{self.config.match_url_base}/{{event_id}}"
                        ),
                    )
                )
        ok = total_requests == 0 or failed_requests < total_requests
        return rows, ok

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
