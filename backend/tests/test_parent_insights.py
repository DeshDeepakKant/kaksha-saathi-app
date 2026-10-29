"""Parent insights (school → home): the five /v1/parent routes in docs/parent_insights_contract.md.

Shape checks run on the seeded demo child (roll 12). State-sensitive checks use a throwaway school
(its own classes, children and parent accounts) that is removed at module teardown, so the shared
seeded DB is untouched. Reviewed tip/home content is monkeypatched where a test needs it, so these
tests pass whether or not `content/misconception_tips.json` is filled in yet.
"""
from __future__ import annotations

import itertools
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.security import make_token
from app.db import SessionLocal
from app.models.tables import (Attendance, Child, Classroom, Evidence, HomeSession, ParentAccount, Plan, School,
                               Teacher, VoiceSession)
from app.services import ledger, tips

ROUTES = ["/v1/parent/school_week", "/v1/parent/journey", "/v1/parent/tips", "/v1/parent/moments",
          "/v1/parent/weekly"]
BORROW = "N.G2.sub_2digit_borrow"
CARRY = "N.G2.add_2digit_carry"
PV = "N.G2.place_value_99"
ADD1 = "N.G1.add_single"
SUB1 = "N.G1.sub_single"
STATES = {"learned", "working", "next", "later"}


def _ago(**delta) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**delta)


def _fake_tip(mid: str) -> dict:
    return {"id": mid, "checkpoint_ids": [], "explain_hi": f"समझाएँ {mid}", "explain_en": f"Explain {mid}",
            "game_hi": "खेल", "game_en": "Game", "example": "52 − 17 → 45", "reviewed": True}


def _fake_home(aid: str) -> dict:
    return {"id": aid, "title_hi": "घर का खेल", "title_en": "Home game", "materials_hi": "कंकड़",
            "materials_en": "Pebbles", "steps_hi": ["एक", "दो", "तीन", "चार"], "steps_en": ["1", "2", "3", "4"],
            "minutes": 5}


# ------------------------------------------------------------------ sandbox school
class Sandbox:
    def __init__(self):
        self.sections = itertools.count(1)
        with SessionLocal() as db:
            sch = School(name="Insights sandbox", code=f"PI{uuid.uuid4().hex[:8].upper()}")
            db.add(sch)
            db.flush()
            t = Teacher(school_id=sch.id, name="T", pin_hash="x")
            db.add(t)
            db.commit()
            self.school_id, self.teacher_id = sch.id, t.id

    def klass(self, names: list[str], grade: int = 2) -> tuple[int, list[int], dict]:
        """A new class with `names`; returns (class_id, child ids, parent headers for the first child)."""
        with SessionLocal() as db:
            sec = f"S{next(self.sections)}"
            cls = Classroom(school_id=self.school_id, teacher_id=self.teacher_id, grade=grade, section=sec,
                            label=f"कक्षा {grade}{sec}")
            db.add(cls)
            db.flush()
            ids = []
            for roll, nm in enumerate(names, start=1):
                ch = Child(class_id=cls.id, roll_no=roll, first_name=nm)
                db.add(ch)
                db.flush()
                ids.append(ch.id)
            p = ParentAccount(school_id=self.school_id, child_id=ids[0], phone_hash="x", pin_hash="x")
            db.add(p)
            db.commit()
            return cls.id, ids, {"Authorization": f"Bearer {make_token(str(p.id), 'parent')}"}

    def ev(self, cls_id: int, child_id: int, cp: str, result: str, at: datetime, source: str = "teacher_tap",
           misc: str | None = None):
        with SessionLocal() as db:
            db.add(Evidence(school_id=self.school_id, class_id=cls_id, child_id=child_id, checkpoint_id=cp,
                            result=result, source=source, confidence=1.0, at=at, status="confirmed",
                            misconception=misc))
            db.commit()

    def add(self, *rows):
        with SessionLocal() as db:
            for r in rows:
                if hasattr(r, "school_id"):
                    r.school_id = self.school_id
                db.add(r)
            db.commit()

    def cleanup(self):
        with SessionLocal() as db:
            cls_ids = select(Classroom.id).where(Classroom.school_id == self.school_id)
            kid_ids = select(Child.id).where(Child.class_id.in_(cls_ids))
            db.execute(delete(Evidence).where(Evidence.child_id.in_(kid_ids)))
            db.execute(delete(Attendance).where(Attendance.child_id.in_(kid_ids)))
            db.execute(delete(HomeSession).where(HomeSession.child_id.in_(kid_ids)))
            db.execute(delete(VoiceSession).where(VoiceSession.child_id.in_(kid_ids)))
            db.execute(delete(Plan).where(Plan.school_id == self.school_id))
            db.execute(delete(ParentAccount).where(ParentAccount.school_id == self.school_id))
            db.execute(delete(Child).where(Child.class_id.in_(cls_ids)))
            db.execute(delete(Classroom).where(Classroom.school_id == self.school_id))
            db.execute(delete(Teacher).where(Teacher.school_id == self.school_id))
            db.execute(delete(School).where(School.id == self.school_id))
            db.commit()


@pytest.fixture(scope="module")
def sb(client):
    s = Sandbox()
    yield s
    s.cleanup()


def _all_text(client, headers) -> str:
    out = []
    for path in ROUTES + ["/v1/parent/journey?subject=literacy"]:
        r = client.get(path, headers=headers)
        assert r.status_code == 200, (path, r.text)
        out.append(json.dumps(r.json(), ensure_ascii=False))
    return "\n".join(out)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[ऀ-ॿ]+|[A-Za-z]+", text))


# ------------------------------------------------------------------ auth
def test_routes_need_a_parent_token(client, teacher_headers):
    for path in ROUTES:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"Authorization": "Bearer nonsense"}).status_code == 401, path
        assert client.get(path, headers=teacher_headers).status_code == 403, path


# ------------------------------------------------------------------ shapes on the demo child
def test_school_week_shape(client, parent_headers):
    d = client.get("/v1/parent/school_week", headers=parent_headers).json()
    assert set(d) >= {"class_topic", "child_focus", "line_hi", "line_en", "as_of"}
    assert d["as_of"] == ledger.school_today().isoformat()
    assert set(d["class_topic"]) == {"checkpoint_id", "chapter", "title_hi", "title_en", "subject"}
    assert set(d["child_focus"]) == {"checkpoint_id", "title_hi", "title_en", "subject", "state"}
    assert d["child_focus"]["state"] in {"learned", "working", "next"}
    assert "कविता" in d["line_hi"] and "कविता" in d["line_en"]
    assert d["class_topic"]["title_hi"] in d["line_hi"]


def test_journey_shape(client, parent_headers):
    for subject in ("numeracy", "literacy"):
        d = client.get(f"/v1/parent/journey?subject={subject}", headers=parent_headers).json()
        assert d["subject"] == subject and d["grade"] == 2
        ms = d["milestones"]
        assert ms and all(set(m) == {"checkpoint_id", "chapter", "title_hi", "title_en", "nipun_ref", "state"}
                          for m in ms)
        assert all(m["state"] in STATES and m["title_hi"] for m in ms)
        assert d["counts"] == {"learned": sum(m["state"] == "learned" for m in ms),
                               "working": sum(m["state"] == "working" for m in ms), "total": len(ms)}
        assert 1 <= sum(m["state"] == "next" for m in ms) <= 2
        assert len(d["growth"]) == 6 and all(set(g) == {"week_end", "learned"} for g in d["growth"])
        assert isinstance(d["celebrations"], list)
    # the demo child struggles with place value: it is being worked on, not learned
    num = client.get("/v1/parent/journey", headers=parent_headers).json()
    assert {m["checkpoint_id"]: m["state"] for m in num["milestones"]}[PV] == "working"


def test_tips_moments_weekly_shape(client, parent_headers):
    assert len(client.get("/v1/parent/tips", headers=parent_headers).json()["tips"]) <= 3
    assert isinstance(client.get("/v1/parent/moments", headers=parent_headers).json()["moments"], list)
    w = client.get("/v1/parent/weekly", headers=parent_headers).json()
    assert set(w) >= {"week_start", "week_end", "practice_days", "voice_sessions", "voice_minutes", "learned",
                      "working_on", "next", "tip", "line_hi", "line_en"}
    start = datetime.fromisoformat(w["week_start"]).date()
    assert start.weekday() == 0 and (datetime.fromisoformat(w["week_end"]).date() - start).days == 6


def test_demo_child_tip_uses_reviewed_content(client, parent_headers, monkeypatch):
    monkeypatch.setattr(tips, "get_tip", _fake_tip)
    t = client.get("/v1/parent/tips", headers=parent_headers).json()["tips"]
    sml = next(x for x in t if x["misconception"] == "smaller_minus_larger")  # seeded on borrowing, not learned
    assert sml["checkpoint_id"] == BORROW and sml["explain_hi"] == "समझाएँ smaller_minus_larger"
    assert set(t[0]) == {"misconception", "checkpoint_id", "title_hi", "title_en", "explain_hi", "explain_en",
                         "game_hi", "game_en", "example", "seen_at"}
    monkeypatch.setattr(tips, "get_tip", lambda _m: None)  # no reviewed text: show nothing
    assert client.get("/v1/parent/tips", headers=parent_headers).json()["tips"] == []


def test_demo_child_texts_have_no_groups_or_classmates(client, parent_headers, monkeypatch):
    monkeypatch.setattr(tips, "get_tip", _fake_tip)
    monkeypatch.setattr(tips, "home_version", _fake_home)
    text = _all_text(client, parent_headers)
    assert not re.search(r"group|समूह", text, re.I)
    with SessionLocal() as db:
        demo = db.scalar(select(School).where(School.code == "DEMO"))
        names = {c.first_name for c in db.scalars(select(Child).join(Classroom, Child.class_id == Classroom.id)
                                                   .where(Classroom.school_id == demo.id))} - {"कविता"}
    assert not (_tokens(text) & names)


# ------------------------------------------------------------------ sandbox: rules and definitions
def test_brand_new_child_gets_empty_values(client, sb):
    _, _, h = sb.klass(["नया"])
    sw = client.get("/v1/parent/school_week", headers=h).json()
    assert sw["class_topic"] is None and sw["child_focus"] is None and "नया" in sw["line_hi"] and sw["line_en"]
    j = client.get("/v1/parent/journey", headers=h).json()
    assert j["counts"]["learned"] == 0 and j["counts"]["working"] == 0 and j["counts"]["total"] > 0
    assert [m["state"] for m in j["milestones"][:3]] == ["next", "next", "later"]  # template roadmap
    assert j["celebrations"] == [] and all(g["learned"] == 0 for g in j["growth"])
    assert client.get("/v1/parent/journey?subject=nosuch", headers=h).status_code == 422  # not a real subject
    assert client.get("/v1/parent/tips", headers=h).json() == {"tips": []}
    assert client.get("/v1/parent/moments", headers=h).json() == {"moments": []}
    w = client.get("/v1/parent/weekly", headers=h).json()
    assert (w["practice_days"], w["voice_sessions"], w["voice_minutes"], w["tip"]) == (0, 0, 0, None)
    assert w["learned"] == [] and w["working_on"] == [] and len(w["next"]) == 2 and w["line_hi"]


def test_learned_needs_school_evidence(client, sb):
    cls, (kid,), h = sb.klass(["घरवाला"])
    for d in (5, 4, 3, 2, 1):
        sb.ev(cls, kid, ADD1, "correct", _ago(days=d), source="home_tap")
        sb.ev(cls, kid, ADD1, "correct", _ago(days=d, hours=1), source="home_voice")
    j = client.get("/v1/parent/journey", headers=h).json()
    assert {m["checkpoint_id"]: m["state"] for m in j["milestones"]}[ADD1] == "working"
    assert j["counts"]["learned"] == 0 and j["celebrations"] == []
    assert client.get("/v1/parent/moments", headers=h).json()["moments"] == []
    # the class topic ignores home evidence too
    assert client.get("/v1/parent/school_week", headers=h).json()["class_topic"] is None
    for d in (3, 2):  # now the teacher confirms it at school
        sb.ev(cls, kid, ADD1, "correct", _ago(days=d, hours=2))
    j = client.get("/v1/parent/journey", headers=h).json()
    assert {m["checkpoint_id"]: m["state"] for m in j["milestones"]}[ADD1] == "learned"
    assert [c["checkpoint_id"] for c in j["celebrations"]] == [ADD1]


def test_celebrations_only_for_fresh_moves(client, sb):
    cls, (kid,), h = sb.klass(["तारा"])
    for d in (20, 19):  # struggling three weeks ago ...
        sb.ev(cls, kid, ADD1, "incorrect", _ago(days=d))
    for d in (3, 2, 1):  # ... and learned it this week
        sb.ev(cls, kid, ADD1, "correct", _ago(days=d))
    for d in (18, 17, 16):  # learned before the 14-day window: no celebration
        sb.ev(cls, kid, SUB1, "correct", _ago(days=d))
    for d in (10, 9):  # getting better: needs_intervention a week ago, needs_practice now
        sb.ev(cls, kid, CARRY, "incorrect", _ago(days=d))
    sb.ev(cls, kid, CARRY, "correct", _ago(days=1))
    j = client.get("/v1/parent/journey", headers=h).json()
    states = {m["checkpoint_id"]: m["state"] for m in j["milestones"]}
    assert states[ADD1] == "learned" and states[SUB1] == "learned" and states[CARRY] == "working"
    assert [c["checkpoint_id"] for c in j["celebrations"]] == [ADD1]
    c = j["celebrations"][0]
    assert c["line_hi"].startswith("⭐") and "तारा" in c["line_hi"] and c["title_hi"] in c["line_hi"]
    assert datetime.fromisoformat(c["at"]) >= datetime.now(timezone.utc) - timedelta(days=4)
    assert j["growth"][-1]["learned"] == 2 and j["growth"][0]["learned"] == 0
    m = client.get("/v1/parent/moments", headers=h).json()["moments"]
    assert {(x["kind"], x["checkpoint_id"], x["move"]) for x in m} == {
        ("celebration", ADD1, "learned"), ("celebration", CARRY, "getting_better")}
    w = client.get("/v1/parent/weekly", headers=h).json()
    if ledger.school_today().weekday() >= 3:  # learned within this school week (Mon–Sun IST)
        assert {"title_hi": c["title_hi"], "title_en": c["title_en"]} in w["learned"]


def test_tips_newest_first_one_per_mistake_unlearned_only(client, sb, monkeypatch):
    monkeypatch.setattr(tips, "get_tip", _fake_tip)
    cls, (kid,), h = sb.klass(["मीरा"])
    sb.ev(cls, kid, BORROW, "incorrect", _ago(days=10), misc="m1")
    sb.ev(cls, kid, BORROW, "incorrect", _ago(days=9), misc="m3")
    sb.ev(cls, kid, PV, "incorrect", _ago(days=8), misc="m4")
    sb.ev(cls, kid, CARRY, "incorrect", _ago(days=7), misc="m2")
    sb.ev(cls, kid, BORROW, "incorrect", _ago(days=6), misc="m1")
    sb.ev(cls, kid, ADD1, "partial", _ago(days=5), misc="m5")  # later learned: no tip
    for d in (4, 3, 2):
        sb.ev(cls, kid, ADD1, "correct", _ago(days=d))
    sb.ev(cls, kid, PV, "incorrect", _ago(days=40), misc="m6")  # too old
    sb.ev(cls, kid, CARRY, "incorrect", _ago(days=1), source="home_tap", misc="m7")  # home evidence
    t = client.get("/v1/parent/tips", headers=h).json()["tips"]
    assert [x["misconception"] for x in t] == ["m1", "m2", "m4"]
    assert [x["checkpoint_id"] for x in t] == [BORROW, CARRY, PV]
    assert t[0]["seen_at"] > t[1]["seen_at"] > t[2]["seen_at"]
    assert client.get("/v1/parent/weekly", headers=h).json()["tip"]["misconception"] == "m1"


def test_catch_up_when_absent_with_a_plan(client, sb, monkeypatch):
    cls, ids, h = sb.klass(["छोटू", "बड़कू", "मुन्नी"])
    today = ledger.school_today()
    sb.add(Attendance(class_id=cls, child_id=ids[0], day=today, present=False),
           Attendance(class_id=cls, child_id=ids[0], day=today - timedelta(days=5), present=False))  # too old
    act = "A.sub.borrow.bundles"
    from app.services.content import get_content
    acts = get_content().activities_for({BORROW})
    act = acts[0]["id"] if acts else act
    sb.add(Plan(class_id=cls, subject="numeracy", for_date=today, generated_by="fallback", payload={
        "groups": [{"key": BORROW, "activity_id": act, "why_hi": "बड़कू, मुन्नी कमज़ोर समूह",
                    "members": [{"id": ids[1], "first_name": "बड़कू"}, {"id": ids[2], "first_name": "मुन्नी"}],
                    "activity": {"id": act, "title_hi": "समूह गतिविधि"}}],
        "assess_first": {"key": "assess_first", "members": [{"id": ids[0], "first_name": "छोटू"}]}}))
    # without reviewed home content: still a gentle card, no activity
    monkeypatch.setattr(tips, "home_version", lambda _a: None)
    m = client.get("/v1/parent/moments", headers=h).json()["moments"]
    assert [x["kind"] for x in m] == ["catch_up"] and m[0]["activity"] is None and m[0]["day"] == today.isoformat()
    monkeypatch.setattr(tips, "home_version", _fake_home)
    c = client.get("/v1/parent/moments", headers=h).json()["moments"][0]
    assert set(c) == {"kind", "day", "class_did_hi", "class_did_en", "activity", "line_hi", "line_en"}
    assert c["activity"]["id"] == act and c["activity"]["minutes"] == 5 and len(c["activity"]["steps_hi"]) == 3
    assert "आज" in c["class_did_hi"] and "दो-अंकीय घटाव" in c["class_did_hi"]
    assert "छोटू" in c["line_hi"] and "5 मिनट" in c["line_hi"]
    text = _all_text(client, h)
    assert not re.search(r"group|समूह|कमज़ोर|weak", text, re.I)
    assert "बड़कू" not in text and "मुन्नी" not in text
    # the plan gives the class topic when there is no school evidence; the child's own focus is not a classmate's
    sw = client.get("/v1/parent/school_week", headers=h).json()
    assert sw["class_topic"]["checkpoint_id"] == BORROW and sw["child_focus"] is None


def test_child_focus_from_own_plan_topic(client, sb):
    cls, ids, h = sb.klass(["गुड्डी", "पप्पू"])
    sb.ev(cls, ids[0], PV, "incorrect", _ago(days=3))
    sb.ev(cls, ids[1], CARRY, "incorrect", _ago(days=2))
    sb.ev(cls, ids[1], CARRY, "incorrect", _ago(days=1))
    sb.add(Plan(class_id=cls, subject="numeracy", for_date=ledger.school_today(), generated_by="fallback", payload={
        "groups": [{"key": CARRY, "members": [{"id": ids[1], "first_name": "पप्पू"}]},
                   {"key": BORROW, "members": [{"id": ids[0], "first_name": "गुड्डी"}]}]}))
    sw = client.get("/v1/parent/school_week", headers=h).json()
    assert sw["class_topic"]["checkpoint_id"] == CARRY  # most school evidence this week
    assert sw["child_focus"]["checkpoint_id"] == BORROW and sw["child_focus"]["state"] == "next"
    assert "गुड्डी" in sw["line_hi"] and "पप्पू" not in sw["line_hi"]


def test_weekly_counts(client, sb):
    cls, (kid,), h = sb.klass(["रानी"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = ledger.school_today()
    week_start = today - timedelta(days=today.weekday())
    sb.add(HomeSession(child_id=kid, started_at=now - timedelta(minutes=30)),
           VoiceSession(child_id=kid, started_at=now - timedelta(minutes=20), status="ended",
                        report={"minutes": 12}, elapsed_s=700),
           VoiceSession(child_id=kid, started_at=now - timedelta(minutes=5), status="active", elapsed_s=300),
           HomeSession(child_id=kid, started_at=now - timedelta(days=10)))  # an earlier week
    days = 1
    if week_start != today:  # 11:30 IST on Monday is still this school week
        sb.add(VoiceSession(child_id=kid, started_at=datetime(week_start.year, week_start.month, week_start.day, 6),
                            status="ended", report=None, state={"elapsed_s": 120}))
        days = 2
    w = client.get("/v1/parent/weekly", headers=h).json()
    assert w["week_start"] == week_start.isoformat()
    assert w["practice_days"] == days
    assert w["voice_sessions"] == days + 1
    assert w["voice_minutes"] == (17 if days == 1 else 19)
    assert "रानी" in w["line_hi"] and str(days) in w["line_hi"]
