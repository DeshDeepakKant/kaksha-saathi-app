"""Teacher v2 core additions: guardrail counters, moved, timeline, attendance, nipun_ref, hardening.

State-sensitive checks use a throwaway class (grade 2, section Z) so other tests sharing the seeded DB
are unaffected; it is removed at module teardown.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models.tables import (
    Attendance, CaptureSession, Child, Classroom, Evidence, InterventionLog, Plan, Roadmap, RoadmapItem, School,
    Teacher,
)
from app.services.ledger import school_today

BORROW = "N.G2.sub_2digit_borrow"


def _utc_naive(**delta) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**delta)


@pytest.fixture(scope="module")
def zclass(client, teacher_headers):
    """Class Z with: A improved, B slipped, C constant gap, D constant gap, E no evidence."""
    with SessionLocal() as db:
        sch = db.scalar(select(School).where(School.code == "DEMO"))
        teacher = db.scalar(select(Teacher).where(Teacher.school_id == sch.id))
        cls = Classroom(school_id=sch.id, teacher_id=teacher.id, grade=2, section="Z", label="कक्षा 2Z")
        db.add(cls)
        db.flush()
        kids = {}
        for roll, name in enumerate(["Asha", "Bina", "Chitra", "Dev", "Esha"], start=1):
            ch = Child(class_id=cls.id, roll_no=roll, first_name=name)
            db.add(ch)
            db.flush()
            kids[name] = ch.id

        def ev(name, result, **ago):
            db.add(Evidence(school_id=sch.id, class_id=cls.id, child_id=kids[name], checkpoint_id=BORROW,
                            result=result, source="teacher_tap", confidence=1.0, at=_utc_naive(**ago),
                            status="confirmed"))
        ev("Asha", "incorrect", days=10)              # gap 10 days ago ...
        ev("Asha", "correct", hours=2)                # ... on track now
        ev("Asha", "correct", hours=1)
        ev("Bina", "correct", days=10)                # on track 10 days ago ...
        ev("Bina", "correct", days=9)
        ev("Bina", "incorrect", hours=2)              # ... gap now
        ev("Bina", "incorrect", hours=1)
        for n in ("Chitra", "Dev"):
            ev(n, "incorrect", days=10)
        db.commit()
        info = {"class_id": cls.id, "kids": kids, "school_id": sch.id}
    yield info
    with SessionLocal() as db:
        ids = list(kids.values())
        plan_ids = [p.id for p in db.scalars(select(Plan).where(Plan.class_id == info["class_id"]))]
        db.execute(delete(InterventionLog).where(InterventionLog.plan_id.in_(plan_ids)))
        db.execute(delete(Evidence).where(Evidence.child_id.in_(ids)))
        db.execute(delete(Attendance).where(Attendance.class_id == info["class_id"]))
        db.execute(delete(CaptureSession).where(CaptureSession.class_id == info["class_id"]))
        db.execute(delete(Plan).where(Plan.class_id == info["class_id"]))
        db.execute(delete(RoadmapItem).where(RoadmapItem.roadmap_id.in_(
            select(Roadmap.id).where(Roadmap.class_id == info["class_id"]))))
        db.execute(delete(Roadmap).where(Roadmap.class_id == info["class_id"]))
        db.execute(delete(Child).where(Child.id.in_(ids)))
        db.execute(delete(Classroom).where(Classroom.id == info["class_id"]))
        db.commit()


# ------------------------------------------------------------------ guardrail counters
def _note_capture(client, h, class_id=1):
    r = client.post(f"/v1/classes/{class_id}/captures/note", headers=h,
                    data={"transcript": "Rohan ko ghatana nahi aata, minus mein galti", "subject": "numeracy"})
    assert r.status_code == 200, r.text
    return r.json()["capture_id"]


def test_confirm_counters_feed_ai_activity(client, teacher_headers):
    before = client.get("/v1/ai_activity", headers=teacher_headers).json()
    for k in ("edited", "skipped", "cost_inr_today", "checks_7d", "plans_7d"):
        assert k in before
    for k in ("captures", "proposals", "confirmed", "rejected", "degraded", "ai_calls", "cost_inr",
              "validation_failures"):
        assert k in before  # old keys survive
    cap = _note_capture(client, teacher_headers)
    r = client.post(f"/v1/captures/{cap}/confirm", headers=teacher_headers,
                    json={"accepted": [], "skipped": 3, "edited": 2})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    cap2 = _note_capture(client, teacher_headers)
    assert client.post(f"/v1/captures/{cap2}/confirm", headers=teacher_headers,
                       json={"accepted": [], "reject_all": True, "skipped": 1}).status_code == 200
    after = client.get("/v1/ai_activity", headers=teacher_headers).json()
    assert after["skipped"] - before["skipped"] == 4
    assert after["edited"] - before["edited"] == 2
    # rejected = discarded captures + skipped proposals
    assert after["rejected"] - before["rejected"] == 1 + 4
    assert 0 <= after["cost_inr_today"] <= after["cost_inr"]


def test_confirm_defaults_counters_to_zero(client, teacher_headers):
    cap = _note_capture(client, teacher_headers)
    before = client.get("/v1/ai_activity", headers=teacher_headers).json()
    assert client.post(f"/v1/captures/{cap}/confirm", headers=teacher_headers,
                       json={"accepted": []}).status_code == 200
    after = client.get("/v1/ai_activity", headers=teacher_headers).json()
    assert (after["skipped"], after["edited"]) == (before["skipped"], before["edited"])


def test_checks_and_plans_7d_grow(client, teacher_headers, zclass):
    cid = zclass["class_id"]
    kid, cp = 30, "L.G2.word_formation"  # class 1: a literacy topic nothing else asserts on
    before = client.get("/v1/ai_activity", headers=teacher_headers).json()
    client.post("/v1/classes/1/captures/tap", headers=teacher_headers,
                json={"items": [{"child_id": kid, "checkpoint_id": cp, "result": "correct"}]})
    client.post("/v1/classes/1/captures/probe", headers=teacher_headers,
                params={"child_id": kid, "checkpoint_id": cp, "passed": 2, "total": 3})
    assert client.post(f"/v1/classes/{cid}/plans?subject=numeracy&force=true",
                       headers=teacher_headers).status_code == 200
    after = client.get("/v1/ai_activity", headers=teacher_headers).json()
    assert after["checks_7d"] - before["checks_7d"] == 2
    assert after["plans_7d"] - before["plans_7d"] == 1
    # seeded evidence is 3 weeks of taps/photos/voice, so the 7 day figure is already non-trivial
    assert before["checks_7d"] > 0


# ------------------------------------------------------------------ moved
def test_moved_improved_and_slipped(client, teacher_headers, zclass):
    r = client.get(f"/v1/classes/{zclass['class_id']}/moved?subject=numeracy&hours=24", headers=teacher_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["since"]
    moves = {m["first_name"]: m for m in j["moves"]}
    assert set(moves) == {"Asha", "Bina"}  # Chitra/Dev unchanged, Esha never assessed
    a, b = moves["Asha"], moves["Bina"]
    assert a["direction"] == "improved" and a["to"] is None and a["from"]["key"]
    assert {"key", "title_hi", "title_en"} <= set(a["from"])
    assert b["direction"] == "slipped" and b["from"] is None and b["to"]["key"]
    assert a["child_id"] == zclass["kids"]["Asha"] and a["roll_no"] == 1


def test_moved_window_and_validation(client, teacher_headers, zclass):
    cid = zclass["class_id"]
    # a window reaching back before all evidence: a first assessment is new information, not a move,
    # so nobody is reported (otherwise every newly marked child would show up as "slipped")
    far = client.get(f"/v1/classes/{cid}/moved?subject=numeracy&hours=2000", headers=teacher_headers).json()
    assert far["moves"] == []
    assert client.get(f"/v1/classes/{cid}/moved?subject=bogus", headers=teacher_headers).status_code == 422
    assert client.get(f"/v1/classes/{cid}/moved?subject=numeracy&hours=0", headers=teacher_headers).status_code == 422
    assert client.get("/v1/classes/999999/moved?subject=numeracy", headers=teacher_headers).status_code == 404


# ------------------------------------------------------------------ timeline
def test_timeline_points(client, teacher_headers, zclass):
    kid = zclass["kids"]["Asha"]
    r = client.get(f"/v1/children/{kid}/timeline?subject=numeracy&weeks=6", headers=teacher_headers)
    assert r.status_code == 200, r.text
    pts = r.json()["points"]
    assert len(pts) == 6
    assert pts[-1]["week_end"] == datetime.now(timezone.utc).date().isoformat()
    keys = {"week_end", "on_track", "needs_practice", "needs_intervention", "assessed", "total"}
    assert all(keys <= set(p) for p in pts)
    assert [p["week_end"] for p in pts] == sorted(p["week_end"] for p in pts)
    total = len(client.get(f"/v1/classes/{zclass['class_id']}/roadmap?subject=numeracy",
                           headers=teacher_headers).json()["items"])
    assert all(p["total"] == total for p in pts)
    assert pts[-1]["on_track"] == 1 and pts[-1]["assessed"] == 1
    # first evidence (10 days ago) is visible from the week-end 7 days back, not before
    assert pts[-3]["assessed"] == 0
    assert pts[-2]["assessed"] == 1 and pts[-2]["on_track"] == 0


def test_timeline_bad_input(client, teacher_headers, zclass):
    kid = zclass["kids"]["Asha"]
    assert client.get(f"/v1/children/{kid}/timeline?subject=numeracy&weeks=0", headers=teacher_headers).status_code == 422
    assert client.get(f"/v1/children/{kid}/timeline?subject=x", headers=teacher_headers).status_code == 422
    assert client.get("/v1/children/999999/timeline?subject=numeracy", headers=teacher_headers).status_code == 404
    # default weeks = 6
    assert len(client.get(f"/v1/children/{kid}/timeline?subject=numeracy", headers=teacher_headers).json()["points"]) == 6


# ------------------------------------------------------------------ attendance + board absent
def test_attendance_get_and_board_absent(client, teacher_headers, zclass):
    cid, kids = zclass["class_id"], zclass["kids"]
    empty = client.get(f"/v1/classes/{cid}/attendance", headers=teacher_headers).json()
    assert empty == {"day": school_today().isoformat(), "absent_rolls": [], "present": 5}
    assert client.post(f"/v1/classes/{cid}/attendance", json={"absent_rolls": [2, 5]},
                       headers=teacher_headers).status_code == 200
    j = client.get(f"/v1/classes/{cid}/attendance", headers=teacher_headers).json()
    assert j["absent_rolls"] == [2, 5] and j["present"] == 3
    old = (school_today() - timedelta(days=3)).isoformat()
    assert client.get(f"/v1/classes/{cid}/attendance?day={old}", headers=teacher_headers).json() == {
        "day": old, "absent_rolls": [], "present": 5}
    board = client.get(f"/v1/classes/{cid}/board?subject=numeracy", headers=teacher_headers).json()
    assert sorted(board["absent"]) == sorted([kids["Bina"], kids["Esha"]])
    assert client.get("/v1/classes/999999/attendance", headers=teacher_headers).status_code == 404
    # seeded class 1 has rolls 1 and 2 absent today
    seeded = client.get("/v1/classes/1/attendance", headers=teacher_headers).json()
    assert {1, 2} <= set(seeded["absent_rolls"])


# ------------------------------------------------------------------ nipun_ref
def test_nipun_ref_everywhere(client, teacher_headers):
    cps = client.get("/v1/content/checkpoints?subject=numeracy", headers=teacher_headers).json()
    assert cps and all("nipun_ref" in c for c in cps)
    refs = {c["id"]: c["nipun_ref"] for c in cps}
    board = client.get("/v1/classes/1/board?subject=numeracy", headers=teacher_headers).json()
    assert "absent" in board and board["groups"]
    for g in board["groups"]:
        assert g["nipun_ref"] == refs.get(g["key"], g["nipun_ref"])
    prof = client.get("/v1/children/12/profile?subject=numeracy", headers=teacher_headers).json()
    assert prof["items"] and all("nipun_ref" in i and i["nipun_ref"] == refs.get(i["checkpoint_id"], "")
                                 for i in prof["items"])
    plan = client.post("/v1/classes/1/plans?subject=numeracy&force=true", headers=teacher_headers).json()
    assert plan["groups"] and all("nipun_ref" in g for g in plan["groups"])
    assert all(g["nipun_ref"] == refs.get(g["key"], g["nipun_ref"]) for g in plan["groups"])
    latest = client.get("/v1/classes/1/plans/latest?subject=numeracy", headers=teacher_headers).json()
    assert all("nipun_ref" in g for g in latest["groups"])


def test_plan_assess_first_members_are_children(client, teacher_headers, zclass):
    p = client.post(f"/v1/classes/{zclass['class_id']}/plans?subject=numeracy&force=true",
                    headers=teacher_headers).json()
    af = p["assess_first"]
    assert af and af["key"] == "assess_first" and af["unassessed"] is True and "nipun_ref" in af
    assert af["members"] and all(set(m) == {"id", "first_name"} for m in af["members"])
    assert zclass["kids"]["Esha"] in {m["id"] for m in af["members"]}
    for g in p["groups"]:  # other groups keep their shape
        assert g["members"] and all({"id", "first_name"} <= set(m) for m in g["members"])
    latest = client.get(f"/v1/classes/{zclass['class_id']}/plans/latest?subject=numeracy",
                        headers=teacher_headers).json()
    assert latest["assess_first"]["members"] == af["members"]


def test_old_plan_payload_is_upgraded(client, teacher_headers, zclass):
    """A plan stored before v2 (roll-number members, no nipun_ref) is served in the new shape."""
    cid = zclass["class_id"]
    with SessionLocal() as db:
        plan = db.scalar(select(Plan).where(Plan.class_id == cid, Plan.subject == "numeracy"))
        old = dict(plan.payload)
        old["assess_first"] = {**old["assess_first"], "members": [5]}
        old["groups"] = [{k: v for k, v in g.items() if k != "nipun_ref"} for g in old["groups"]]
        old["assess_first"].pop("nipun_ref", None)
        plan.payload = old
        db.commit()
    p = client.post(f"/v1/classes/{cid}/plans?subject=numeracy", headers=teacher_headers).json()
    assert p["assess_first"]["members"] == [{"id": zclass["kids"]["Esha"], "first_name": "Esha"}]
    assert all("nipun_ref" in g for g in p["groups"])


# ------------------------------------------------------------------ hardening
def _fresh_capture(client, h):
    return _note_capture(client, h)


@pytest.mark.parametrize("item", [
    {"checkpoint_id": "L.G1.matra_basic", "result": "correct"},                       # no child_id
    {"child_id": 2, "result": "correct"},                                              # no checkpoint
    {"child_id": 2, "checkpoint_id": "L.G1.matra_basic"},                              # no result
    {"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "result": "correct", "confidence": None},
    {"child_id": "abc", "checkpoint_id": "L.G1.matra_basic", "result": "correct"},
    {"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "result": "perfect"},
])
def test_confirm_bad_items_are_422(client, teacher_headers, item):
    cap = _fresh_capture(client, teacher_headers)
    r = client.post(f"/v1/captures/{cap}/confirm", headers=teacher_headers, json={"accepted": [item]})
    assert r.status_code == 422, r.text
    # the capture stays proposed, so the teacher can fix and resubmit
    assert client.post(f"/v1/captures/{cap}/confirm", headers=teacher_headers, json={"accepted": []}).status_code == 200


def test_confirm_full_item_still_works(client, teacher_headers):
    cap = _fresh_capture(client, teacher_headers)
    r = client.post(f"/v1/captures/{cap}/confirm", headers=teacher_headers, json={"accepted": [
        {"child_id": 3, "checkpoint_id": "L.G1.matra_basic", "result": "partial", "confidence": 0.7,
         "quote": "x" * 400, "misconception": None, "extra": "ignored"}]})
    assert r.status_code == 200 and r.json()["committed"] == 1


@pytest.mark.parametrize("body", [
    "not json", "[]", "{}", '{"child_id": 2}', '{"child_id": 2, "checkpoint_id": "L.G1.matra_basic"}',
    '{"child_id": "x", "checkpoint_id": "L.G1.matra_basic", "target_items": []}',
    '{"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "target_items": 5}',
])
def test_voice_bad_body_json_is_422(client, teacher_headers, body):
    r = client.post("/v1/classes/1/captures/voice", headers=teacher_headers, data={"body_json": body})
    assert r.status_code == 422, r.text


def test_voice_unknown_checkpoint_still_422(client, teacher_headers):
    r = client.post("/v1/classes/1/captures/voice", headers=teacher_headers, data={
        "body_json": '{"child_id": 2, "checkpoint_id": "nope", "target_items": ["a"]}', "transcript": "a"})
    assert r.status_code == 422


def test_voice_asr_failure_is_not_a_crash(client, teacher_headers, monkeypatch):
    from app.api import teacher as t

    class Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("asr down")

    monkeypatch.setattr(t, "get_asr", lambda: Boom())
    r = client.post("/v1/classes/1/captures/voice", headers=teacher_headers,
                    data={"body_json": '{"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "target_items": ["का"]}'},
                    files={"audio": ("a.m4a", b"\x00\x01\x02", "audio/mp4")})
    assert r.status_code == 200 and r.json()["ai_status"] == "low_audio_quality"


def test_roadmap_non_integer_position_is_422(client, teacher_headers, zclass):
    cid = zclass["class_id"]
    items = [{"checkpoint_id": "N.G2.place_value_99", "position": 0},
             {"checkpoint_id": "N.G2.add_2digit_no_carry", "position": "abc"},
             {"checkpoint_id": BORROW, "position": 2}]
    r = client.post(f"/v1/classes/{cid}/roadmap", headers=teacher_headers,
                    json={"subject": "numeracy", "items": items})
    assert r.status_code == 422, r.text
    # nothing half-written: still no confirmed roadmap
    assert client.get(f"/v1/classes/{cid}/roadmap?subject=numeracy", headers=teacher_headers).json()["confirmed"] is False
    items[1]["position"] = 1
    ok = client.post(f"/v1/classes/{cid}/roadmap", headers=teacher_headers,
                     json={"subject": "numeracy", "items": items})
    assert ok.status_code == 200 and ok.json()["version"] == 1


def test_photo_retake_message_is_bilingual(client, teacher_headers, monkeypatch):
    from app.api import teacher as t

    class P:
        ai_status = "ready"
        note = ""
        payload = {"page": {"legible": False}, "questions": []}

    monkeypatch.setattr(t.features, "analyze_photo", lambda *a, **k: P())
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    r = client.post("/v1/classes/1/captures/photo", headers=teacher_headers, data={"child_id": 3},
                    files={"image": ("p.png", png, "image/png")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ai_status"] == "retake" and j["capture_id"] is None
    hindi, english = j["message"].split(" / ")
    assert "फ़ोटो" in hindi and "photo" in english.lower()


# ------------------------------------------------------------------ replay safety (offline outbox)
def _evidence_count(child_id, cp, source):
    with SessionLocal() as db:
        return len(db.scalars(select(Evidence).where(Evidence.child_id == child_id, Evidence.checkpoint_id == cp,
                                                     Evidence.source == source)).all())


def test_tap_with_same_client_uuid_is_applied_once(client, teacher_headers, zclass):
    cid, kid = zclass["class_id"], zclass["kids"]["Esha"]
    body = {"client_uuid": "tap-uuid-1", "items": [{"child_id": kid, "checkpoint_id": "L.G1.swar", "result": "correct"}]}
    before = _evidence_count(kid, "L.G1.swar", "teacher_tap")
    a = client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=body)
    b = client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=body)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == {"committed": 1}
    assert _evidence_count(kid, "L.G1.swar", "teacher_tap") - before == 1
    # a different uuid (or none) is a new request
    body2 = {**body, "client_uuid": "tap-uuid-2"}
    client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=body2)
    del body2["client_uuid"]
    client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=body2)
    assert _evidence_count(kid, "L.G1.swar", "teacher_tap") - before == 3
    # markers are not AI captures
    j = client.get("/v1/ai_activity", headers=teacher_headers).json()
    with SessionLocal() as db:
        n = len(db.scalars(select(CaptureSession).where(CaptureSession.kind.not_in(("tap", "probe")),
                                                        CaptureSession.school_id == zclass["school_id"])).all())
    assert j["captures"] == n


def test_failed_tap_does_not_burn_the_uuid(client, teacher_headers, zclass):
    cid, kid = zclass["class_id"], zclass["kids"]["Esha"]
    bad = {"client_uuid": "tap-uuid-bad", "items": [{"child_id": kid, "checkpoint_id": "nope", "result": "correct"}]}
    assert client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=bad).status_code == 422
    good = {"client_uuid": "tap-uuid-bad",
            "items": [{"child_id": kid, "checkpoint_id": "L.G1.vyanjan", "result": "correct"}]}
    assert client.post(f"/v1/classes/{cid}/captures/tap", headers=teacher_headers, json=good).json() == {"committed": 1}


def test_probe_with_same_client_uuid_is_applied_once(client, teacher_headers, zclass):
    cid, kid = zclass["class_id"], zclass["kids"]["Esha"]
    q = {"child_id": kid, "checkpoint_id": "L.G1.matra_basic", "passed": 3, "total": 4, "client_uuid": "probe-uuid-1"}
    before = _evidence_count(kid, "L.G1.matra_basic", "guided_probe")
    a = client.post(f"/v1/classes/{cid}/captures/probe", headers=teacher_headers, params=q)
    b = client.post(f"/v1/classes/{cid}/captures/probe", headers=teacher_headers, params=q)
    assert a.status_code == b.status_code == 200 and a.json() == b.json() == {"result": "correct"}
    assert _evidence_count(kid, "L.G1.matra_basic", "guided_probe") - before == 1
    q.pop("client_uuid")  # without a uuid, behaviour is unchanged
    client.post(f"/v1/classes/{cid}/captures/probe", headers=teacher_headers, params=q)
    assert _evidence_count(kid, "L.G1.matra_basic", "guided_probe") - before == 2


def test_plan_group_done_is_idempotent(client, teacher_headers, zclass):
    cid = zclass["class_id"]
    plan = client.post(f"/v1/classes/{cid}/plans?subject=numeracy&force=true", headers=teacher_headers).json()
    url = f"/v1/plans/{plan['id']}/groups/{BORROW}/done"
    assert client.post(url, headers=teacher_headers).json() == {"ok": True}
    assert client.post(url, headers=teacher_headers).json() == {"ok": True}
    client.post(f"/v1/plans/{plan['id']}/groups/other_group/done", headers=teacher_headers)
    with SessionLocal() as db:
        rows = db.scalars(select(InterventionLog).where(InterventionLog.plan_id == plan["id"])).all()
    assert sorted(r.group_key for r in rows) == sorted([BORROW, "other_group"])
    assert client.post("/v1/plans/999999/groups/x/done", headers=teacher_headers).status_code == 404
