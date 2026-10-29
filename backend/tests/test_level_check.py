"""First-week level check: ladder content, stop rule, writes, replay, class summary, demo seed.

Runs in schools made here, so the seeded DEMO data other tests count on is never changed.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import Child, Classroom, Evidence, LevelCheck, School, Teacher
from app.services import level_check as lc
from app.services.content import get_content


def _school(name: str) -> dict:
    with SessionLocal() as db:
        school = School(name=name, code="LC" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="LC Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.commit()
        return {"school_id": school.id, "teacher_id": t.id,
                "headers": {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}}


@pytest.fixture(scope="module")
def sa():
    return _school("Level Check School")


@pytest.fixture(scope="module")
def sb():
    return _school("Other School")


def _class(client, s, grade=2, children=3):
    r = client.post("/v1/classes", headers=s["headers"], json={"grade": grade, "section": uuid.uuid4().hex[:6]})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    ids = []
    for n in range(1, children + 1):
        c = client.post(f"/v1/classes/{cid}/children", headers=s["headers"],
                        json={"first_name": f"Bachcha{n}", "roll_no": n})
        assert c.status_code == 200, c.text
        ids.append(c.json()["id"])
    return cid, ids


def _post(client, s, cid, child, results, subject="literacy", client_uuid=None):
    body = {"subject": subject, "child_id": child,
            "results": [{"level_key": k, "passed": p} for k, p in results]}
    if client_uuid:
        body["client_uuid"] = client_uuid
    return client.post(f"/v1/classes/{cid}/level_check", headers=s["headers"], json=body)


# ------------------------------------------------------------------ content + stop rule
def test_ladder_loads_and_matches_the_graph():
    ladders = lc.load_ladders()
    assert {"literacy", "numeracy"} <= set(ladders) <= {"literacy", "numeracy", "english"}
    cps = get_content().checkpoints
    for subject, lad in ladders.items():
        assert lad["beginner"]["key"] == "beginner"
        for lv in lad["levels"]:
            assert cps[lv["checkpoint_id"]].subject == subject
            assert lv["of"] == len(lv["items"]) and 1 <= lv["pass_min"] <= lv["of"]
    assert [lv["key"] for lv in ladders["literacy"]["levels"]] == ["letter", "word", "sentence", "story"]
    assert lc.ladder("nope") is None


def test_placement_stop_rule():
    lad = lc.ladder("literacy")
    assert lc.placement(lad, [("letter", False)]) == -1
    assert lc.placement(lad, [("letter", True), ("word", False)]) == 0
    assert lc.placement(lad, [("letter", True), ("word", True), ("sentence", True), ("story", True)]) == 3
    assert lc.placement(lad, [("letter", True)]) == 0  # stopped early on a pass: placed at what was passed
    for bad in ([], [("word", True)], [("letter", True), ("sentence", True)],
                [("letter", False), ("word", False)], [("letter", True), ("word", False), ("sentence", True)],
                [("letter", True), ("word", True), ("sentence", True), ("story", True), ("extra", True)]):
        with pytest.raises(lc.LadderError):
            lc.placement(lad, bad)


# ------------------------------------------------------------------ routes
def test_get_level_check_shape(client, sa):
    cid, ids = _class(client, sa)
    r = client.get(f"/v1/classes/{cid}/level_check", params={"subject": "numeracy"}, headers=sa["headers"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["subject"] == "numeracy" and j["beginner"]["key"] == "beginner"
    assert [lv["index"] for lv in j["levels"]] == list(range(len(j["levels"])))
    assert j["levels"][2]["items"][0] == {"show": "3 + 4", "expect": "7"}
    assert j["levels"][0]["items"][0] == {"show": "3", "expect": None}
    assert [c["child_id"] for c in j["children"]] == ids
    assert all(c["first"] is None and c["latest"] is None for c in j["children"])
    assert j["summary"]["total"] == 3 and j["summary"]["checked"] == 0 and j["summary"]["moved_up"] == 0


def test_subject_without_ladder_is_422(client, sa):
    cid, _ = _class(client, sa, children=0)
    key = client.post("/v1/subjects", headers=sa["headers"], json={"name": "EVS " + uuid.uuid4().hex[:4]}).json()["key"]
    r = client.get(f"/v1/classes/{cid}/level_check", params={"subject": key}, headers=sa["headers"])
    assert r.status_code == 422
    assert client.get(f"/v1/classes/{cid}/level_check", params={"subject": "nope"},
                      headers=sa["headers"]).status_code == 422


def test_post_writes_evidence_and_level_row(client, sa):
    cid, ids = _class(client, sa)
    r = _post(client, sa, cid, ids[0], [("letter", True), ("word", False)])
    assert r.status_code == 200, r.text
    assert r.json() == {"level_index": 0, "level_key": "letter", "title_en": "Letters", "title_hi": "अक्षर"}
    with SessionLocal() as db:
        evs = db.scalars(select(Evidence).where(Evidence.child_id == ids[0]).order_by(Evidence.id)).all()
        assert [(e.checkpoint_id, e.result, e.score) for e in evs] == [
            ("L.G1.vyanjan", "correct", 1.0), ("L.G1.read_matra_words", "incorrect", 0.0)]
        assert all(e.source == "guided_probe" and e.status == "confirmed" and e.confidence == 1.0
                   and e.created_by == sa["teacher_id"] for e in evs)
        rows = db.scalars(select(LevelCheck).where(LevelCheck.child_id == ids[0])).all()
        assert [(x.subject, x.level_index, x.level_key, x.class_id) for x in rows] == [("literacy", 0, "letter", cid)]


def test_beginner_and_all_pass(client, sa):
    cid, ids = _class(client, sa)
    r = _post(client, sa, cid, ids[0], [("num_1_9", False)], subject="numeracy")
    assert r.status_code == 200 and r.json()["level_index"] == -1 and r.json()["level_key"] == "beginner"
    keys = [lv["key"] for lv in lc.ladder("numeracy")["levels"]]
    r = _post(client, sa, cid, ids[1], [(k, True) for k in keys], subject="numeracy")
    assert r.status_code == 200 and r.json() == {"level_index": 4, "level_key": "mult",
                                                 "title_en": "Multiplication", "title_hi": "गुणा"}


def test_post_stop_rule_violations_are_422_and_write_nothing(client, sa):
    cid, ids = _class(client, sa)
    for results in ([("word", True)], [("letter", True), ("sentence", False)],
                    [("letter", False), ("word", True)], []):
        assert _post(client, sa, cid, ids[0], results).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Evidence.id)).where(Evidence.child_id == ids[0])) == 0
        assert db.scalar(select(func.count(LevelCheck.id)).where(LevelCheck.child_id == ids[0])) == 0


def test_client_uuid_replay_writes_once(client, sa):
    cid, ids = _class(client, sa)
    u = uuid.uuid4().hex
    a = _post(client, sa, cid, ids[0], [("letter", True), ("word", True), ("sentence", False)], client_uuid=u)
    b = _post(client, sa, cid, ids[0], [("letter", True), ("word", True), ("sentence", False)], client_uuid=u)
    assert a.status_code == b.status_code == 200 and a.json() == b.json() and a.json()["level_key"] == "word"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Evidence.id)).where(Evidence.child_id == ids[0])) == 3
        assert db.scalar(select(func.count(LevelCheck.id)).where(LevelCheck.child_id == ids[0])) == 1
    # the replay marker stays out of the AI guardrail counters
    assert client.get("/v1/ai_activity", headers=sa["headers"]).json()["captures"] == 0


def test_summary_first_latest_moved_up(client, sa):
    cid, ids = _class(client, sa, children=4)
    _post(client, sa, cid, ids[0], [("letter", False)])                                  # beginner
    _post(client, sa, cid, ids[0], [("letter", True), ("word", True), ("sentence", False)])  # → word
    _post(client, sa, cid, ids[1], [("letter", True), ("word", False)])                  # letter only
    _post(client, sa, cid, ids[2], [("letter", True), ("word", True), ("sentence", False)])  # word
    _post(client, sa, cid, ids[2], [("letter", True), ("word", False)])                  # → letter (down)
    j = client.get(f"/v1/classes/{cid}/level_check", params={"subject": "literacy"}, headers=sa["headers"]).json()
    by = {c["child_id"]: c for c in j["children"]}
    assert by[ids[0]]["first"]["level_key"] == "beginner" and by[ids[0]]["latest"]["level_index"] == 1
    assert by[ids[1]]["first"] == by[ids[1]]["latest"]
    assert by[ids[3]]["first"] is None and by[ids[3]]["latest"] is None
    s = j["summary"]
    assert (s["total"], s["checked"], s["moved_up"]) == (4, 3, 1)
    assert s["first"] == {"beginner": 1, "letter": 1, "word": 1, "sentence": 0, "story": 0}
    assert s["latest"] == {"beginner": 0, "letter": 2, "word": 1, "sentence": 0, "story": 0}
    # the numeracy ladder is separate
    n = client.get(f"/v1/classes/{cid}/level_check", params={"subject": "numeracy"}, headers=sa["headers"]).json()
    assert n["summary"]["checked"] == 0


def test_child_must_be_in_the_class(client, sa):
    cid, ids = _class(client, sa)
    other, oids = _class(client, sa)
    assert _post(client, sa, cid, oids[0], [("letter", True)]).status_code == 422


def test_tenant_isolation(client, sa, sb):
    cid, ids = _class(client, sa)
    assert client.get(f"/v1/classes/{cid}/level_check", params={"subject": "literacy"},
                      headers=sb["headers"]).status_code == 404
    assert _post(client, sb, cid, ids[0], [("letter", True)]).status_code == 404
    bcid, _ = _class(client, sb)
    assert _post(client, sb, bcid, ids[0], [("letter", True)]).status_code == 404  # child of another school


def test_demo_seed_gives_moved_up(client):
    s = _school("Demo Seed School")
    with SessionLocal() as db:
        cls = Classroom(school_id=s["school_id"], teacher_id=s["teacher_id"], grade=2, section="A", label="2A")
        db.add(cls)
        db.flush()
        for i in range(1, 31):
            db.add(Child(class_id=cls.id, roll_no=i, first_name=f"Bachcha{i}"))
        db.flush()
        n = lc.demo_seed(db, s["school_id"])
        assert n > 0
        assert lc.demo_seed(db, s["school_id"]) == 0  # idempotent
        db.commit()
        cid = cls.id
    for subject in ("literacy", "numeracy"):
        j = client.get(f"/v1/classes/{cid}/level_check", params={"subject": subject}, headers=s["headers"]).json()
        assert j["summary"]["moved_up"] > 0 and 0 < j["summary"]["checked"] < j["summary"]["total"], j["summary"]
    with SessionLocal() as db:
        lc.delete_for_school(db, s["school_id"])
        db.commit()
        assert db.scalar(select(func.count(LevelCheck.id)).where(LevelCheck.school_id == s["school_id"])) == 0
