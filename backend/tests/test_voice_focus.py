"""Voice session at the child's level (docs/voice_focus_contract.md sections 1-3).

The plan (which stage, from which evidence), the session's phases (placement, warm-up, focus, stretch,
support), the outcome stored in the report, the teacher's home-focus override and the parent preview.
The engine's other seams are the voice-session test fakes; children live in a sandbox school.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import (
    Attendance, Child, Classroom, Evidence, HomeFocus, LevelCheck, ParentAccount, School, Teacher, VoiceSession,
)
from app.seed import DEMO_CODE
from app.services import ledger, voice_plan
from app.services import voice_session as vse
from app.services.voice_types import STAGE_CHECKPOINTS
from tests.test_voice_session import (  # noqa: F401 - fixtures and helpers of the voice-session tests
    LEVEL_AT, NOPE, RIGHT, _fail_item, _start, _turn, bare_kid, clock, fakes, kid, make_kid, sandbox,
)


def _plan(cid, lang="hi", now=None):
    with SessionLocal() as db:
        child = db.get(Child, cid)
        syl = vse._syllabus(db, db.get(Classroom, child.class_id), lang)
        return voice_plan.plan_session(db, child, lang, syl, now=now or datetime(2026, 10, 29, 9, tzinfo=timezone.utc))


def _ev(sandbox, cid, cp, result, days_ago=2, source="teacher_tap"):
    with SessionLocal() as db:
        db.add(Evidence(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=cid, checkpoint_id=cp,
                        result=result, source=source, confidence=1.0, status="confirmed",
                        at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
        db.commit()


def _absent_today(sandbox, cid):
    with SessionLocal() as db:
        db.add(Attendance(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=cid,
                          day=ledger.school_today(), present=False))
        db.commit()


def _end(client, h, s):
    r = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={"reason": "parent_stop"})
    assert r.status_code == 200, r.text
    return r.json()


def _answer_all(client, h, s, t, n, answer=RIGHT, advance=None, clock=None):
    for _ in range(n):
        if advance:
            clock.advance(advance)
        t = _turn(client, h, s, t["next_item"]["id"], answer)
    return t


# ------------------------------------------------------------------ 1. the plan
@pytest.mark.parametrize("key,focus,warm,stretch,diff", [
    ("beginner", "letter", None, "word_build", 1), ("letter", "word_build", "letter", "word_read", 1),
    ("word", "sentence_build", "word_read", "reading", 1), ("sentence", "reading", "sentence_build", None, 1),
    ("story", "reading", "sentence_build", None, 3)])
def test_level_check_maps_to_the_next_step(sandbox, key, focus, warm, stretch, diff):
    _, cid = make_kid(sandbox, {"literacy": key})
    p = _plan(cid)
    assert (p["source"], p["focus_stage"], p["warmup_stage"], p["stretch_stage"], p["start_difficulty"]) == (
        "level_check", focus, warm, stretch, diff)
    assert p["placement"] is False and p["subject"] == "literacy" and p["v"] == 1
    assert "Level check on 9 Oct" in p["reason_en"] and "9 अक्टूबर" in p["reason_hi"]
    assert p["focus_checkpoints"] and set(p["focus_checkpoints"]) <= set(STAGE_CHECKPOINTS[focus])
    assert len(p["focus_checkpoints"]) <= 4


def test_old_level_check_and_the_other_subject_are_ignored(sandbox):
    _, cid = make_kid(sandbox, {"english": "story"})
    with SessionLocal() as db:
        db.add(LevelCheck(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=cid,
                          subject="literacy", level_index=2, level_key="sentence", at=LEVEL_AT - timedelta(days=40)))
        db.commit()
    assert _plan(cid)["source"] == "placement"  # 60 days old by the clock: too old
    assert _plan(cid, "en")["focus_stage"] == "reading"  # English check counts for English only


def test_placement_when_there_is_no_evidence(bare_kid):
    _, cid = bare_kid
    p = _plan(cid)
    assert p["source"] == "placement" and p["placement"] is True and p["focus_stage"] == "word_read"
    assert p["warmup_stage"] == "word_build" and p["stretch_stage"] == "sentence_build"
    assert p["override"] is None and p["based_on_session"] is None and p["target_sounds"] == []


def test_board_gap_then_mastery(sandbox, bare_kid):
    _, cid = bare_kid
    for d in (5, 3, 1):
        _ev(sandbox, cid, "L.G1.matra_basic", "incorrect", d)
    p = _plan(cid)
    assert p["source"] == "board_gap" and p["focus_stage"] == "word_build"
    assert p["focus_checkpoints"][0] == "L.G1.matra_basic" and "Class board" in p["reason_en"]
    _absent_today(sandbox, cid)  # absent today: not grouped on the board, so the records decide
    p = _plan(cid)
    assert p["source"] == "mastery" and p["focus_stage"] == "letter"  # letters were never assessed


def test_mastery_returns_the_lowest_stage_not_secure(sandbox, bare_kid):
    _, cid = bare_kid
    _absent_today(sandbox, cid)
    for cp in STAGE_CHECKPOINTS["letter"]:
        for d in (4, 3, 2):
            _ev(sandbox, cid, cp, "correct", d)
    p = _plan(cid)
    assert p["source"] == "mastery" and p["focus_stage"] == "word_build"  # not one below, as start_stage was


def test_level_check_beats_board_gap(sandbox):
    _, cid = make_kid(sandbox, {"literacy": "word"})
    for d in (5, 3, 1):
        _ev(sandbox, cid, "L.G1.matra_basic", "incorrect", d)
    assert _plan(cid)["source"] == "level_check"


def _ended_session(cid, school_id, *, lang="hi", next_stage="word_read", at=datetime(2026, 10, 20, 9),
                   weak=("क", "म")):
    with SessionLocal() as db:
        vs = VoiceSession(school_id=school_id, child_id=cid, lang=lang, status="ended", stage="word_read",
                          started_at=at, ended_at=at + timedelta(minutes=20), state={"weak_sounds": list(weak)},
                          report={"outcome": {"focus_stage": "word_build", "focus_accuracy": 0.9, "mastered": True,
                                              "next_focus_stage": next_stage, "next_reason_en": "Mastered.",
                                              "next_reason_hi": "पक्का हुआ।"},
                                  "plan": {"source": "level_check"}})
        db.add(vs)
        db.commit()
        return vs.id


def test_last_session_wins_only_when_newer_than_the_evidence(sandbox):
    _, cid = make_kid(sandbox, {"literacy": "beginner"})
    old = _ended_session(cid, sandbox["school_id"], at=LEVEL_AT - timedelta(days=3))
    p = _plan(cid)
    assert p["source"] == "level_check" and p["based_on_session"] is None
    assert p["target_sounds"] == ["म", "क"]  # the last session's weak sounds, most recent first
    sid = _ended_session(cid, sandbox["school_id"], weak=("ि",))
    p = _plan(cid)
    assert (p["source"], p["focus_stage"], p["based_on_session"]) == ("last_session", "word_read", sid)
    assert p["reason_en"].startswith("Last session on 20 Oct") and p["target_sounds"] == ["ि"]
    assert p["warmup_stage"] == "word_build" and old != sid
    assert _plan(cid, "en")["source"] == "placement"  # a Hindi session says nothing about English


def test_teacher_override_beats_everything(sandbox):
    _, cid = make_kid(sandbox, {"literacy": "story"})
    _ended_session(cid, sandbox["school_id"])
    with SessionLocal() as db:
        db.add(HomeFocus(school_id=sandbox["school_id"], child_id=cid, subject="literacy", stage="letter",
                         checkpoint_ids=["L.G1.swar"], note="Swar this week", until=date(2026, 11, 5)))
        db.add(HomeFocus(school_id=sandbox["school_id"], child_id=cid, subject="literacy", stage="reading",
                         until=date(2026, 10, 1)))  # expired
        db.commit()
    p = _plan(cid)
    assert p["source"] == "teacher_override" and p["focus_stage"] == "letter" and p["based_on_session"] is None
    assert p["focus_checkpoints"] == ["L.G1.swar"] and p["override"]["note"] == "Swar this week"
    assert p["override"]["until"] == "2026-11-05" and "5 Nov" in p["reason_en"] and "Swar" in p["reason_en"]
    assert _plan(cid, now=datetime(2026, 11, 6, 9, tzinfo=timezone.utc))["source"] == "last_session"  # ran out


# ------------------------------------------------------------------ 2. the session
def test_placement_probes_up_to_the_top(client, bare_kid, fakes, clock):
    h, cid = bare_kid
    s = _start(client, h)
    assert (s["phase"], s["stage"], s["attempts_left"]) == ("placement", "word_read", 2)
    t = _turn(client, h, s, s["item"]["id"], NOPE)
    assert t["attempts_left"] == 1 and t["attempt"] == 2  # at most 2 tries per placement item
    t = _turn(client, h, s, t["next_item"]["id"], RIGHT)  # right on the second try still passes
    t = _turn(client, h, s, t["next_item"]["id"], RIGHT)
    assert t["stage"] == "sentence_build" and t["phase"] == "placement"
    t = _answer_all(client, h, s, t, 2)
    assert t["stage"] == "reading" and t["phase"] == "placement"
    t = _answer_all(client, h, s, t, 2)  # the ladder ends: everything passed -> reading
    assert (t["phase"], t["stage"], t["focus_stage"]) == ("warmup", "sentence_build", "reading")
    plan = client.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()["session"]["plan"]
    assert plan["source"] == "placement" and plan["focus_stage"] == "reading" and plan["stretch_stage"] is None
    assert plan["reason_en"].startswith("Saathi checked the level first")
    assert [p["stage"] for p in plan["probes"]] == ["word_read", "sentence_build", "reading"]
    rep = _end(client, h, s)
    assert rep["plan"]["source"] == "placement" and rep["outcome"]["next_focus_stage"] == "reading"


def test_placement_probes_down_and_stops_when_it_reverses(client, bare_kid, fakes, clock):
    h, cid = bare_kid
    s = _start(client, h)
    t = {"next_item": s["item"]}
    for stage in ("word_read", "word_read", "word_build", "word_build"):
        assert t["next_item"]["stage"] == stage
        t = _turn(client, h, s, t["next_item"]["id"], NOPE)
        t = _turn(client, h, s, t["next_item"]["id"], NOPE)
        assert t["item_result"] == "failed"
    assert t["stage"] == "letter" and t["phase"] == "placement"
    t = _answer_all(client, h, s, t, 2)  # letters pass: the direction reverses -> focus word_build
    assert (t["phase"], t["stage"], t["focus_stage"]) == ("warmup", "letter", "word_build")
    with SessionLocal() as db:  # placement answers are evidence like any other
        assert db.scalar(select(func.count()).select_from(Evidence).where(
            Evidence.child_id == cid, Evidence.source == "home_voice")) == 6
    rep = _end(client, h, s)
    assert rep["outcome"]["focus_stage"] == "word_build" and rep["outcome"]["next_focus_stage"] == "word_build"


def test_unfinished_placement_is_found_again_next_time(client, bare_kid, fakes, clock):
    h, cid = bare_kid
    s = _start(client, h)
    _turn(client, h, s, s["item"]["id"], RIGHT)
    rep = _end(client, h, s)
    assert rep["outcome"]["next_focus_stage"] is None
    assert client.get("/v1/parent/voice/plan", headers=h).json()["source"] == "placement"


def test_mastery_moves_up_once_only(client, kid, fakes, clock):
    h, cid = kid  # focus letter
    s = _start(client, h)
    t = {"next_item": s["item"]}
    t = _answer_all(client, h, s, t, 7)
    assert t["stage"] == "letter" and not t["stage_changed"]
    t = _answer_all(client, h, s, t, 1)  # 8 judged focus items, all right: mastered
    assert t["stage_changed"] and t["stage"] == t["focus_stage"] == "word_build"
    assert "[stage_up:1]" in t["tutor"]["text"]
    t = _answer_all(client, h, s, t, 12)
    assert t["stage"] == t["focus_stage"] == "word_build" and not t["stage_changed"]  # never a second move
    rep = _end(client, h, s)
    oc = rep["outcome"]
    assert (oc["focus_stage"], oc["focus_items"], oc["focus_accuracy"], oc["mastered"], oc["moved_up_to"]) == (
        "letter", 8, 1.0, True, "word_build")
    assert oc["next_focus_stage"] == "word_build" and oc["next_reason_en"] and oc["next_reason_hi"]
    assert rep["plan"]["focus_stage"] == "letter"
    row = next(r for r in client.get("/v1/parent/voice/sessions", headers=h).json() if r["id"] == s["id"])
    assert (row["focus_stage"], row["mastered"], row["next_focus_stage"], row["plan_source"]) == (
        "letter", True, "word_build", "level_check")


def test_mastery_needs_80_percent_of_the_last_10(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    t = _fail_item(client, h, s, s["item"])
    t = _fail_item(client, h, s, t["next_item"])
    t = _answer_all(client, h, s, t, 6)  # 6 of 8
    assert t["focus_stage"] == "letter"
    t = _answer_all(client, h, s, t, 1)  # 7 of 9
    assert t["focus_stage"] == "letter"
    t = _answer_all(client, h, s, t, 1)  # 8 of 10
    assert t["focus_stage"] == "word_build" and t["stage_changed"]


def test_stretch_at_the_end_then_back_to_focus(client, kid, fakes, clock):
    h, cid = kid  # focus letter, stretch word_build
    s = _start(client, h)
    item = s["item"]
    for _ in range(9):  # silence uses no try and logs nothing, but the time runs
        clock.advance(170)
        _turn(client, h, s, item["id"], "")
    clock.advance(170)
    t = _turn(client, h, s, item["id"], RIGHT)  # 100 s left, focus not mastered
    assert (t["phase"], t["stage"], t["focus_stage"]) == ("stretch", "word_build", "letter")
    assert t["next_item"]["difficulty"] == 1
    t = _answer_all(client, h, s, t, 3, advance=5, clock=clock)
    assert (t["phase"], t["stage"]) == ("focus", "letter") and t["stage_changed"]
    t = _answer_all(client, h, s, t, 1, advance=5, clock=clock)
    assert t["phase"] == "focus"  # one stretch a session
    oc = _end(client, h, s)["outcome"]
    assert (oc["stretch_stage"], oc["stretch_items"], oc["stretch_correct"]) == ("word_build", 3, 3)
    assert oc["mastered"] is False and oc["next_focus_stage"] == "word_build"  # every stretch item right
    # tracking: the next plan starts from this outcome (newer than the level check)
    p = client.get("/v1/parent/voice/plan", headers=h).json()
    assert (p["source"], p["focus_stage"], p["based_on_session"]) == ("last_session", "word_build", s["id"])


def test_a_missed_stretch_keeps_the_focus(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    item = s["item"]
    for _ in range(10):
        clock.advance(170)
        _turn(client, h, s, item["id"], "")
    t = _turn(client, h, s, item["id"], RIGHT)
    assert t["phase"] == "stretch"
    t = _fail_item(client, h, s, t["next_item"])
    oc = _end(client, h, s)["outcome"]
    assert oc["stretch_items"] == 1 and oc["stretch_correct"] == 0 and oc["next_focus_stage"] == "letter"


def test_session_uses_the_plan_checkpoints_and_target_sounds(client, sandbox, fakes, clock):
    h, cid = make_kid(sandbox, {"literacy": "beginner"})
    _ended_session(cid, sandbox["school_id"], next_stage="letter", weak=("श", "ष"))
    s = _start(client, h)
    assert s["plan"]["source"] == "last_session"
    call = fakes.gen_calls[-1]
    assert call["weak_sounds"][-2:] == ["श", "ष"]  # the last session's weak sounds, most recent last
    assert [t["checkpoint_id"] for t in call["topics"] if not t["custom"]] == s["plan"]["focus_checkpoints"]


# ------------------------------------------------------------------ 3. teacher override and preview
@pytest.fixture
def th(sandbox):
    return {"Authorization": f"Bearer {make_token(str(sandbox['teacher_id']), 'teacher')}"}


def test_home_focus_crud_and_session(client, sandbox, th, fakes, clock):
    h, cid = make_kid(sandbox, {"literacy": "beginner"})
    url = f"/v1/children/{cid}/home_focus"
    g = client.get(url, headers=th, params={"subject": "literacy"})
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["subject"] == "literacy" and body["override"] is None and body["history"] == []
    assert body["plan"]["source"] == "level_check" and body["plan"]["focus_stage"] == "letter"
    r = client.put(url, headers=th, json={"subject": "literacy", "stage": "word_read",
                                          "checkpoint_ids": ["L.G2.all_matras"], "note": "Matra words", "days": 14})
    assert r.status_code == 200, r.text
    ov = r.json()["override"]
    assert ov["stage"] == "word_read" and ov["checkpoint_ids"] == ["L.G2.all_matras"] and ov["note"] == "Matra words"
    assert ov["until"] == (ledger.school_today() + timedelta(days=14)).isoformat()
    assert r.json()["plan"]["source"] == "teacher_override" and r.json()["plan"]["focus_stage"] == "word_read"
    r2 = client.put(url, headers=th, json={"subject": "literacy", "stage": "letter"})  # replaces it
    assert r2.json()["override"]["stage"] == "letter" and r2.json()["override"]["id"] != ov["id"]
    with SessionLocal() as db:
        rows = list(db.scalars(select(HomeFocus).where(HomeFocus.child_id == cid)))
        assert len(rows) == 2 and sum(r.active for r in rows) == 1
        assert next(r for r in rows if r.active).until == ledger.school_today() + timedelta(days=7)
    client.put(url, headers=th, json={"subject": "literacy", "stage": "word_read", "checkpoint_ids": ["L.G2.all_matras"]})
    s = _start(client, h)  # the session follows the teacher
    assert s["focus_stage"] == "word_read" and s["plan"]["source"] == "teacher_override"
    _end(client, h, s)
    hist = client.get(url, headers=th).json()["history"]
    assert len(hist) == 1 and hist[0]["session_id"] == s["id"] and hist[0]["plan_source"] == "teacher_override"
    assert {"session_id", "date", "lang", "focus_stage", "focus_accuracy", "mastered", "next_focus_stage",
            "plan_source"} == set(hist[0])
    d = client.delete(url, headers=th, params={"subject": "literacy"})
    assert d.status_code == 200 and d.json()["override"] is None
    assert d.json()["plan"]["source"] in ("level_check", "last_session")
    eng = client.get(url, headers=th, params={"subject": "english"}).json()
    assert eng["subject"] == "english" and eng["plan"]["subject"] == "english" and eng["history"] == []


def test_home_focus_422_and_tenancy(client, sandbox, th, teacher_headers):
    _, cid = make_kid(sandbox)
    url = f"/v1/children/{cid}/home_focus"
    for bad in ({"subject": "literacy", "stage": "flying"}, {"subject": "maths", "stage": "letter"},
                {"subject": "literacy", "stage": "letter", "checkpoint_ids": ["L.nope"]},
                {"subject": "literacy", "stage": "letter", "checkpoint_ids": ["E.G1.letter_names"]},
                {"subject": "literacy", "stage": "letter", "days": 31},
                {"subject": "literacy", "stage": "letter", "note": "x" * 201}):
        assert client.put(url, headers=th, json=bad).status_code == 422, bad
    assert client.get(url, headers=th, params={"subject": "maths"}).status_code == 422
    # another school's teacher sees nothing and changes nothing
    assert client.get(url, headers=teacher_headers).status_code == 404
    assert client.put(url, headers=teacher_headers, json={"subject": "literacy", "stage": "letter"}).status_code == 404
    assert client.delete(url, headers=teacher_headers).status_code == 404
    with SessionLocal() as db:
        assert not db.scalar(select(HomeFocus.id).where(HomeFocus.child_id == cid))


def test_parent_plan_preview(client, sandbox, fakes, clock):
    h, cid = make_kid(sandbox, {"literacy": "word", "english": "letter"})
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(VoiceSession))
    p = client.get("/v1/parent/voice/plan", headers=h, params={"lang": "hi"})
    assert p.status_code == 200, p.text
    assert p.json()["focus_stage"] == "sentence_build" and p.json()["subject"] == "literacy"
    en = client.get("/v1/parent/voice/plan", headers=h, params={"lang": "en"}).json()
    assert en["subject"] == "english" and en["focus_stage"] == "word_build"
    assert client.get("/v1/parent/voice/plan", headers=h).json()["focus_stage"] == "sentence_build"  # default hi
    assert client.get("/v1/parent/voice/plan", headers=h, params={"lang": "xx"}).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(VoiceSession)) == before  # a preview writes nothing
    assert client.get("/v1/parent/voice/plan").status_code == 401


def test_delete_routes_remove_home_focus(client):
    with SessionLocal() as db:
        school = School(name="Focus Delete School", code="FD" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="T", pin_hash=hash_pin("4321"))
        db.add(t)
        db.flush()
        cls = Classroom(school_id=school.id, teacher_id=t.id, grade=2, section="D", label="2D")
        db.add(cls)
        db.flush()
        kids = [Child(class_id=cls.id, roll_no=n, first_name=f"K{n}") for n in (1, 2, 3)]
        db.add_all(kids)
        db.flush()
        for k in kids:
            db.add(HomeFocus(school_id=school.id, child_id=k.id, subject="literacy", stage="letter",
                             until=date(2030, 1, 1)))
        db.commit()
        ids, cls_id = [k.id for k in kids], cls.id
        h = {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}
    assert client.delete(f"/v1/children/{ids[0]}/data", headers=h).status_code == 200
    with SessionLocal() as db:
        assert sorted(db.scalars(select(HomeFocus.child_id).where(HomeFocus.child_id.in_(ids)))) == ids[1:]
    assert client.delete(f"/v1/classes/{cls_id}/data", headers=h).status_code == 200
    with SessionLocal() as db:
        assert not db.scalar(select(HomeFocus.id).where(HomeFocus.child_id.in_(ids)))


# ------------------------------------------------------------------ demo seed
def test_demo_child_history_and_next_plan(client, teacher_headers, parent_headers):
    with SessionLocal() as db:
        sch = db.scalar(select(School).where(School.code == DEMO_CODE))
        parent = db.scalar(select(ParentAccount).where(ParentAccount.school_id == sch.id))
        roll3 = db.scalar(select(Child).join(Classroom, Classroom.id == Child.class_id).where(
            Classroom.school_id == sch.id, Classroom.grade == 2, Child.roll_no == 3))
        child_id = parent.child_id
    body = client.get(f"/v1/children/{child_id}/home_focus", headers=teacher_headers).json()
    hist = body["history"]
    assert [(r["focus_stage"], r["mastered"], r["next_focus_stage"]) for r in hist[-2:]] == [
        ("word_read", False, "word_read"), ("word_build", True, "word_read")]
    assert hist[-1]["plan_source"] == "level_check" and hist[-2]["plan_source"] == "last_session"
    assert body["plan"]["source"] == "last_session" and body["plan"]["focus_stage"] == "word_read"
    assert body["plan"]["target_sounds"]
    p = client.get("/v1/parent/voice/plan", headers=parent_headers, params={"lang": "hi"}).json()
    assert p["focus_stage"] == "word_read" and p["source"] == "last_session"
    rows = client.get("/v1/parent/voice/sessions", headers=parent_headers).json()
    seeded = [r for r in rows if r["status"] == "ended" and r["plan_source"]]
    assert len(seeded) >= 2 and all(r["items"] > 0 for r in seeded)
    rep = client.get(f"/v1/parent/voice/sessions/{seeded[0]['id']}", headers=parent_headers).json()["report"]
    assert rep["outcome"]["focus_stage"] == "word_read" and rep["narrative"]["parent_en"]
    if "E.G1.letter_sounds" in vse.get_content().checkpoints:
        en = client.get(f"/v1/children/{roll3.id}/home_focus", headers=teacher_headers,
                        params={"subject": "english"}).json()
        assert en["override"]["stage"] == "letter" and en["plan"]["source"] == "teacher_override"
        assert en["override"]["note"] == "Practise letter sounds this week"
