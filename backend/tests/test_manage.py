"""Correcting mistakes: evidence undo/restore, student edit/remove/restore, topic rename, syllabus reorder.

Runs in schools made here, so the seeded DEMO data other tests count on is never changed.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import Evidence, School, Teacher
from app.services import ledger
from app.services.content import get_content


def _school(name: str) -> dict:
    with SessionLocal() as db:
        school = School(name=name, code="MG" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="Manage Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.commit()
        return {"school_id": school.id, "teacher_id": t.id,
                "headers": {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}}


@pytest.fixture(scope="module")
def sa():
    return _school("Manage School")


@pytest.fixture(scope="module")
def sb():
    return _school("Manage Other School")


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


def _tap(client, s, cid, child, cp, result):
    r = client.post(f"/v1/classes/{cid}/captures/tap", headers=s["headers"],
                    json={"items": [{"child_id": child, "checkpoint_id": cp, "result": result}]})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        return db.scalar(select(Evidence.id).where(Evidence.child_id == child).order_by(Evidence.id.desc()))


def _status(child, cp):
    with SessionLocal() as db:
        r = ledger.child_statuses(db, [child])[child].get(cp)
        return r.status if r else "not_started"


# ------------------------------------------------------------------ undo / restore
def test_undo_restore_state_machine_changes_status(client, sa):
    cid, ids = _class(client, sa)
    cp = "N.G2.sub_2digit_borrow"
    ev = _tap(client, sa, cid, ids[0], cp, "incorrect")
    assert _status(ids[0], cp) == "needs_intervention"
    r = client.post(f"/v1/evidence/{ev}/undo", headers=sa["headers"])
    assert r.status_code == 200 and r.json() == {"id": ev, "status": "rejected"}
    assert _status(ids[0], cp) == "not_started"
    assert client.post(f"/v1/evidence/{ev}/undo", headers=sa["headers"]).status_code == 409
    r = client.post(f"/v1/evidence/{ev}/restore", headers=sa["headers"])
    assert r.status_code == 200 and r.json() == {"id": ev, "status": "confirmed"}
    assert _status(ids[0], cp) == "needs_intervention"
    assert client.post(f"/v1/evidence/{ev}/restore", headers=sa["headers"]).status_code == 409
    assert client.post("/v1/evidence/999999999/undo", headers=sa["headers"]).status_code == 404


def test_proposed_evidence_cannot_be_undone(client, sa):
    cid, ids = _class(client, sa)
    with SessionLocal() as db:
        ev = Evidence(school_id=sa["school_id"], class_id=cid, child_id=ids[0], checkpoint_id="N.G1.add_single",
                      result="correct", source="teacher_note", status="proposed")
        db.add(ev)
        db.commit()
        eid = ev.id
    assert client.post(f"/v1/evidence/{eid}/undo", headers=sa["headers"]).status_code == 409
    assert client.post(f"/v1/evidence/{eid}/restore", headers=sa["headers"]).status_code == 409


# ------------------------------------------------------------------ edit students
def test_edit_name_roll_and_clash(client, sa):
    cid, ids = _class(client, sa)
    r = client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"], json={"first_name": "  मीना  "})
    assert r.status_code == 200
    assert r.json() == {"id": ids[0], "first_name": "मीना", "roll_no": 1, "class_id": cid, "active": True}
    assert client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"],
                       json={"first_name": "   "}).status_code == 422
    assert client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"],
                       json={"roll_no": 2}).status_code == 409
    r = client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"], json={"roll_no": 40})
    assert r.status_code == 200 and r.json()["roll_no"] == 40
    # same roll number again is not a clash with itself
    assert client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"], json={"roll_no": 40}).status_code == 200


def test_move_class(client, sa, sb):
    cid, ids = _class(client, sa)
    other, oids = _class(client, sa, children=2)  # rolls 1, 2 taken there
    assert client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"],
                       json={"class_id": other}).status_code == 409
    r = client.post(f"/v1/children/{ids[0]}/edit", headers=sa["headers"], json={"class_id": other, "roll_no": 9})
    assert r.status_code == 200 and r.json()["class_id"] == other and r.json()["roll_no"] == 9
    roster = client.get(f"/v1/classes/{other}/roster", headers=sa["headers"]).json()
    assert ids[0] in {c["id"] for c in roster}
    bcid, _ = _class(client, sb, children=0)
    assert client.post(f"/v1/children/{ids[1]}/edit", headers=sa["headers"],
                       json={"class_id": bcid}).status_code == 404


def test_deactivate_inactive_list_and_restore(client, sa):
    cid, ids = _class(client, sa)
    r = client.post(f"/v1/children/{ids[1]}/edit", headers=sa["headers"], json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert ids[1] not in {c["id"] for c in client.get(f"/v1/classes/{cid}/roster", headers=sa["headers"]).json()}
    inactive = client.get(f"/v1/classes/{cid}/children/inactive", headers=sa["headers"]).json()
    assert inactive == [{"id": ids[1], "first_name": "Bachcha2", "roll_no": 2}]
    assert client.post(f"/v1/children/{ids[1]}/edit", headers=sa["headers"], json={"active": True}).json()["active"]
    assert client.get(f"/v1/classes/{cid}/children/inactive", headers=sa["headers"]).json() == []
    assert ids[1] in {c["id"] for c in client.get(f"/v1/classes/{cid}/roster", headers=sa["headers"]).json()}


# ------------------------------------------------------------------ topics
def _custom_topic(client, s, cid, title="Paise ginna"):
    r = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=s["headers"],
                    json={"subject": "numeracy", "chapter": "Paise", "title": title})
    assert r.status_code == 200, r.text
    return r.json()["checkpoint_id"]


def _topics(syl):
    return [(t["checkpoint_id"], ch["chapter"], t) for ch in syl["chapters"] for t in ch["topics"]]


def test_rename_custom_topic(client, sa, sb):
    cid, _ = _class(client, sa, children=0)
    tid = _custom_topic(client, sa, cid)
    url = f"/v1/classes/{cid}/syllabus/topics/{tid}/rename"
    r = client.post(url, headers=sa["headers"], json={"subject": "numeracy", "title_en": "Counting coins",
                                                      "title_hi": "सिक्के गिनना"})
    assert r.status_code == 200, r.text
    t = next(t for cpid, _, t in _topics(r.json()) if cpid == tid)
    assert (t["title_en"], t["title_hi"], t["custom"]) == ("Counting coins", "सिक्के गिनना", True)
    assert get_content().checkpoints[tid].title_en == "Counting coins"  # re-registered in the cache
    r = client.post(url, headers=sa["headers"], json={"subject": "numeracy", "title_hi": "रुपये गिनना"})
    t = next(t for cpid, _, t in _topics(r.json()) if cpid == tid)
    assert (t["title_en"], t["title_hi"]) == ("Counting coins", "रुपये गिनना")
    assert client.post(url, headers=sa["headers"], json={"subject": "numeracy"}).status_code == 422
    assert client.post(url, headers=sa["headers"], json={"subject": "numeracy", "title_en": " "}).status_code == 422
    lib = client.post(f"/v1/classes/{cid}/syllabus/topics/N.G2.sub_2digit_borrow/rename", headers=sa["headers"],
                      json={"subject": "numeracy", "title_en": "x"})
    assert lib.status_code == 422 and "library" in lib.json()["detail"]
    # another school can't rename it, even through its own class
    bcid, _ = _class(client, sb, children=0)
    assert client.post(f"/v1/classes/{bcid}/syllabus/topics/{tid}/rename", headers=sb["headers"],
                       json={"subject": "numeracy", "title_en": "x"}).status_code == 404
    assert client.post(url, headers=sb["headers"], json={"subject": "numeracy", "title_en": "x"}).status_code == 404


def test_reorder_keeps_chapters(client, sa):
    cid, _ = _class(client, sa, children=0)
    before = client.get(f"/v1/classes/{cid}/syllabus", params={"subject": "numeracy"}, headers=sa["headers"]).json()
    rows = _topics(before)
    assert len(rows) >= 3
    chapter_of = {cpid: ch for cpid, ch, _ in rows}
    order = [cpid for cpid, _, _ in rows][::-1]
    r = client.post(f"/v1/classes/{cid}/syllabus/reorder", headers=sa["headers"],
                    json={"subject": "numeracy", "order": order})
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["confirmed"] and after["version"] == (before["version"] or 0) + 1
    got = sorted(_topics(after), key=lambda x: x[2]["position"])
    assert [cpid for cpid, _, _ in got] == order
    assert all(chapter_of[cpid] == ch for cpid, ch, _ in got)
    assert client.get(f"/v1/classes/{cid}/syllabus", params={"subject": "numeracy"},
                      headers=sa["headers"]).json() == after
    bad = client.post(f"/v1/classes/{cid}/syllabus/reorder", headers=sa["headers"],
                      json={"subject": "numeracy", "order": order[:-1]})
    assert bad.status_code == 422
    dup = client.post(f"/v1/classes/{cid}/syllabus/reorder", headers=sa["headers"],
                      json={"subject": "numeracy", "order": order[:-1] + [order[0]]})
    assert dup.status_code == 422
    extra = client.post(f"/v1/classes/{cid}/syllabus/reorder", headers=sa["headers"],
                        json={"subject": "numeracy", "order": order + ["L.G1.swar"]})
    assert extra.status_code == 422


# ------------------------------------------------------------------ tenant isolation
def test_tenant_isolation(client, sa, sb):
    cid, ids = _class(client, sa)
    ev = _tap(client, sa, cid, ids[0], "N.G1.add_single", "correct")
    h = sb["headers"]
    assert client.post(f"/v1/evidence/{ev}/undo", headers=h).status_code == 404
    assert client.post(f"/v1/evidence/{ev}/restore", headers=h).status_code == 404
    assert client.post(f"/v1/children/{ids[0]}/edit", headers=h, json={"first_name": "x"}).status_code == 404
    assert client.get(f"/v1/classes/{cid}/children/inactive", headers=h).status_code == 404
    assert client.post(f"/v1/classes/{cid}/syllabus/reorder", headers=h,
                       json={"subject": "numeracy", "order": []}).status_code == 404
    with SessionLocal() as db:
        assert db.get(Evidence, ev).status == "confirmed"
