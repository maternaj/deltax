"""Pinnacle public mirror constants and exceptions."""

from __future__ import annotations

PA_ORIGINS = (
    "https://www.p4578.com",
    "https://www.pin1188.com",
    "https://www.part567.com",
    "https://www.zephyrveil57.xyz",
)
PA_ORIGIN = PA_ORIGINS[0]
ORIGINS_WITHOUT_CF_CACHE_STATUS = {"https://www.pin1188.com"}
REQUEST_TIMEOUT_SECONDS = 20.0
FRESH_CF_STATUSES = {"MISS", "BYPASS", "DYNAMIC", "REVALIDATED"}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
SAFE_RESPONSE_HEADERS = {
    "age",
    "cache-control",
    "cf-cache-status",
    "cf-ray",
    "content-encoding",
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "server",
    "vary",
    "via",
}


class PinnacleQueryError(RuntimeError):
    """A query could not produce a usable current response."""


class FreshnessError(PinnacleQueryError):
    """Every response attempt carried known-stale cache evidence."""


class PinnacleProtocolError(PinnacleQueryError):
    """The compact response did not have the expected public shape."""


class SelectionError(PinnacleQueryError):
    """A sport, league, or event selector was missing or ambiguous."""
