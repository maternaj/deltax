#!/usr/bin/env python3
"""Print a human-readable Pinnacle probe report (corners scope + live tennis)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tests"))

from deltax.pinnacle.client import PinnacleClient
from pinnacle_probe import (
    DEFAULT_CORNER_MORE_BET_MIN,
    probe_soccer_corner_scope,
    probe_tennis_live_odds,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pinnacle exploratory probe report")
    parser.add_argument(
        "--more-bet-min",
        type=int,
        default=DEFAULT_CORNER_MORE_BET_MIN,
        help="only detail-fetch prematch soccer rows with at least this more_bet_count",
    )
    parser.add_argument(
        "--corner-limit",
        type=int,
        default=None,
        help="cap corner detail fetches (default: full gated scope)",
    )
    args = parser.parse_args()

    client = PinnacleClient(fresh_attempts=2, max_origin_age_seconds=5.0)
    try:
        corners = probe_soccer_corner_scope(
            client,
            more_bet_min=args.more_bet_min,
            max_detail_fetches=args.corner_limit,
        )
        tennis = probe_tennis_live_odds(client)
    finally:
        client.close()

    print("=== Soccer prematch corners (efficient scope) ===")
    print(f"Bulk feed mentions corners: {corners.bulk_feed_has_corners}")
    print(f"Prematch main-line events: {corners.prematch_events_total}")
    print(
        f"Detail candidates (more_bet_count>={corners.more_bet_min}): "
        f"{corners.candidate_events} "
        f"(saves {corners.detail_calls_saved_vs_full_scan} detail calls vs full scan)"
    )
    print(
        f"Detail fetches this run: {corners.detail_fetches} "
        f"→ corners with lines: {corners.corners_with_lines} "
        f"(hit rate {corners.corner_hit_rate:.0%})"
    )
    if corners.sample_corner_match:
        print(f"Sample corner match: {corners.sample_corner_match}")
        print(f"Sample templates: {', '.join(corners.sample_corner_templates)}")
    print("Leagues with corners (top 15):")
    for league, count in corners.leagues_with_corners[:15]:
        print(f"  {count:>3}  {league}")

    print("\n=== Tennis live odds (mk=2) ===")
    print(f"Live events: {tennis.live_events}")
    print(f"Live events with open lines: {tennis.live_events_with_lines}")
    if tennis.sample_live_match:
        odds = ", ".join(f"{price:.3f}" for price in tennis.sample_live_odds[:4])
        print(f"Sample: {tennis.sample_live_match} → {odds}")
    print(f"Flatten live rows (current pipeline): {tennis.flatten_live_rows}")
    if tennis.leagues_with_live:
        print("Live leagues:")
        for league, count in tennis.leagues_with_live[:10]:
            print(f"  {count:>3}  {league}")


if __name__ == "__main__":
    main()
