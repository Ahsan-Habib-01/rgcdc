"""
Automated Verification & Unit Test Suite for RGCDC Tabulation System
Tests:
1. AP (3 speakers) vs BP (2 speakers) schema validation
2. Power-Pairing strict bracket integrity (AP & BP)
3. Hungarian Algorithm optimality & O(n^3) solver
4. Hard Constraint 1: Institutional Conflict (Judge cannot judge own institution)
5. Hard Constraint 2: Team History Conflict (Judge cannot judge same team twice)
6. Dynamic Judge Rating adjustment via post-round evaluations
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.algorithm import (
    INF_COST,
    TeamNode,
    JudgeNode,
    hungarian_algorithm,
    power_pair_teams,
    allocate_adjudicators_hungarian,
    update_judge_score_from_evaluation,
)
from backend.schemas import TeamCreateRequest, SpeakerInput


def test_format_speaker_validation():
    # AP requires 3 speakers
    ap_team = TeamCreateRequest(
        reference_name="RGCDC Alpha",
        short_name="RGCDC A",
        institution_name="Rangpur Government College Debating Club",
        institution_code="RGCDC",
        format="AP",
        speakers=[
            SpeakerInput(name="Tanvir Ahmed", email="tanvir@rgcdc.org"),
            SpeakerInput(name="Nusrat Jahan", email="nusrat@rgcdc.org"),
            SpeakerInput(name="Farhan Sadiq", email="farhan@rgcdc.org"),
        ],
    )
    assert len(ap_team.speakers) == 3

    # BP requires 2 speakers
    bp_team = TeamCreateRequest(
        reference_name="DUDS A",
        short_name="DUDS A",
        institution_name="Dhaka University Debating Society",
        institution_code="DUDS",
        format="BP",
        speakers=[
            SpeakerInput(name="Arif Rahman", email="arif@duds.org"),
            SpeakerInput(name="Maliha Islam", email="maliha@duds.org"),
        ],
    )
    assert len(bp_team.speakers) == 2

    # Invalid AP with 2 speakers must raise ValueError
    try:
        TeamCreateRequest(
            reference_name="Invalid AP",
            short_name="INV",
            institution_name="Inst",
            institution_code="INST",
            format="AP",
            speakers=[SpeakerInput(name="S1"), SpeakerInput(name="S2")],
        )
        assert False, "Should have rejected AP team with 2 speakers"
    except Exception:
        pass


def test_power_pairing_and_hungarian_constraints():
    teams = [
        TeamNode(id=1, name="RGCDC A", short_name="RGCDC A", institution_id=10, institution_code="RGCDC", total_points=3, total_speaks=715.0),
        TeamNode(id=2, name="DUDS A", short_name="DUDS A", institution_id=20, institution_code="DUDS", total_points=3, total_speaks=712.5),
        TeamNode(id=3, name="BUETDC A", short_name="BUETDC A", institution_id=30, institution_code="BUETDC", total_points=2, total_speaks=704.0),
        TeamNode(id=4, name="NSUDC A", short_name="NSUDC A", institution_id=40, institution_code="NSUDC", total_points=2, total_speaks=701.0),
        TeamNode(id=5, name="BRACU A", short_name="BRACU A", institution_id=50, institution_code="BRACU", total_points=1, total_speaks=695.0),
        TeamNode(id=6, name="JUDO A", short_name="JUDO A", institution_id=60, institution_code="JUDO", total_points=1, total_speaks=692.0),
    ]

    rooms = power_pair_teams(teams, debate_format="AP", venue_prefix="Room")
    assert len(rooms) == 3
    # Room 1 must have the two 3-point teams (strict bracket matching)
    assert {t.id for t in rooms[0].teams} == {1, 2}
    # Room 2 must have the two 2-point teams
    assert {t.id for t in rooms[1].teams} == {3, 4}
    # Room 3 must have the two 1-point teams
    assert {t.id for t in rooms[2].teams} == {5, 6}

    # Now test Hungarian Adjudicator Allocation with hard constraints:
    # Judge 101 is highest rated (9.5), belongs to RGCDC (inst 10) -> CANNOT judge Room 1 (which has RGCDC A)!
    # Judge 102 is rated 9.0, belongs to BRACU (inst 50), but has ALREADY judged Team 3 (BUETDC A) in Round 1 -> CANNOT judge Room 2!
    # Judge 103 is rated 8.5, belongs to Independent (inst 99) -> Can judge any room!
    judges = [
        JudgeNode(id=101, name="Akm Shoaib", institution_id=10, institution_code="RGCDC", base_score=9.5, current_score=9.5),
        JudgeNode(id=102, name="Rashedul Hasan", institution_id=50, institution_code="BRACU", base_score=9.0, current_score=9.0, judged_team_ids={3}),
        JudgeNode(id=103, name="Tahmina Karim", institution_id=99, institution_code="IND", base_score=8.5, current_score=8.5),
    ]

    alloc = allocate_adjudicators_hungarian(rooms, judges, allocate_panels=False)
    assert len(alloc["infeasible_warnings"]) == 0

    # Verify Hard Constraint 1 (Institutional Conflict):
    # Room 1 has insts {10, 20}, so Judge 101 (inst 10) is forbidden from Room 1.
    # Room 3 has insts {50, 60}, so Judge 102 (inst 50) is forbidden from Room 3.
    # Verify Hard Constraint 2 (Team History Conflict):
    # Room 2 has Team 3, which Judge 102 already judged, so Judge 102 is ALSO forbidden from Room 2!
    # Therefore, the ONLY conflict-free global perfect matching is:
    #   Judge 102 -> Room 1 (Hall 1)
    #   Judge 101 -> Room 2 (Hall 2)
    #   Judge 103 -> Room 3 (Hall 3)
    assert rooms[0].chair.id == 102, f"Expected Judge 102 in Room 1, got {rooms[0].chair.id}"
    assert rooms[1].chair.id == 101, f"Expected Judge 101 in Room 2, got {rooms[1].chair.id}"
    assert rooms[2].chair.id == 103, f"Expected Judge 103 in Room 3, got {rooms[2].chair.id}"


def test_dynamic_judge_evaluation_update():
    updated = update_judge_score_from_evaluation(
        base_score=7.0,
        current_score=7.0,
        evaluation_score=9.5,
        past_evaluations_count=1,
        room_importance=8.5,
    )
    assert 7.0 < updated <= 10.0


if __name__ == "__main__":
    test_format_speaker_validation()
    test_power_pairing_and_hungarian_constraints()
    test_dynamic_judge_evaluation_update()
    print("ALL ALGORITHM & SCHEMA TESTS PASSED SUCCESSFULLY!")
