#!/usr/bin/env python3
"""List Pinnacle sports from the live menu + probe common prematch sport IDs."""

from __future__ import annotations

import argparse

from deltax.pinnacle.client import OriginFailover, PinnacleClient, build_events_url, build_sports_url, create_http_session
from deltax.pinnacle.freshness import FreshTokenFactory
from deltax.pinnacle.parser import normalize_sport_feed, parse_sports_menu, sport_by_id

COMMON_SPORT_IDS = (
    (29, "Soccer"),
    (4, "Basketball"),
    (33, "Tennis"),
    (19, "Hockey"),
    (12, "E Sports"),
    (22, "Mixed Martial Arts"),
    (15, "Football"),
    (6, "Baseball"),
    (8, "Cricket"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pinnacle sport discovery helper")
    parser.add_argument("--probe-prematch", action="store_true", help="also probe mk=0 event counts")
    args = parser.parse_args()

    session = create_http_session()
    origins = OriginFailover()
    tokens = FreshTokenFactory()
    capture = origins.fetch(
        session,
        lambda origin, token: build_sports_url(token, origin=origin),
        purpose="sports menu",
        token_factory=tokens,
        attempts=3,
        max_origin_age_seconds=5.0,
    )
    menu = parse_sports_menu(capture.body)
    print(f"Live menu ({capture.freshness.get('origin')}) — sports with live activity now:")
    print(f"{'ID':>4}  {'Sport':<28}  live_events  live_markets")
    for row in sorted(menu, key=lambda x: (-x["live_event_count"], x["sport_name"])):
        print(
            f"{row['sport_id']:>4}  {row['sport_name']:<28}  "
            f"{row['live_event_count']:>11}  {row['live_market_count']:>12}"
        )

    if args.probe_prematch:
        client = PinnacleClient(fresh_attempts=2, max_origin_age_seconds=5.0)
        print("\nPrematch mk=0 probe (common IDs):")
        print(f"{'ID':>4}  {'Sport':<22}  events  leagues")
        for sport_id, name in COMMON_SPORT_IDS:
            body = client.fetch_events(sport_id, 0)
            if body is None:
                print(f"{sport_id:>4}  {name:<22}  FAIL")
                continue
            try:
                sport = sport_by_id(normalize_sport_feed(body), sport_id)
                if sport is None:
                    print(f"{sport_id:>4}  {name:<22}  empty")
                    continue
                events = sum(len(lg.get("events") or []) for lg in sport.get("leagues") or [])
                leagues = len(sport.get("leagues") or [])
                if events:
                    print(f"{sport_id:>4}  {name:<22}  {events:>6}  {leagues:>7}")
            except Exception as exc:
                print(f"{sport_id:>4}  {name:<22}  error: {exc}")
        client.close()
    session.close()


if __name__ == "__main__":
    main()
