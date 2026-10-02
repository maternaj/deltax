"""Pinnacle corner settlement — grading and FS match-link tests."""

from datetime import datetime, timedelta, timezone

from deltax.settle.constants import RESULT_LOSS, RESULT_UNKNOWN, RESULT_VOID, RESULT_WIN
from deltax.settle.pinnacle.corners import (
    CornerCounts,
    grade_corner_alert,
    is_bookings_alert,
    is_corners_alert,
    normalize_team_key,
    strip_relative_unit_suffix,
)
from deltax.settle.matching.config import FsMatchingConfig
from deltax.settle.matching.teams import name_similarity
from deltax.settle.pinnacle.fs_match import (
    FsFinishedMatch,
    LinkedFsMatch,
    build_alert_match_key,
    link_alert_to_fs_match,
)

MATCHING = FsMatchingConfig(
    min_match_score=75,
    min_second_best_gap=10,
    kickoff_window_minutes=180,
    time_penalty_per_minute=0.05,
    load_window_hours=3,
    team_aliases={},
)

KICKOFF = datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc)


def test_strip_corners_suffix() -> None:
    assert strip_relative_unit_suffix("Coritiba (Corners)") == "Coritiba"
    assert strip_relative_unit_suffix("Team (Bookings)") == "Team"


def test_normalize_team_key() -> None:
    assert normalize_team_key("Coritiba (Corners)") == normalize_team_key("Coritiba")


def test_is_corners_vs_bookings_alert() -> None:
    assert is_corners_alert(
        home_participant="A (Corners)",
        visiting_participant="B (Corners)",
        match_name="A (Corners) - B (Corners)",
    )
    assert not is_corners_alert(
        home_participant="A (Bookings)",
        visiting_participant="B (Bookings)",
        match_name="A (Bookings) - B (Bookings)",
    )
    assert is_bookings_alert(
        home_participant="A (Bookings)",
        visiting_participant="B (Bookings)",
        match_name=None,
    )


def test_grade_total_over_under() -> None:
    counts = CornerCounts(home=6, away=5)
    assert (
        grade_corner_alert(
            my_selection_id="29-0-TOTAL-OVER",
            opp_name="Over 10.5",
            opp_number="10.5",
            counts=counts,
        )
        == RESULT_WIN
    )
    assert (
        grade_corner_alert(
            my_selection_id="29-0-TOTAL-UNDER",
            opp_name="Under 10.5",
            opp_number="10.5",
            counts=counts,
        )
        == RESULT_LOSS
    )
    assert (
        grade_corner_alert(
            my_selection_id="29-0-TOTAL-OVER",
            opp_name="Over 11",
            opp_number="11",
            counts=counts,
        )
        == RESULT_VOID
    )


def test_grade_spread_home() -> None:
    counts = CornerCounts(home=5, away=4)
    assert (
        grade_corner_alert(
            my_selection_id="29-0-SPREAD-HOME",
            opp_name="Home +0.5",
            opp_number="+0.5",
            counts=counts,
        )
        == RESULT_WIN
    )
    assert (
        grade_corner_alert(
            my_selection_id="29-0-SPREAD-AWAY",
            opp_name="Away +1.5",
            opp_number="+1.5",
            counts=counts,
        )
        == RESULT_WIN
    )


def test_grade_moneyline() -> None:
    counts = CornerCounts(home=7, away=3)
    assert (
        grade_corner_alert(
            my_selection_id="29-0-MONEYLINE-HOME",
            opp_name="Home",
            opp_number=None,
            counts=counts,
        )
        == RESULT_WIN
    )
    assert (
        grade_corner_alert(
            my_selection_id="29-0-MONEYLINE-DRAW",
            opp_name="Draw",
            opp_number=None,
            counts=counts,
        )
        == RESULT_LOSS
    )


def test_grade_quarter_line_unknown() -> None:
    assert (
        grade_corner_alert(
            my_selection_id="29-0-TOTAL-OVER",
            opp_name="Over 10-10.5",
            opp_number=None,
            counts=CornerCounts(home=5, away=6),
        )
        == RESULT_UNKNOWN
    )


def test_link_alert_to_fs_match() -> None:
    alert = build_alert_match_key(
        home_participant="Coritiba (Corners)",
        visiting_participant="Chapecoense (Corners)",
        kickoff_at=KICKOFF,
    )
    candidates = [
        FsFinishedMatch(
            match_id="fs1",
            match_date=KICKOFF + timedelta(minutes=5),
            home_team="Coritiba",
            away_team="Chapecoense",
            corners=CornerCounts(home=4, away=3),
        ),
        FsFinishedMatch(
            match_id="fs2",
            match_date=KICKOFF,
            home_team="Other FC",
            away_team="Another FC",
            corners=CornerCounts(home=1, away=1),
        ),
    ]
    linked = link_alert_to_fs_match(alert, candidates, matching=MATCHING)
    assert linked is not None
    assert isinstance(linked, LinkedFsMatch)
    assert linked.match_id == "fs1"
    assert linked.corners == CornerCounts(home=4, away=3)
    assert linked.corners.total == 7


def test_link_alert_swapped_home_away() -> None:
    alert = build_alert_match_key(
        home_participant="Team A (Corners)",
        visiting_participant="Team B (Corners)",
        kickoff_at=KICKOFF,
    )
    candidates = [
        FsFinishedMatch(
            match_id="fs-swapped",
            match_date=KICKOFF,
            home_team="Team B",
            away_team="Team A",
            corners=CornerCounts(home=2, away=5),
        ),
    ]
    linked = link_alert_to_fs_match(alert, candidates, matching=MATCHING)
    assert linked is not None
    assert linked.match_id == "fs-swapped"
    # FS lists Team B as home (2 corners) but alert home is Team A (5 corners).
    assert linked.corners == CornerCounts(home=5, away=2)


def test_name_similarity_pumas_unam() -> None:
    assert name_similarity("Pumas UNAM", "UNAM Pumas") >= 90


def test_link_alert_fuzzy_pumas_unam() -> None:
    alert = build_alert_match_key(
        home_participant="Pumas UNAM (Corners)",
        visiting_participant="Atletico San Luis (Corners)",
        kickoff_at=KICKOFF,
    )
    candidates = [
        FsFinishedMatch(
            match_id="WrElsNRO",
            match_date=KICKOFF,
            home_team="UNAM Pumas",
            away_team="Atl. San Luis",
            corners=CornerCounts(home=11, away=2),
        ),
    ]
    linked = link_alert_to_fs_match(alert, candidates, matching=MATCHING)
    assert linked is not None
    assert linked.match_id == "WrElsNRO"
    assert linked.corners == CornerCounts(home=11, away=2)


def test_link_alert_rejects_ambiguous_match() -> None:
    alert = build_alert_match_key(
        home_participant="Team A (Corners)",
        visiting_participant="Team B (Corners)",
        kickoff_at=KICKOFF,
    )
    candidates = [
        FsFinishedMatch(
            match_id="fs-a",
            match_date=KICKOFF,
            home_team="Team A",
            away_team="Team B",
            corners=CornerCounts(home=3, away=2),
        ),
        FsFinishedMatch(
            match_id="fs-b",
            match_date=KICKOFF + timedelta(minutes=5),
            home_team="Team A",
            away_team="Team B",
            corners=CornerCounts(home=1, away=1),
        ),
    ]
    linked = link_alert_to_fs_match(alert, candidates, matching=MATCHING)
    assert linked is None


def test_grade_moneyline_uses_oriented_swapped_counts() -> None:
    counts = CornerCounts(home=5, away=2)
    assert (
        grade_corner_alert(
            my_selection_id="29-0-MONEYLINE-HOME",
            opp_name="Home",
            opp_number=None,
            counts=counts,
        )
        == RESULT_WIN
    )
    assert (
        grade_corner_alert(
            my_selection_id="29-0-MONEYLINE-AWAY",
            opp_name="Away",
            opp_number=None,
            counts=counts,
        )
        == RESULT_LOSS
    )
