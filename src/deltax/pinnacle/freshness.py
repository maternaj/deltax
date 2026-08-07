"""HTTP freshness gates for Pinnacle public mirror requests."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from deltax.pinnacle.protocol import (
    FRESH_CF_STATUSES,
    FreshnessError,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)


def _header(headers: Mapping[str, Any], wanted: str) -> str | None:
    wanted = wanted.casefold()
    for name, value in headers.items():
        if str(name).casefold() == wanted:
            return str(value)
    return None


class FreshTokenFactory:
    """Return strictly increasing nanosecond cache-busters within a process."""

    def __init__(self, clock_ns: Callable[[], int] = time.time_ns) -> None:
        self._clock_ns = clock_ns
        self._last = -1

    def next(self) -> str:
        candidate = int(self._clock_ns())
        if candidate <= self._last:
            candidate = self._last + 1
        self._last = candidate
        return str(candidate)


def _http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freshness_rejection_reason(
    status_code: int,
    headers: Mapping[str, Any],
    max_origin_age_seconds: float,
    *,
    received_unix_ns: int | None = None,
    allow_missing_cf_status: bool = False,
) -> str | None:
    if status_code != 200:
        return f"HTTP {status_code}"

    cf_status = (_header(headers, "cf-cache-status") or "").upper()
    if not cf_status and allow_missing_cf_status:
        if _http_date(_header(headers, "date")) is None:
            return "both CF-Cache-Status and a valid Date header are missing"
    elif cf_status not in FRESH_CF_STATUSES:
        return f"CF-Cache-Status {cf_status or 'missing'} is not fresh"

    raw_age = _header(headers, "age")
    if raw_age:
        try:
            age = float(raw_age)
        except ValueError:
            return f"invalid Age header {raw_age!r}"
        if age > 0:
            return f"Age is {age:g} seconds"

    response_date = _http_date(_header(headers, "date"))
    last_modified = _http_date(_header(headers, "last-modified"))
    if response_date is not None and received_unix_ns is not None:
        received_at = datetime.fromtimestamp(received_unix_ns / 1_000_000_000, tz=timezone.utc)
        response_age = (received_at - response_date).total_seconds()
        if response_age > max_origin_age_seconds:
            return (
                f"Date trails local receipt by {response_age:g} seconds "
                f"(limit {max_origin_age_seconds:g})"
            )
        if response_age < -max_origin_age_seconds:
            return (
                f"Date is {-response_age:g} seconds ahead of local receipt "
                f"(limit {max_origin_age_seconds:g})"
            )
    if response_date is not None and last_modified is not None:
        origin_age = max(0.0, (response_date - last_modified).total_seconds())
        if origin_age > max_origin_age_seconds:
            return (
                f"Last-Modified trails Date by {origin_age:g} seconds "
                f"(limit {max_origin_age_seconds:g})"
            )
    return None


@dataclass
class CapturedResponse:
    purpose: str
    url: str
    status_code: int
    headers: dict[str, str]
    body: Any
    raw_body: bytes
    started_unix_ns: int
    received_unix_ns: int
    started_monotonic_ns: int
    received_monotonic_ns: int
    freshness: dict[str, Any]
    rejected_attempts: list[dict[str, Any]] = field(default_factory=list)


def build_api_headers(origin: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "Origin": origin,
        "Referer": f"{origin.rstrip('/')}/en/",
        "User-Agent": USER_AGENT,
    }


def fetch_fresh_json(
    session: Any,
    url_factory: Callable[[str], str],
    *,
    purpose: str,
    token_factory: FreshTokenFactory,
    attempts: int,
    max_origin_age_seconds: float,
    allow_missing_cf_status: bool = False,
) -> CapturedResponse:
    rejected: list[dict[str, Any]] = []
    last_reason = "no request attempted"
    for attempt_number in range(1, attempts + 1):
        token = token_factory.next()
        url = url_factory(token)
        started_unix_ns = time.time_ns()
        started_monotonic_ns = time.monotonic_ns()
        try:
            parts = urlsplit(url)
            request_origin = f"{parts.scheme}://{parts.netloc}"
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers=build_api_headers(request_origin),
            )
        except Exception as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
            rejected.append({"attempt": attempt_number, "url": url, "reason": last_reason})
            continue
        received_unix_ns = time.time_ns()
        received_monotonic_ns = time.monotonic_ns()
        status_code = int(response.status_code)
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        reason = freshness_rejection_reason(
            status_code,
            headers,
            max_origin_age_seconds,
            received_unix_ns=received_unix_ns,
            allow_missing_cf_status=allow_missing_cf_status,
        )
        if reason is not None:
            last_reason = reason
            rejected.append({"attempt": attempt_number, "url": url, "reason": reason})
            continue
        raw_body = bytes(response.content)
        try:
            body = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            last_reason = f"invalid JSON: {exc}"
            rejected.append({"attempt": attempt_number, "url": url, "reason": last_reason})
            continue
        response_url = str(getattr(response, "url", None) or url)
        return CapturedResponse(
            purpose=purpose,
            url=response_url,
            status_code=status_code,
            headers=headers,
            body=body,
            raw_body=raw_body,
            started_unix_ns=started_unix_ns,
            received_unix_ns=received_unix_ns,
            started_monotonic_ns=started_monotonic_ns,
            received_monotonic_ns=received_monotonic_ns,
            freshness={
                "accepted": True,
                "cache_buster": token,
                "cf_cache_status": (_header(headers, "cf-cache-status") or "").upper(),
                "cache_validation": (
                    "explicit_cf_cache_status"
                    if _header(headers, "cf-cache-status")
                    else "current_date_and_unique_url"
                ),
                "age_seconds": _header(headers, "age"),
                "response_date": _header(headers, "date"),
                "last_modified": _header(headers, "last-modified"),
                "requested_full_snapshot": True,
                "requested_versions": {"v": 0, "lv": 0},
            },
            rejected_attempts=rejected,
        )
    raise FreshnessError(
        f"Could not obtain fresh {purpose} after {attempts} attempts: {last_reason}"
    )
