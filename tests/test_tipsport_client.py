"""Tipsport client session recovery tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from deltax.tipsport_client import TipsportClient, invalidate_saved_scraper


def _mock_response(status_code: int, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if payload is not None:
        response.json.return_value = payload
    return response


def test_invalidate_saved_scraper_removes_file(tmp_path: Path) -> None:
    state_file = tmp_path / "tipsport_scraper_state.json"
    state_file.write_text("{}", encoding="utf-8")

    invalidate_saved_scraper(str(state_file))

    assert not state_file.exists()


def test_fetch_recovers_from_401_by_invalidating_cache_and_bootstrapping(tmp_path: Path) -> None:
    state_file = tmp_path / "tipsport_scraper_state.json"
    state_file.write_text("{}", encoding="utf-8")

    stale_scraper = MagicMock()
    fresh_scraper = MagicMock()
    stale_scraper.get.return_value = _mock_response(401)
    fresh_scraper.get.return_value = _mock_response(200, {"ok": True})

    client = TipsportClient("https://www.tipsport.cz", state_file=str(state_file))

    with (
        patch.object(client, "_load_scraper", side_effect=[stale_scraper, None]),
        patch.object(client, "_bootstrap_scraper", return_value=fresh_scraper) as bootstrap,
        patch("deltax.tipsport_client.save_successful_scraper", return_value=True),
        patch("deltax.tipsport_client.exponential_backoff"),
    ):
        result = client.fetch("/rest/external/offer/v1/matches?allEvents=false")

    assert result == {"ok": True}
    assert not state_file.exists()
    bootstrap.assert_called_once()


def test_fetch_does_not_invalidate_cache_on_503(tmp_path: Path) -> None:
    state_file = tmp_path / "tipsport_scraper_state.json"
    state_file.write_text("{}", encoding="utf-8")

    scraper = MagicMock()
    scraper.get.return_value = _mock_response(503)

    client = TipsportClient("https://www.tipsport.cz", state_file=str(state_file), max_retries=1)

    with (
        patch.object(client, "_load_scraper", return_value=scraper),
        patch.object(client, "_bootstrap_scraper") as bootstrap,
        patch("deltax.tipsport_client.exponential_backoff"),
    ):
        result = client.fetch("/rest/external/offer/v1/matches?allEvents=false")

    assert result is None
    assert state_file.exists()
    bootstrap.assert_not_called()
