"""Pinnacle ru=Corners / ru=Bookings bulk feed tests."""

from urllib.parse import parse_qs, urlsplit

from deltax.pinnacle.client import build_relative_markets_bulk_url


def test_build_corners_bulk_url() -> None:
    url = build_relative_markets_bulk_url(29, "token123", "Corners", market_kind=1)
    params = parse_qs(urlsplit(url).query)
    assert params["ru"] == ["Corners"]
    assert params["sp"] == ["29"]
    assert params["mk"] == ["1"]
    assert params["me"] == ["0"]
    assert params["more"] == ["false"]


def test_build_bookings_bulk_url() -> None:
    url = build_relative_markets_bulk_url(29, "tok", "Bookings", market_kind=0)
    params = parse_qs(urlsplit(url).query)
    assert params["ru"] == ["Bookings"]
    assert params["mk"] == ["0"]
