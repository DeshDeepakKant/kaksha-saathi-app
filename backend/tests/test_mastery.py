"""Mastery engine rules — the core guarantee: status is deterministic and explainable."""
from datetime import datetime, timedelta, timezone

from app.services.content import get_content
from app.services.mastery import Ev, find_gap, status_for, prerequisite_closure

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def ev(result, source="teacher_tap", days=0, conf=1.0, i=0):
    return Ev(result=result, source=source, confidence=conf, at=NOW - timedelta(days=days), id=i)


def test_no_evidence_is_not_started():
    assert status_for([], NOW).status == "not_started"


def test_single_voice_clip_is_not_enough():
    r = status_for([ev("correct", "class_voice")], NOW)
    assert r.status == "needs_practice"  # one clip is not yet an "on track" decision
    assert r.confidence < 0.6


def test_two_confirmed_corrects_on_track():
    r = status_for([ev("correct", i=2), ev("correct", days=1, i=1)], NOW)
    assert r.status == "on_track"
    assert r.score == 1.0


def test_wrong_then_wrong_needs_intervention():
    r = status_for([ev("incorrect", i=2), ev("incorrect", days=2, i=1)], NOW)
    assert r.status == "needs_intervention"


def test_home_only_evidence_capped_at_needs_practice():
    r = status_for([ev("correct", "home_voice", i=3), ev("correct", "home_voice", days=1, i=2),
                    ev("correct", "home_voice", days=2, i=1)], NOW)
    assert r.status == "needs_practice"
    assert r.ceiling_applied


def test_home_plus_teacher_can_reach_on_track():
    r = status_for([ev("correct", "teacher_tap", i=3), ev("correct", "home_voice", days=1, i=2),
                    ev("correct", "home_voice", days=2, i=1)], NOW)
    assert r.status == "on_track"


def test_two_recent_wrongs_cap_status():
    # historically correct, then two recent failures (an intervention happened)
    r = status_for([ev("incorrect", days=1, i=3), ev("incorrect", i=2), ev("correct", days=5, i=1)], NOW)
    assert r.status in ("needs_practice", "needs_intervention")


def test_improving_flag_after_wrong_then_rights():
    r = status_for([ev("incorrect", days=20, i=1), ev("correct", days=10, i=2),
                    ev("correct", days=5, i=3), ev("correct", i=4)], NOW)
    assert r.improving


def test_unattempted_excluded():
    r = status_for([ev("unattempted", i=1), ev("unattempted", i=2)], NOW)
    assert r.status == "not_started"


def test_gap_walks_to_prerequisite_root():
    content = get_content()
    # fails borrowing and no-borrow; place value is fine
    statuses = {"N.G2.sub_2digit_borrow": "needs_intervention",
                "N.G2.sub_2digit_no_borrow": "needs_intervention",
                "N.G2.place_value_99": "on_track"}
    g = find_gap(content, statuses)
    assert g is not None
    assert g.checkpoint_id == "N.G2.sub_2digit_no_borrow"
    assert g.reason == "needs_intervention_root"


def test_gap_direct_when_prereqs_ok():
    content = get_content()
    statuses = {"N.G2.sub_2digit_borrow": "needs_intervention",
                "N.G2.sub_2digit_no_borrow": "on_track", "N.G2.place_value_99": "on_track",
                "N.G1.sub_single": "on_track"}
    g = find_gap(content, statuses)
    assert g.checkpoint_id == "N.G2.sub_2digit_borrow"
    assert g.reason == "direct"


def test_no_gap_when_on_track():
    assert find_gap(get_content(), {"N.G1.add_single": "on_track"}) is None


def test_prerequisite_closure_nearest_first():
    closure = prerequisite_closure(get_content(), "N.G2.sub_2digit_borrow")
    assert closure[0] == "N.G2.sub_2digit_no_borrow"
    assert "N.G1.sub_single" in closure
