"""Shared Pinnacle compact feed fixtures for tests."""

from __future__ import annotations

from typing import Any


def prematch_period() -> list[Any]:
    return [
        [[0.5, -0.5, "0.5", "1.95", "1.95", 1, 0, 9001, 0, 100.0, 1]],
        [["2.5", 2.5, "1.90", "1.95", 9002, 0, 100.0, 1]],
        ["2.50", "2.80", "3.20", 9003, 0, 100.0, 1],
        0,
        "Match",
        1,
        0,
        0,
        [0, 0],
        7,
        [0, 0],
        [0, 0],
        0,
    ]


def prematch_event(
    event_id: int = 999001,
    home: str = "Arsenal",
    away: str = "Chelsea",
) -> list[Any]:
    return [
        event_id,
        home,
        away,
        7,
        1_785_833_000_000,
        0,
        0,
        8,
        {"0": prematch_period()},
        [0, 0],
        [0, 0],
        [0, 1],
        0,
        None,
        None,
        None,
        None,
        "O",
        0,
        0,
        0,
        18,
        2,
        0,
        home,
        away,
        0,
        "Match",
        None,
        0,
        0,
    ]


def live_event(event_id: int = 999002) -> list[Any]:
    row = prematch_event(event_id=event_id, home="Live Home", away="Live Away")
    row[5] = 1
    row[6] = 1
    row[15] = "45'"
    row[16] = "1st Half"
    return row


def prematch_soccer_body() -> dict[str, Any]:
    return {
        "u": None,
        "l": None,
        "n": [
            [
                29,
                "Soccer",
                [
                    [
                        1980,
                        "England - Premier League",
                        [prematch_event()],
                        None,
                        "England - Premier League",
                        0,
                        None,
                    ]
                ],
                1_785_833_100_000,
                0,
                None,
                [],
                1,
            ]
        ],
        "e": None,
        "e1": None,
    }


def mixed_live_and_prematch_body() -> dict[str, Any]:
    return {
        "u": None,
        "l": [
            [
                29,
                "Soccer",
                [
                    [
                        1980,
                        "England - Premier League",
                        [live_event()],
                        None,
                        "England - Premier League",
                        0,
                        None,
                    ]
                ],
                1_785_833_100_000,
                0,
                None,
                [],
                1,
            ]
        ],
        "n": prematch_soccer_body()["n"],
        "e": None,
        "e1": None,
    }
