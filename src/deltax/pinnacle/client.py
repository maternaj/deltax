"""Pinnacle public mirror HTTP client."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from curl_cffi import requests

from deltax.pinnacle.freshness import (
    CapturedResponse,
    FreshTokenFactory,
    build_api_headers,
    fetch_fresh_json,
)
from deltax.pinnacle.protocol import (
    ORIGINS_WITHOUT_CF_CACHE_STATUS,
    PA_ORIGIN,
    PA_ORIGINS,
    FreshnessError,
)

logger = logging.getLogger(__name__)


def _api_root(origin: str) -> str:
    return f"{origin.rstrip('/')}/sports-service/sv/compact"


def build_sports_url(token: str, *, origin: str = PA_ORIGIN) -> str:
    query = urlencode((("c", ""), ("v", "0"), ("wm", ""), ("_", token)))
    return f"{_api_root(origin)}/sports-markets?{query}"


def build_events_url(
    sport_id: int,
    token: str,
    *,
    market_kind: int = 3,
    event_id: int | None = None,
    origin: str = PA_ORIGIN,
) -> str:
    if market_kind not in {0, 1, 2, 3}:
        raise ValueError("market_kind must be 0, 1, 2, or 3")
    query: list[tuple[str, str]] = [
        ("mk", str(market_kind)),
        ("sp", str(sport_id)),
        ("v", "0"),
        ("lv", "0"),
    ]
    if event_id is not None:
        query.extend((("more", "true"), ("me", str(event_id))))
    query.append(("_", token))
    return f"{_api_root(origin)}/events?{urlencode(query)}"


def create_http_session() -> Any:
    return requests.Session(impersonate="chrome", headers=build_api_headers(PA_ORIGIN))


class OriginFailover:
    """Try public mirrors in order and remain on the first working origin."""

    def __init__(self, origins: tuple[str, ...] = PA_ORIGINS) -> None:
        if not origins:
            raise ValueError("at least one origin is required")
        self.origins = origins
        self.active_index = 0

    @property
    def active_origin(self) -> str:
        return self.origins[self.active_index]

    def fetch(
        self,
        session: Any,
        url_factory: Callable[[str, str], str],
        *,
        purpose: str,
        token_factory: FreshTokenFactory,
        attempts: int,
        max_origin_age_seconds: float,
    ) -> CapturedResponse:
        origin_failures: list[dict[str, Any]] = []
        last_error = "no origin attempted"
        for index in range(self.active_index, len(self.origins)):
            origin = self.origins[index]
            try:
                capture = fetch_fresh_json(
                    session,
                    lambda token, selected=origin: url_factory(selected, token),
                    purpose=purpose,
                    token_factory=token_factory,
                    attempts=attempts,
                    max_origin_age_seconds=max_origin_age_seconds,
                    allow_missing_cf_status=(origin in ORIGINS_WITHOUT_CF_CACHE_STATUS),
                )
            except FreshnessError as exc:
                last_error = str(exc)
                origin_failures.append(
                    {"scope": "origin_failover", "origin": origin, "reason": last_error}
                )
                continue

            self.active_index = index
            capture.freshness.update(
                {
                    "origin": origin,
                    "origin_priority": index + 1,
                    "fallback_used": index > 0,
                }
            )
            capture.rejected_attempts[:0] = origin_failures
            return capture

        raise FreshnessError(
            f"All Pinnacle public origins failed for {purpose}: {last_error}"
        )


class PinnacleClient:
    """Fetch fresh prematch snapshots from Pinnacle public mirrors."""

    def __init__(
        self,
        *,
        origins: tuple[str, ...] = PA_ORIGINS,
        fresh_attempts: int = 3,
        max_origin_age_seconds: float = 5.0,
        session: Any | None = None,
    ) -> None:
        self.origins = origins
        self.fresh_attempts = fresh_attempts
        self.max_origin_age_seconds = max_origin_age_seconds
        self._session = session
        self._origins = OriginFailover(origins)
        self._tokens = FreshTokenFactory()

    def close(self) -> None:
        self._session = None

    @property
    def session(self) -> Any:
        if self._session is None:
            self._session = requests.Session(
                impersonate="chrome",
                headers=build_api_headers(self._origins.active_origin),
            )
        return self._session

    def fetch_events(self, sport_id: int, market_kind: int) -> dict[str, Any] | None:
        try:
            capture = self._origins.fetch(
                self.session,
                lambda origin, token: build_events_url(
                    sport_id,
                    token,
                    market_kind=market_kind,
                    origin=origin,
                ),
                purpose=f"market bucket {market_kind} odds for sport {sport_id}",
                token_factory=self._tokens,
                attempts=self.fresh_attempts,
                max_origin_age_seconds=self.max_origin_age_seconds,
            )
            body = capture.body
            if isinstance(body, dict):
                return body
            logger.error("Pinnacle events response is not a JSON object sport_id=%s mk=%s", sport_id, market_kind)
            return None
        except FreshnessError:
            logger.exception(
                "Pinnacle fetch failed sport_id=%s mk=%s",
                sport_id,
                market_kind,
            )
            return None
