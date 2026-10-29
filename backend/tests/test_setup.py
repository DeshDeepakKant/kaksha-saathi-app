"""Teacher setup: classes, subjects, syllabus coverage, custom topics as real checkpoints.

Classes, subjects and topics are created in a second school made here, so the seeded DEMO data
other tests count on is never changed. Names are unique per run; tests don't depend on order.
"""
import uuid

import pytest

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import School, Teacher
from app.services.content import Content, get_content, load_custom_checkpoints

STATUSES = ("on_track", "needs_practice", "needs_intervention", "not_started")


@pytest.fixture(scope="module")
def sb():
    """A second school with one teacher; returns its auth headers, school id and a class factory."""
    with SessionLocal() as db:
        school = School(name="Setup Test School", code="ST" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="Setup Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.commit()
        sid, tid = school.id, t.id
    return {"school_id": sid, "headers": {"Authorization": f"Bearer {make_token(str(tid), 'teacher')}"}}


def _class(client, sb, grade, section=None, children=0):
    section = section or uuid.uuid4().hex[:6].upper()
    r = client.post("/v1/classes", headers=sb["headers"], json={"grade": grade, "section": section})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    ids = []
    for n in range(1, children + 1):
        c = client.post(f"/v1/classes/{cid}/children", headers=sb["headers"],
                        json={"first_name": f"Bachcha{n}", "roll_no": n, "consent_source": "form"})
        assert c.status_code == 200, c.text
        ids.append(c.json()["id"])
    return cid, ids


# ------------------------------------------------------------------ classes
def test_create_class_defaults_and_listing(client, sb):
    r = client.post("/v1/classes", headers=sb["headers"], json={"grade": 4, "section": "q"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j == {"id": j["id"], "label": "कक्षा 4Q", "grade": 4, "section": "Q", "children": 0, "consented": 0}
    mine = client.get("/v1/classes", headers=sb["headers"]).json()
    assert j["id"] in {c["id"] for c in mine}
    # a custom label is kept
    r2 = client.post("/v1/classes", headers=sb["headers"], json={"grade": 4, "section": "R", "label": "Sunflowers"})
    assert r2.json()["label"] == "Sunflowers"


def test_create_class_duplicate_is_409(client, sb):
    body = {"grade": 5, "section": "Dup"}
    assert client.post("/v1/classes", headers=sb["headers"], json=body).status_code == 200
    assert client.post("/v1/classes", headers=sb["headers"], json=body).status_code == 409
    # the section is normalised, so a different case is the same class
    assert client.post("/v1/classes", headers=sb["headers"], json={"grade": 5, "section": "dup"}).status_code == 409


@pytest.mark.parametrize("body", [
    {"grade": 0, "section": "A"}, {"grade": 9, "section": "A"}, {"grade": 3, "section": ""},
    {"grade": 3, "section": "   "}, {"grade": 3, "section": "ABCDEFGHI"}, {"grade": "x", "section": "A"},
    {"section": "A"}, {"grade": 3, "section": "A", "label": "x" * 41},
])
def test_create_class_bad_input_is_422(client, sb, body):
    assert client.post("/v1/classes", headers=sb["headers"], json=body).status_code == 422


def test_setup_routes_need_a_teacher_token(client):
    assert client.post("/v1/classes", json={"grade": 2, "section": "A"}).status_code == 401
    assert client.post("/v1/subjects", json={"name": "x"}).status_code == 401
    assert client.get("/v1/classes/1/syllabus?subject=numeracy").status_code == 401


def test_tenancy_other_schools_class_is_404(client, sb, teacher_headers):
    cid, _ = _class(client, sb, 2)
    # the DEMO teacher cannot touch school B's class, and school B cannot touch DEMO's class 1
    for h, c in ((teacher_headers, cid), (sb["headers"], 1)):
        assert client.get(f"/v1/classes/{c}/subjects", headers=h).status_code == 404
        assert client.get(f"/v1/classes/{c}/syllabus?subject=numeracy", headers=h).status_code == 404
        assert client.post(f"/v1/classes/{c}/syllabus", headers=h, json={
            "subject": "numeracy", "items": [{"custom_title": "x"}]}).status_code == 404
        assert client.post(f"/v1/classes/{c}/syllabus/topics", headers=h, json={
            "subject": "numeracy", "chapter": "c", "title": "t"}).status_code == 404
        assert client.delete(f"/v1/classes/{c}/syllabus/topics/x?subject=numeracy", headers=h).status_code == 404


# ------------------------------------------------------------------ subjects
def test_subjects_lists_builtins_first(client, sb):
    cid, _ = _class(client, sb, 3)
    name = "Art " + uuid.uuid4().hex[:5]
    k = client.post("/v1/subjects", headers=sb["headers"], json={"name": name, "name_hi": "कला"}).json()
    subs = client.get(f"/v1/classes/{cid}/subjects", headers=sb["headers"]).json()
    assert [s["key"] for s in subs[:2]] == ["numeracy", "literacy"]
    assert subs[0]["name_en"] == "Maths" and subs[1]["name_hi"] == "हिन्दी"
    assert all(s["builtin"] for s in subs[:2])
    mine = next(s for s in subs if s["key"] == k["key"])
    assert mine == {"key": k["key"], "name_en": name, "name_hi": "कला", "builtin": False, "topics": 0}
    assert subs[0]["topics"] > 5  # built-in subject counts its template topics for a grade 3 class


def test_add_subject_key_rules(client, sb):
    h = sb["headers"]
    tag = uuid.uuid4().hex[:4]
    r = client.post("/v1/subjects", headers=h, json={"name": f"Science {tag}"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["key"] == f"science_{tag}" and j["builtin"] is False and j["name_hi"] == f"Science {tag}"
    # same name again, in any case: 409
    assert client.post("/v1/subjects", headers=h, json={"name": f"SCIENCE {tag}"}).status_code == 409
    # built-in names and aliases are taken
    for n in ("Maths", "Hindi", "numeracy", "math", "Literacy"):
        assert client.post("/v1/subjects", headers=h, json={"name": n}).status_code == 409, n
    # a long name is cut to 16 chars; two names with the same slug get distinct keys
    a = client.post("/v1/subjects", headers=h, json={"name": f"Environmental Studies {tag} one"}).json()
    b = client.post("/v1/subjects", headers=h, json={"name": f"Environmental Studies {tag} two"}).json()
    assert len(a["key"]) <= 16 and len(b["key"]) <= 16 and a["key"] != b["key"]
    # a name with no Latin letters still gets a valid key
    c = client.post("/v1/subjects", headers=h, json={"name": "संगीत", "name_hi": "संगीत"}).json()
    assert c["key"].startswith("s_") and len(c["key"]) <= 16
    # bad input
    assert client.post("/v1/subjects", headers=h, json={"name": ""}).status_code == 422
    assert client.post("/v1/subjects", headers=h, json={"name": "   "}).status_code == 422
    assert client.post("/v1/subjects", headers=h, json={"name": "x" * 61}).status_code == 422


def test_subject_keys_are_per_school(client, sb, teacher_headers):
    tag = uuid.uuid4().hex[:4]
    client.post("/v1/subjects", headers=sb["headers"], json={"name": f"Only B {tag}"})
    cid, _ = _class(client, sb, 2)
    assert client.get(f"/v1/classes/{cid}/syllabus?subject=only_b_{tag}", headers=sb["headers"]).status_code == 200
    # unknown to the DEMO school: the existing subject gate says 422
    assert client.get(f"/v1/classes/1/board?subject=only_b_{tag}", headers=teacher_headers).status_code == 422
    assert client.get(f"/v1/classes/1/syllabus?subject=only_b_{tag}", headers=teacher_headers).status_code == 422


# ------------------------------------------------------------------ syllabus coverage (seeded 2A numeracy)
def test_syllabus_shape_and_counts_match_seed(client, teacher_headers):
    r = client.get("/v1/classes/1/syllabus?subject=numeracy", headers=teacher_headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["subject"] == "numeracy" and s["confirmed"] is True and s["version"] >= 1
    assert s["children"] == 30 and s["chapters"] and s["totals"]["topics"] > 10
    # independent tally from each child's profile
    roster = client.get("/v1/classes/1/roster", headers=teacher_headers).json()
    tally = {}
    for ch in roster:
        p = client.get(f"/v1/children/{ch['id']}/profile?subject=numeracy", headers=teacher_headers).json()
        for it in p["items"]:
            tally.setdefault(it["checkpoint_id"], dict.fromkeys(STATUSES, 0))[it["status"]] += 1
    positions, n_topics = [], 0
    for chap in s["chapters"]:
        assert chap["totals"]["topics"] == len(chap["topics"])
        for t in chap["topics"]:
            n_topics += 1
            positions.append(t["position"])
            assert {"checkpoint_id", "title_hi", "title_en", "custom", "nipun_ref", "position", "total",
                    "assessed", "counts", "pct_done"} <= set(t)
            assert t["custom"] is False and t["total"] == 30
            assert t["counts"] == tally[t["checkpoint_id"]], t["checkpoint_id"]
            assert t["assessed"] == 30 - t["counts"]["not_started"]
            assert t["pct_done"] == pytest.approx(t["counts"]["on_track"] / 30, abs=1e-3)
    assert n_topics == s["totals"]["topics"] and positions == sorted(positions)
    assert sum(s["totals"]["counts"].values()) == 30 * n_topics
    # the seeded story: some children have gaps, some are on track
    assert s["totals"]["counts"]["on_track"] > 0
    assert s["totals"]["counts"]["needs_practice"] + s["totals"]["counts"]["needs_intervention"] > 0


def test_syllabus_validates_subject_and_args(client, teacher_headers):
    assert client.get("/v1/classes/1/syllabus?subject=nope", headers=teacher_headers).status_code == 422
    assert client.get("/v1/classes/1/syllabus", headers=teacher_headers).status_code == 422
    assert client.get("/v1/classes/1/syllabus?subject=maths", headers=teacher_headers).json()["subject"] == "numeracy"


# ------------------------------------------------------------------ add / delete custom topics
def test_template_roadmap_is_materialised_on_first_topic(client, sb):
    h = sb["headers"]
    cid, kids = _class(client, sb, 2, children=3)
    before = client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=h).json()
    assert before["confirmed"] is False and before["version"] is None and before["source"] == "template"
    n = before["totals"]["topics"]
    assert n > 5 and before["children"] == 3
    chapter = before["chapters"][0]["chapter"]
    last_in_chapter = before["chapters"][0]["topics"][-1]["position"]
    t = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                    json={"subject": "numeracy", "chapter": chapter, "title": "Rangoli patterns"})
    assert t.status_code == 200, t.text
    t = t.json()
    assert t["checkpoint_id"] == f"C{sb['school_id']}-1" or t["checkpoint_id"].startswith(f"C{sb['school_id']}-")
    assert t["custom"] is True and t["title_en"] == "Rangoli patterns" and t["title_hi"] == "Rangoli patterns"
    assert t["total"] == 3 and t["counts"] == {"on_track": 0, "needs_practice": 0, "needs_intervention": 0,
                                               "not_started": 3}
    assert t["assessed"] == 0 and t["pct_done"] == 0.0 and t["nipun_ref"] == ""
    assert t["position"] == last_in_chapter + 1  # slotted at the end of its chapter
    after = client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=h).json()
    assert after["confirmed"] is True and after["version"] == 1 and after["totals"]["topics"] == n + 1
    assert after["chapters"][0]["topics"][-1]["checkpoint_id"] == t["checkpoint_id"]
    # the template items survived and the board / roadmap routes see the same list
    rm = client.get(f"/v1/classes/{cid}/roadmap?subject=numeracy", headers=h).json()
    assert rm["confirmed"] is True and len(rm["items"]) == n + 1
    # a second add makes version 2; a new chapter goes to the end
    t2 = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                     json={"subject": "numeracy", "chapter": "My new chapter", "title": "Topic two",
                           "title_hi": "विषय दो"}).json()
    assert t2["title_hi"] == "विषय दो" and t2["position"] == n + 1
    assert client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=h).json()["version"] == 2


def test_delete_topic_and_unknown_is_404(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 3, children=2)
    t = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                    json={"subject": "literacy", "chapter": "Poems", "title": "Poem recital"}).json()
    s = client.get(f"/v1/classes/{cid}/syllabus?subject=literacy", headers=h).json()
    n = s["totals"]["topics"]
    d = client.delete(f"/v1/classes/{cid}/syllabus/topics/{t['checkpoint_id']}?subject=literacy", headers=h)
    assert d.status_code == 200, d.text
    ids = [x["checkpoint_id"] for c in d.json()["chapters"] for x in c["topics"]]
    assert t["checkpoint_id"] not in ids and d.json()["totals"]["topics"] == n - 1
    assert client.delete(f"/v1/classes/{cid}/syllabus/topics/{t['checkpoint_id']}?subject=literacy",
                         headers=h).status_code == 404
    # a built-in topic can be dropped from a class syllabus too
    first = ids[0]
    assert client.delete(f"/v1/classes/{cid}/syllabus/topics/{first}?subject=literacy",
                         headers=h).json()["totals"]["topics"] == n - 2
    # the checkpoint row survives, so earlier evidence still resolves
    assert t["checkpoint_id"] in get_content().checkpoints
    assert client.delete(f"/v1/classes/{cid}/syllabus/topics/{t['checkpoint_id']}", headers=h).status_code == 422


def test_topic_input_limits(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 2)
    base = {"subject": "numeracy", "chapter": "c", "title": "t"}
    for bad in ({**base, "title": ""}, {**base, "title": "x" * 121}, {**base, "chapter": ""},
                {**base, "chapter": "x" * 121}, {**base, "title": "   "}, {**base, "subject": "nope"},
                {**base, "title_hi": "x" * 121}, {"subject": "numeracy"}):
        assert client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h, json=bad).status_code == 422, bad
    assert client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                       json={**base, "title": "x" * 120}).status_code == 200


def test_save_syllabus_import(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 4, children=2)
    tag = uuid.uuid4().hex[:4]
    sub = client.post("/v1/subjects", headers=h, json={"name": f"EVS {tag}"}).json()["key"]
    body = {"subject": sub, "source": "import", "items": [
        {"custom_title": "Plants", "chapter": "Living things", "position": 1},
        {"custom_title": "Animals", "custom_title_hi": "जानवर", "chapter": "Living things", "position": 0},
        {"custom_title": "Water", "chapter": "Resources", "position": 2},
    ]}
    r = client.post(f"/v1/classes/{cid}/syllabus", headers=h, json=body)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["confirmed"] is True and s["version"] == 1 and s["source"] == "import" and s["children"] == 2
    assert [c["chapter"] for c in s["chapters"]] == ["Living things", "Resources"]
    first = s["chapters"][0]["topics"]
    assert [t["title_en"] for t in first] == ["Animals", "Plants"] and first[0]["title_hi"] == "जानवर"
    assert all(t["custom"] and t["position"] == i for i, t in enumerate(first))
    # resubmitting with ids keeps the topics and makes version 2 (no duplicates created)
    items = [{"checkpoint_id": t["checkpoint_id"], "position": t["position"]}
             for c in s["chapters"] for t in c["topics"]]
    r2 = client.post(f"/v1/classes/{cid}/syllabus", headers=h, json={"subject": sub, "source": "photo",
                                                                      "items": items + items[:1]})
    assert r2.status_code == 200 and r2.json()["version"] == 2 and r2.json()["totals"]["topics"] == 3
    assert [t["checkpoint_id"] for c in r2.json()["chapters"] for t in c["topics"]] == [i["checkpoint_id"] for i in items]
    # a built-in topic can be mixed in (id kept, chapter from the graph)
    tmpl = client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=h).json()
    cp0 = tmpl["chapters"][0]["topics"][0]["checkpoint_id"]
    m = client.post(f"/v1/classes/{cid}/syllabus", headers=h, json={
        "subject": "numeracy", "items": [{"checkpoint_id": cp0}, {"custom_title": "Mental maths"}]}).json()
    assert m["totals"]["topics"] == 2 and m["chapters"][0]["topics"][0]["custom"] is False
    assert m["chapters"][-1]["chapter"] == "अन्य"


def test_save_syllabus_rejects_bad_input(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 2)
    other_cid, _ = _class(client, sb, 2)
    ok = {"custom_title": "x"}
    cases = [
        {"subject": "numeracy", "items": []},
        {"subject": "numeracy", "items": [ok] * 81},
        {"subject": "numeracy", "items": [{"custom_title": "x" * 121}]},
        {"subject": "numeracy", "items": [{"custom_title": "  "}]},
        {"subject": "numeracy", "items": [{"position": 1}]},
        {"subject": "numeracy", "items": [{"checkpoint_id": "N.nope"}]},
        {"subject": "numeracy", "items": [{"checkpoint_id": "L.G1.swar"}]},  # wrong subject
        {"subject": "numeracy", "items": [{"checkpoint_id": "C999999-1"}]},   # other school's id shape
        {"subject": "numeracy", "source": "magic", "items": [ok]},
        {"subject": "unknown", "items": [ok]},
        {"items": [ok]},
        {"subject": "numeracy", "items": "nope"},
    ]
    for body in cases:
        r = client.post(f"/v1/classes/{cid}/syllabus", headers=h, json=body)
        assert r.status_code == 422, (body, r.status_code, r.text)
    assert client.post(f"/v1/classes/{cid}/syllabus", headers=h,
                       json={"subject": "numeracy", "items": [ok] * 80}).status_code == 200
    # a rejected request leaves no half-written roadmap behind
    assert client.get(f"/v1/classes/{other_cid}/syllabus?subject=numeracy", headers=h).json()["confirmed"] is False
    # another school's custom topic id cannot be smuggled in
    topic = client.get(f"/v1/classes/{cid}/syllabus?subject=numeracy", headers=h).json()["chapters"][0]["topics"][0]
    with SessionLocal() as db:
        s2 = School(name="Other", code="OT" + uuid.uuid4().hex[:8].upper())
        db.add(s2)
        db.commit()
        other_school = s2.id
    assert other_school != sb["school_id"]
    foreign = f"C{other_school}-1"
    from app.models.tables import CustomCheckpoint
    from app.services.coverage import register
    row = CustomCheckpoint(id=foreign, school_id=other_school, subject="numeracy", grade=2, chapter="c",
                           title_en="foreign", title_hi="foreign")
    with SessionLocal() as db:
        db.add(row)
        db.commit()
    register(row)
    r = client.post(f"/v1/classes/{cid}/syllabus", headers=h,
                    json={"subject": "numeracy", "items": [{"checkpoint_id": foreign}]})
    assert r.status_code == 422 and topic


def test_custom_topics_do_not_leak_into_other_classes_templates(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 2)
    other, _ = _class(client, sb, 2)
    t = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                    json={"subject": "numeracy", "chapter": "c", "title": "only here"}).json()
    s = client.get(f"/v1/classes/{other}/syllabus?subject=numeracy", headers=h).json()
    assert t["checkpoint_id"] not in [x["checkpoint_id"] for c in s["chapters"] for x in c["topics"]]
    content = get_content()
    assert t["checkpoint_id"] in content.custom_ids
    assert all(i["checkpoint_id"] not in content.custom_ids for i in content.template_roadmap("numeracy", 2))
    assert all(c.id not in content.custom_ids for c in content.for_grade("numeracy", 2))


# ------------------------------------------------------------------ custom subject, end to end
def test_custom_subject_end_to_end(client, sb):
    h = sb["headers"]
    cid, kids = _class(client, sb, 3, children=6)
    tag = uuid.uuid4().hex[:4]
    key = client.post("/v1/subjects", headers=h, json={"name": f"Gardening {tag}"}).json()["key"]
    topics = []
    for title in ("Seeds", "Watering", "Compost"):
        r = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                        json={"subject": key, "chapter": "Garden", "title": title})
        assert r.status_code == 200, r.text
        topics.append(r.json()["checkpoint_id"])
    # tap: all six children are weak on Seeds, two are fine on Watering, one on Compost
    items = [{"child_id": k, "checkpoint_id": topics[0], "result": "incorrect"} for k in kids]
    items += [{"child_id": k, "checkpoint_id": topics[1], "result": "correct"} for k in kids[:2]]
    items += [{"child_id": kids[0], "checkpoint_id": topics[2], "result": "correct"}]
    r = client.post(f"/v1/classes/{cid}/captures/tap", headers=h, json={"items": items})
    assert r.status_code == 200 and r.json()["committed"] == len(items), r.text

    s = client.get(f"/v1/classes/{cid}/syllabus?subject={key}", headers=h).json()
    by = {t["checkpoint_id"]: t for c in s["chapters"] for t in c["topics"]}
    assert by[topics[0]]["counts"]["on_track"] == 0 and by[topics[0]]["assessed"] == 6
    assert by[topics[0]]["counts"]["not_started"] == 0
    assert by[topics[1]]["counts"]["on_track"] + by[topics[1]]["counts"]["needs_practice"] == 2
    assert by[topics[1]]["counts"]["not_started"] == 4 and by[topics[2]]["assessed"] == 1

    board = client.get(f"/v1/classes/{cid}/board?subject={key}", headers=h)
    assert board.status_code == 200, board.text
    b = board.json()
    assert [g["key"] for g in b["groups"]] == [topics[0]] and len(b["groups"][0]["members"]) == 6
    assert b["groups"][0]["title_en"] == "Seeds"

    plan = client.post(f"/v1/classes/{cid}/plans?subject={key}", headers=h)
    assert plan.status_code == 200, plan.text
    p = plan.json()
    g = p["groups"][0]
    # no reviewed activity exists for a custom topic: the plan falls back to the generic template
    assert p["generated_by"] == "fallback" and g["key"] == topics[0] and g["activity"] is None
    assert g["activity_id"] == "generic" and g["generic_steps_hi"] and g["time_min"] >= 5
    again = client.get(f"/v1/classes/{cid}/plans/latest?subject={key}", headers=h).json()
    assert again["exists"] is True and again["groups"][0]["key"] == topics[0]

    prof = client.get(f"/v1/children/{kids[0]}/profile?subject={key}", headers=h)
    assert prof.status_code == 200, prof.text
    items = {i["checkpoint_id"]: i for i in prof.json()["items"]}
    assert set(items) == set(topics) and items[topics[0]]["title_en"] == "Seeds"
    assert items[topics[0]]["status"] in ("needs_practice", "needs_intervention")
    assert items[topics[2]]["evidence_count"] == 1

    # the other routes that take a subject accept it too
    assert client.get(f"/v1/classes/{cid}/roadmap?subject={key}", headers=h).status_code == 200
    # a tap on a topic of a different school-less id is still rejected, as before
    assert client.post(f"/v1/classes/{cid}/captures/tap", headers=h, json={
        "items": [{"child_id": kids[0], "checkpoint_id": "C0-0", "result": "correct"}]}).status_code == 422


# ------------------------------------------------------------------ startup reload
def test_startup_loader_rebuilds_custom_checkpoints(client, sb):
    h = sb["headers"]
    cid, _ = _class(client, sb, 5)
    t = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                    json={"subject": "literacy", "chapter": "Stories", "title": "Retell a story",
                          "title_hi": "कहानी सुनाओ"}).json()["checkpoint_id"]
    fresh = Content(checkpoints={}, activities={}, practice_items=[], probes={})
    assert load_custom_checkpoints(fresh) >= 1
    cp = fresh.checkpoints[t]
    assert t in fresh.custom_ids
    assert (cp.subject, cp.grade, cp.chapter, cp.title_en, cp.title_hi) == ("literacy", 5, "Stories",
                                                                          "Retell a story", "कहानी सुनाओ")
    assert cp.prereqs == () and cp.misconceptions == () and cp.item_types == ()
    assert cp.assess_via == ("teacher_tap",) and cp.nipun_ref == "" and cp.language == "hi"
    assert fresh.descendants_ok()
    # ids are per school and never reused after a topic is removed from the syllabus
    client.delete(f"/v1/classes/{cid}/syllabus/topics/{t}?subject=literacy", headers=h)
    t2 = client.post(f"/v1/classes/{cid}/syllabus/topics", headers=h,
                     json={"subject": "literacy", "chapter": "Stories", "title": "Another"}).json()["checkpoint_id"]
    assert t2 != t and t2.startswith(f"C{sb['school_id']}-")


def test_custom_topic_is_private_to_its_school(client, teacher_headers):
    """Another school's custom checkpoint id is unknown to this teacher (list, tap, probe)."""
    from app.services.content import get_content
    from app.services.content import Checkpoint
    cid = "C999-1"
    get_content().register_custom(Checkpoint(id=cid, subject="numeracy", grade=2, domain="", chapter="X",
                                             title_hi="x", title_en="x", prereqs=(), misconceptions=(),
                                             assess_via=("teacher_tap",), item_types=(), nipun_ref="", language="hi"))
    try:
        ids = {c["id"] for c in client.get("/v1/content/checkpoints", headers=teacher_headers).json()}
        assert cid not in ids
        r = client.post("/v1/classes/1/captures/tap", headers=teacher_headers,
                        json={"items": [{"child_id": 1, "checkpoint_id": cid, "result": "correct"}]})
        assert r.status_code == 422
        r = client.post(f"/v1/classes/1/captures/probe?child_id=1&checkpoint_id={cid}&passed=1&total=2",
                        headers=teacher_headers)
        assert r.status_code == 422
    finally:
        get_content().checkpoints.pop(cid, None)
        get_content().custom_ids.discard(cid)


def test_hosted_postgres_url_uses_psycopg3():
    """Neon/Render give postgresql:// URLs; the engine must use the psycopg 3 driver we ship."""
    from app.config import Settings

    for raw in ("postgresql://u:p@h/db?sslmode=require", "postgres://u:p@h/db"):
        assert Settings(database_url=raw).database_url.startswith("postgresql+psycopg://")
    assert Settings(database_url="sqlite:///x.db").database_url == "sqlite:///x.db"
    assert Settings(database_url="postgresql+psycopg://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
