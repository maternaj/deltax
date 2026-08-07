"""Pinnacle freshness and URL builder tests."""

from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from deltax.pinnacle.client import OriginFailover, build_events_url, build_sports_url
from deltax.pinnacle.freshness import FreshTokenFactory, freshness_rejection_reason, fetch_fresh_json
from deltax.pinnacle.protocol import PA_ORIGINS


class _FakeResponse:
    def __init__(self, body: object, *, status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        import json

        self.status_code = status_code
        self.headers = headers or {}
        self.content = json.dumps(body).encode("utf-8")
        self.url = ""


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _FakeResponse:
        self.urls.append(url)
        response = self.responses.pop(0)
        response.url = url
        return response


def _fresh_headers_now() -> dict[str, str]:
    value = format_datetime(datetime.now(timezone.utc), usegmt=True)
    return {
        "CF-Cache-Status": "MISS",
        "Date": value,
        "Last-Modified": value,
    }


def test_events_url_forces_full_snapshot() -> None:
    query = parse_qs(urlsplit(build_events_url(29, "123456", market_kind=1)).query)
    assert query == {
        "mk": ["1"],
        "sp": ["29"],
        "v": ["0"],
        "lv": ["0"],
        "_": ["123456"],
    }


def test_sports_url_includes_cache_buster() -> None:
    query = parse_qs(urlsplit(build_sports_url("999")).query)
    assert query["_"] == ["999"]
    assert query["v"] == ["0"]


def test_cache_busters_are_strictly_increasing() -> None:
    tokens = FreshTokenFactory(clock_ns=lambda: 100)
    assert [tokens.next(), tokens.next(), tokens.next()] == ["100", "101", "102"]


def test_freshness_gate_rejects_cloudflare_hit() -> None:
    headers = {
        "CF-Cache-Status": "HIT",
        "Date": "Tue, 04 Aug 2026 08:45:34 GMT",
        "Last-Modified": "Tue, 04 Aug 2026 08:45:34 GMT",
    }
    assert "HIT" in (freshness_rejection_reason(200, headers, 5.0) or "")


def test_fetch_retries_hit_with_new_cache_buster() -> None:
    current = _fresh_headers_now()
    hit = _FakeResponse({"l": ["stale"]}, headers={**current, "CF-Cache-Status": "HIT"})
    miss = _FakeResponse({"l": []}, headers=current)
    session = _FakeSession([hit, miss])
    tokens = FreshTokenFactory(clock_ns=lambda: 700)

    capture = fetch_fresh_json(
        session,
        lambda token: build_events_url(29, token, market_kind=1),
        purpose="prematch soccer odds",
        token_factory=tokens,
        attempts=2,
        max_origin_age_seconds=5.0,
    )

    assert capture.body == {"l": []}
    assert len(session.urls) == 2
    assert session.urls[0] != session.urls[1]


def test_origin_failover_is_ordered_and_sticky() -> None:
    current = _fresh_headers_now()
    session = _FakeSession(
        [
            _FakeResponse({}, status_code=503, headers=current),
            _FakeResponse({"sports": []}, headers=current),
            _FakeResponse({"sports": []}, headers=current),
        ]
    )
    origins = OriginFailover(PA_ORIGINS[:2])
    tokens = FreshTokenFactory(clock_ns=lambda: 900)

    first = origins.fetch(
        session,
        lambda origin, token: build_sports_url(token, origin=origin),
        purpose="menu",
        token_factory=tokens,
        attempts=1,
        max_origin_age_seconds=5.0,
    )
    second = origins.fetch(
        session,
        lambda origin, token: build_sports_url(token, origin=origin),
        purpose="menu again",
        token_factory=tokens,
        attempts=1,
        max_origin_age_seconds=5.0,
    )

    assert first.freshness["origin"] == PA_ORIGINS[1]
    assert second.freshness["origin"] == PA_ORIGINS[1]


def test_pinnacle_config_rejects_live_market_kind(tmp_path) -> None:
    import yaml

    from deltax.config import load_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "source": "pinnacle",
                "pinnacle": {
                    "sports": [{"sport_id": 29, "market_kinds": [2]}],
                },
                "drop_tiers": [{"window_seconds": 0, "drop_pct": 10}],
                "markets": {"wanted": [], "pending": [], "blacklisted": [], "blacklisted_prefixes": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not allowed for prematch-only"):
        load_config(env={"DELTAX_CONFIG_PATH": str(config_path)})
