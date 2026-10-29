"""English as the third built-in subject (docs/english_subject_contract.md), backend side.

Tests that need the English lessons (`E.G*`) skip with a reason when the content is not installed
(the Content agent's files, or tests/english_fixture.py via CONTENT_DIR). The seeded DEMO school is only
read; anything that writes goes to a sandbox school made here.
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import (
    CustomSubject, Evidence, GroupSession, LevelCheck, Plan, School, Teacher,
)
from app.i18n import library
from app.services import content_lang, voice_session as vse
from app.services.content import Checkpoint, Content, get_content
from app.services.subjects import ALIASES, BUILTIN_NAMES, resolve_subject, subject_names
from app.services.voice_types import STAGE_CHECKPOINTS, STAGE_CHECKPOINTS_EN, stage_checkpoints
from tests.test_voice_session import (  # noqa: F401 - fixtures and helpers of the voice-session tests
    RIGHT, _evidence, _start, _turn, clock, fakes, kid, sandbox,
)

HAS_ENGLISH = "E.G1.letter_names" in get_content().checkpoints
needs_english = pytest.mark.skipif(not HAS_ENGLISH, reason="English content (E.G* nodes) is not installed")

G1 = ["E.G1.letter_names", "E.G1.letter_sounds", "E.G1.oral_vocab", "E.G1.build_cvc", "E.G1.read_cvc",
      "E.G1.sight_words", "E.G1.read_short_sent"]
G2 = ["E.G2.blends_digraphs", "E.G2.spell_words", "E.G2.read_sentences", "E.G2.make_sentence", "E.G2.simple_comp"]
G3 = ["E.G3.read_passage", "E.G3.sentence_formation", "E.G3.word_types", "E.G3.story_comp"]


def _class_id(client, headers, grade):
    return next(c["id"] for c in client.get("/v1/classes", headers=headers).json() if c["grade"] == grade)


@pytest.fixture(scope="module")
def esb():
    """A second school with a teacher; classes are made through the API (no English roadmap row)."""
    with SessionLocal() as db:
        school = School(name="English Test School", code="EN" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="English Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.commit()
        return {"school_id": school.id, "teacher_id": t.id,
                "headers": {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}}


def _new_class(client, esb, grade, children=3):
    r = client.post("/v1/classes", headers=esb["headers"], json={"grade": grade, "section": uuid.uuid4().hex[:6]})
    cid = r.json()["id"]
    ids = [client.post(f"/v1/classes/{cid}/children", headers=esb["headers"],
                       json={"first_name": f"Bachcha{n}", "roll_no": n, "consent_source": "form"}).json()["id"]
           for n in range(1, children + 1)]
    return cid, ids


# ------------------------------------------------------------------ subjects (no English content needed)
def test_english_is_a_builtin_subject_with_aliases():
    assert BUILTIN_NAMES["english"] == ("English", "अंग्रेज़ी")
    assert list(BUILTIN_NAMES) == ["numeracy", "literacy", "english"]
    assert ALIASES["angrezi"] == "english" and ALIASES["hindi"] == "literacy" and ALIASES["maths"] == "numeracy"
    with SessionLocal() as db:
        for s in ("english", "English", " ENGLISH ", "angrezi"):
            assert resolve_subject(db, 1, s) == "english"
        assert resolve_subject(db, 1, "Hindi") == "literacy" and resolve_subject(db, 1, "math") == "numeracy"


def test_subjects_endpoint_lists_three_builtins_then_custom(client, esb):
    cid, _ = _new_class(client, esb, 2)
    name = "Art " + uuid.uuid4().hex[:5]
    client.post("/v1/subjects", headers=esb["headers"], json={"name": name})
    subs = client.get(f"/v1/classes/{cid}/subjects", headers=esb["headers"]).json()
    assert [s["key"] for s in subs[:3]] == ["numeracy", "literacy", "english"]
    assert subs[2]["name_en"] == "English" and subs[2]["name_hi"] == "अंग्रेज़ी" and subs[2]["builtin"] is True
    assert subs[3]["name_en"] == name and subs[3]["builtin"] is False
    assert (subs[2]["topics"] > 0) == HAS_ENGLISH


def test_english_name_is_reserved_for_custom_subjects(client, esb):
    for n in ("English", "english", "Angrezi", "अंग्रेज़ी"):
        assert client.post("/v1/subjects", headers=esb["headers"], json={"name": n}).status_code == 409, n


def test_a_schools_old_custom_english_subject_is_listed_once():
    with SessionLocal() as db:
        school = School(name="Old English School", code="OE" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        db.add(CustomSubject(school_id=school.id, key="english", name_en="English", name_hi="English"))
        db.flush()
        keys = [s["key"] for s in subject_names(db, school.id)]
        assert keys == ["numeracy", "literacy", "english"]
        assert resolve_subject(db, school.id, "english") == "english"
        db.rollback()


def test_unknown_subject_is_still_422(client, teacher_headers):
    assert client.get("/v1/classes/1/board", params={"subject": "french"}, headers=teacher_headers).status_code == 422


# ------------------------------------------------------------------ localization guards (no content needed)
def _en_cp(cid="E.TEST.x") -> Checkpoint:
    return Checkpoint(id=cid, subject="english", grade=1, domain="d", chapter="c", title_hi="हिन्दी नाम",
                      title_en="English name", prereqs=(), misconceptions=(), assess_via=(), item_types=(),
                      nipun_ref="", language="en")


def test_english_activity_is_never_translated():
    act = {"id": "act_en_fake", "title_hi": "Sound hunt", "steps_hi": ["Say a sound."], "materials_hi": "none",
           "blackboard_hi": "", "language": "en", "checkpoint_ids": []}
    for lang in ("ta", "mr", "bn", "en"):
        out = content_lang.activity(act, lang)
        assert out["steps_hi"] == ["Say a sound."] and out["title_hi"] == "Sound hunt"
        assert out["machine_translated"] is False
    assert content_lang.activity(act, "hi") is act  # Hindi: the very same object
    hindi = {"id": "act_borrow_sticks", "title_hi": "x", "steps_hi": ["a"], "language": "hi"}
    assert content_lang.activity(hindi, "ta")["machine_translated"] in (True, False)  # still localised as before


def test_library_keeps_english_activity_text_and_titles_fall_back_to_english(monkeypatch):
    content = get_content()
    monkeypatch.setitem(content.activities, "act_en_zz", {"id": "act_en_zz", "title_hi": "Read it", "steps_hi": ["Read."],
                                                          "language": "en", "checkpoint_ids": []})
    monkeypatch.setitem(content.checkpoints, "E.ZZ.node", _en_cp("E.ZZ.node"))
    try:
        assert library.localized("activity", "act_en_zz", "title", "ta") == {"text": "Read it", "machine_translated": False}
        assert library.localized("activity", "act_en_zz", "steps", "mr") == {"text": ["Read."], "machine_translated": False}
        # a language file without the lesson: its English title, not the Hindi one
        assert library.localized("checkpoint", "E.ZZ.node", "title", "ta") == {"text": "English name", "machine_translated": False}
        assert content_lang.checkpoint_title(content, "E.ZZ.node", "ta") == ("English name", False)
        assert content_lang.checkpoint_title(content, "E.ZZ.node", "hi") == ("हिन्दी नाम", False)
        assert content_lang.checkpoint_title(content, "E.ZZ.node", "en") == ("English name", False)
        # a probe on an English lesson keeps its questions
        p = {"title_hi": "Check", "tell_hi": "x", "items": [{"ask_hi": "Say it.", "expect": "x"}]}
        out = content_lang.probe(p, "E.ZZ.node", "ta")
        assert out["items"] == p["items"] and out["title_hi"] == "Check" and out["machine_translated"] is False
    finally:
        library.reload()


def test_hindi_and_maths_titles_still_fall_back_to_hindi_in_other_languages():
    content = get_content()
    cp = content.checkpoints["N.G1.count_to_20"]
    title, mt = content_lang.checkpoint_title(content, cp.id, "zz")  # a language with no file
    assert title == cp.title_hi and mt is False


# ------------------------------------------------------------------ voice mapping (no content needed)
def test_english_stage_mapping_uses_E_nodes():
    assert set(STAGE_CHECKPOINTS_EN) == set(STAGE_CHECKPOINTS)
    assert STAGE_CHECKPOINTS_EN["letter"] == ("E.G1.letter_names", "E.G1.letter_sounds")
    assert STAGE_CHECKPOINTS_EN["word_build"] == ("E.G1.build_cvc", "E.G2.spell_words")
    assert STAGE_CHECKPOINTS_EN["word_read"] == ("E.G1.read_cvc", "E.G2.blends_digraphs")
    assert STAGE_CHECKPOINTS_EN["sentence_build"] == ("E.G2.make_sentence", "E.G3.sentence_formation")
    assert STAGE_CHECKPOINTS_EN["reading"] == ("E.G1.read_short_sent", "E.G2.read_sentences", "E.G3.read_passage")
    assert stage_checkpoints("en", "letter") == STAGE_CHECKPOINTS_EN["letter"]
    for lang in ("hi", "mr", None):
        assert stage_checkpoints(lang, "letter") == STAGE_CHECKPOINTS["letter"]


def test_evidence_gate_keeps_languages_apart(monkeypatch):
    content = get_content()
    monkeypatch.setitem(content.checkpoints, "E.ZZ.node", _en_cp("E.ZZ.node"))
    en = {"lang": "en", "syllabus": {"english": ["E.ZZ.node"]}}
    hi = {"lang": "hi", "syllabus": {"english": []}}
    assert vse._evidence_ok(en, "E.ZZ.node") is True
    assert vse._evidence_ok(en, "L.G1.swar") is False  # English answers never land on the Hindi map
    assert vse._evidence_ok(hi, "L.G1.swar") is True
    assert vse._evidence_ok(hi, "E.ZZ.node") is False  # and Hindi answers never on an English lesson
    assert vse._evidence_ok(en, None) is False


# ------------------------------------------------------------------ the demo seed is deterministic
def test_seed_is_deterministic_across_fresh_databases(tmp_path):
    code = (
        "import json, os\n"
        "from datetime import datetime\n"
        "from sqlalchemy import select\n"
        "from app.seed import seed\n"
        "from app.db import SessionLocal\n"
        "from app.models.tables import Evidence, Child, GroupSession, LevelCheck\n"
        "seed()\n"
        "db = SessionLocal(); now = datetime.utcnow(); out = []\n"
        "for e in db.scalars(select(Evidence).order_by(Evidence.id)):\n"
        "    out.append([e.child_id, e.checkpoint_id, e.result, e.source, e.misconception, round((now - e.at).total_seconds() / 3600)])\n"
        "for s in db.scalars(select(GroupSession).order_by(GroupSession.id)):\n"
        "    out.append([s.subject, s.checkpoint_id, s.activity_id, s.member_ids])\n"
        "for c in db.scalars(select(LevelCheck).order_by(LevelCheck.id)):\n"
        "    out.append([c.child_id, c.subject, c.level_index])\n"
        "print(json.dumps(out))\n")
    runs = []
    for n in (1, 2):
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path}/seed{n}.db", "ANTHROPIC_API_KEY": "", "SARVAM_API_KEY": ""}
        r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], env=env,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        runs.append(r.stdout.strip().splitlines()[-1])
    assert runs[0] == runs[1] and len(runs[0]) > 1000


def test_seed_version_was_bumped():
    from app.seed import SEED_VERSION
    assert SEED_VERSION != "2026-10-30"


# ------------------------------------------------------------------ template syllabus per grade
@needs_english
def test_template_roadmap_per_grade_in_teaching_order():
    c = get_content()
    ids = lambda g: [i["checkpoint_id"] for i in c.template_roadmap("english", g)]  # noqa: E731
    assert ids(1) == G1
    assert ids(2) == G1 + G2
    assert ids(3) == G1 + G2 + G3
    assert [i["position"] for i in c.template_roadmap("english", 3)] == list(range(16))
    # Maths and Hindi templates are untouched by English
    assert all(i["checkpoint_id"].startswith("N.") for i in c.template_roadmap("numeracy", 2))
    assert all(i["checkpoint_id"].startswith("L.") for i in c.template_roadmap("literacy", 2))


@needs_english
def test_demo_classes_have_english_roadmaps(client, teacher_headers):
    for grade, want in ((2, G1 + G2), (3, G1 + G2 + G3)):
        cid = _class_id(client, teacher_headers, grade)
        r = client.get(f"/v1/classes/{cid}/roadmap", params={"subject": "english"}, headers=teacher_headers).json()
        assert r["confirmed"] is True and [i["checkpoint_id"] for i in r["items"]] == want
        subs = client.get(f"/v1/classes/{cid}/subjects", headers=teacher_headers).json()
        assert [s["key"] for s in subs] == ["numeracy", "literacy", "english"]
        assert subs[2]["topics"] == len(want)


@needs_english
def test_syllabus_and_board_work_for_a_class_without_an_english_roadmap(client, esb):
    """Existing live classes (no English roadmap row) get the grade's template, not an empty subject."""
    cid, ids = _new_class(client, esb, 3)
    h = esb["headers"]
    s = client.get(f"/v1/classes/{cid}/syllabus", params={"subject": "english"}, headers=h).json()
    assert s["confirmed"] is False and s["source"] == "template" and s["totals"]["topics"] == 16
    assert client.get(f"/v1/classes/{cid}/roadmap", params={"subject": "english"}, headers=h).json()["confirmed"] is False
    b = client.get(f"/v1/classes/{cid}/board", params={"subject": "english"}, headers=h)
    assert b.status_code == 200 and b.json()["unassessed"]
    p = client.get(f"/v1/children/{ids[0]}/profile", params={"subject": "english"}, headers=h).json()
    assert [i["checkpoint_id"] for i in p["items"]] == G1 + G2 + G3 and p["subject"] == "english"


# ------------------------------------------------------------------ the seeded DEMO school
@needs_english
def test_demo_board_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    b = client.get(f"/v1/classes/{cid}/board", params={"subject": "english"}, headers=teacher_headers).json()
    keys = {g["key"] for g in b["groups"]}
    assert len(b["groups"]) >= 3 and b["on_track"] and b["unassessed"]
    assert {"E.G1.letter_sounds", "E.G1.build_cvc", "E.G1.read_short_sent"} <= keys
    assert all(k.startswith("E.") for k in keys)
    assert len(b["on_track"]) >= 5 and len(b["unassessed"]) >= 2
    # the other subjects' boards never mention English lessons
    for subject, prefix in (("numeracy", "N."), ("literacy", "L.")):
        other = client.get(f"/v1/classes/{cid}/board", params={"subject": subject}, headers=teacher_headers).json()
        assert other["groups"] and all(g["key"].startswith(prefix) for g in other["groups"])
    b3 = client.get(f"/v1/classes/{_class_id(client, teacher_headers, 3)}/board", params={"subject": "english"},
                    headers=teacher_headers)
    assert b3.status_code == 200 and b3.json()["groups"]


@needs_english
def test_demo_followups_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    f = client.get(f"/v1/classes/{cid}/followups", params={"subject": "english"}, headers=teacher_headers).json()
    for k in ("recheck", "stuck", "missed", "not_checked"):
        assert f[k], k
    assert all(r["checkpoint_id"].startswith("E.") for k in ("recheck", "stuck", "missed") for r in f[k])
    assert any(r["checkpoint_id"] == "E.G1.letter_sounds" and r["sessions"] >= 3 for r in f["stuck"])
    for subject in ("numeracy", "literacy"):  # English sessions never leak into the other subjects
        o = client.get(f"/v1/classes/{cid}/followups", params={"subject": subject}, headers=teacher_headers).json()
        assert not any(r.get("checkpoint_id", "").startswith("E.") for k in ("recheck", "stuck", "missed") for r in o[k])


@needs_english
def test_demo_outcomes_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    o = client.get(f"/v1/classes/{cid}/outcomes", params={"subject": "english"}, headers=teacher_headers).json()
    assert len(o["sessions"]) >= 3
    assert all(s["activity_id"].startswith("act_en_") for s in o["sessions"])
    assert {a["activity_id"][:7] for a in o["activities"]} == {"act_en_"}
    changes = {c["change"] for s in o["sessions"] for c in s["children"]}
    assert {"up", "same", "not_rechecked"} <= changes
    nu = client.get(f"/v1/classes/{cid}/outcomes", params={"subject": "numeracy"}, headers=teacher_headers).json()
    assert not any(s["checkpoint_id"].startswith("E.") for s in nu["sessions"])


@needs_english
def test_demo_level_check_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    j = client.get(f"/v1/classes/{cid}/level_check", params={"subject": "english"}, headers=teacher_headers).json()
    assert [lv["key"] for lv in j["levels"]] == ["letter", "word", "sentence", "story"]
    assert j["title_en"] == "English reading level"
    s = j["summary"]
    assert s["total"] == 30 and 18 <= s["checked"] <= 20 and s["moved_up"] >= 5
    # the same content language gives the same English ladder (English is never translated)
    assert all(lv["checkpoint_id"].startswith("E.") for lv in j["levels"])


@needs_english
def test_demo_parent_english_journey_tips_and_moments(client, parent_headers):
    j = client.get("/v1/parent/journey", params={"subject": "english"}, headers=parent_headers).json()
    assert j["subject"] == "english" and j["counts"]["total"] == 12 and j["counts"]["learned"] >= 3
    assert [m["checkpoint_id"] for m in j["milestones"]] == G1 + G2  # teaching order
    assert {m["state"] for m in j["milestones"]} >= {"learned", "working", "next"}
    assert j["celebrations"] and all(c["checkpoint_id"].startswith("E.") for c in j["celebrations"])
    growth = [g["learned"] for g in j["growth"]]
    assert growth == sorted(growth) and growth[-1] > growth[0]
    # the alias works too, and the other subjects keep their own journeys
    assert client.get("/v1/parent/journey", params={"subject": "angrezi"}, headers=parent_headers).json()["subject"] == "english"
    assert all(m["checkpoint_id"].startswith("N.") for m in
               client.get("/v1/parent/journey", params={"subject": "numeracy"}, headers=parent_headers).json()["milestones"])
    tips = client.get("/v1/parent/tips", headers=parent_headers).json()["tips"]
    assert any(t["checkpoint_id"].startswith("E.") for t in tips)
    moments = client.get("/v1/parent/moments", headers=parent_headers).json()["moments"]
    assert any(m.get("checkpoint_id", "").startswith("E.") for m in moments)
    assert any(m.get("move") == "getting_better" and m["checkpoint_id"].startswith("E.") for m in moments)


@needs_english
def test_demo_child_profile_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    roster = client.get(f"/v1/classes/{cid}/roster", headers=teacher_headers).json()
    kid12 = next(c for c in roster if c["roll_no"] == 12)
    p = client.get(f"/v1/children/{kid12['id']}/profile", params={"subject": "english"}, headers=teacher_headers).json()
    st = {i["checkpoint_id"]: i["status"] for i in p["items"]}
    assert st["E.G1.letter_sounds"] == "on_track" and st["E.G2.blends_digraphs"] == "needs_practice"


@needs_english
def test_hindi_and_maths_demo_data_is_unchanged_by_english(client, teacher_headers):
    cid = _class_id(client, teacher_headers, 2)
    nu = client.get(f"/v1/classes/{cid}/board", params={"subject": "numeracy"}, headers=teacher_headers).json()
    # (counts shift when other tests tap on DEMO; the group set and the story's shape do not)
    assert {g["key"] for g in nu["groups"]} == {"N.G2.add_2digit_carry", "N.G2.place_value_99", "N.G2.sub_2digit_borrow"}
    f = client.get(f"/v1/classes/{cid}/followups", params={"subject": "numeracy"}, headers=teacher_headers).json()
    assert {r["checkpoint_id"] for r in f["stuck"]} == {"N.G2.sub_2digit_borrow"}
    lc = client.get(f"/v1/classes/{cid}/level_check", params={"subject": "literacy"}, headers=teacher_headers).json()
    assert lc["summary"]["checked"] == 20


# ------------------------------------------------------------------ plans, follow-ups and clean-up in a sandbox class
@needs_english
def test_english_plan_done_followups_outcomes_and_delete(client, esb):
    h = esb["headers"]
    cid, ids = _new_class(client, esb, 2, children=4)
    cp = "E.G1.letter_sounds"
    client.post(f"/v1/classes/{cid}/captures/tap", headers=h,
                json={"items": [{"child_id": i, "checkpoint_id": cp, "result": "incorrect"} for i in ids] * 2})
    plan = client.post(f"/v1/classes/{cid}/plans", params={"subject": "english"}, headers=h).json()
    assert plan["subject"] == "english"
    group = next(g for g in client.get(f"/v1/classes/{cid}/plans/latest", params={"subject": "english"},
                                       headers=h).json()["groups"] if g["key"] == cp)
    assert group["activity_id"].startswith("act_en_") and len(group["members"]) == 4
    assert client.post(f"/v1/plans/{plan['id']}/groups/{cp}/done", headers=h).status_code == 200
    o = client.get(f"/v1/classes/{cid}/outcomes", params={"subject": "english"}, headers=h).json()
    assert len(o["sessions"]) == 1 and o["sessions"][0]["activity_id"].startswith("act_en_")
    assert client.get(f"/v1/classes/{cid}/outcomes", params={"subject": "numeracy"}, headers=h).json()["sessions"] == []
    # a level check records on E.* lessons and a LevelCheck row for english
    r = client.post(f"/v1/classes/{cid}/level_check", headers=h, json={
        "subject": "english", "child_id": ids[0],
        "results": [{"level_key": "letter", "passed": True}, {"level_key": "word", "passed": False}]})
    assert r.status_code == 200 and r.json()["level_key"] == "letter"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LevelCheck).where(LevelCheck.child_id == ids[0],
                                                                            LevelCheck.subject == "english")) == 1
    # per-child delete clears English evidence and checks; per-class delete clears sessions and plans
    assert client.delete(f"/v1/children/{ids[0]}/data", headers=h).status_code == 200
    with SessionLocal() as db:
        assert not db.scalar(select(Evidence.id).where(Evidence.child_id == ids[0]))
        assert not db.scalar(select(LevelCheck.id).where(LevelCheck.child_id == ids[0]))
    assert client.delete(f"/v1/classes/{cid}/data", headers=h).status_code == 200
    with SessionLocal() as db:
        assert not db.scalar(select(Evidence.id).where(Evidence.child_id.in_(ids)))
        assert not db.scalar(select(GroupSession.id).where(GroupSession.class_id == cid))
        assert not db.scalar(select(Plan.id).where(Plan.class_id == cid))


# ------------------------------------------------------------------ English voice session
@needs_english
def test_english_session_practises_E_nodes_and_writes_E_evidence(client, kid, sandbox, fakes, clock):
    h, cid = kid
    s = _start(client, h, lang="en")
    assert s["stage"] == "letter"
    topics = fakes.gen_calls[-1]["topics"]
    assert [t["checkpoint_id"] for t in topics] == list(STAGE_CHECKPOINTS_EN["letter"])  # grade 2: both letter lessons
    assert not any(t["custom"] for t in topics)  # built-in subject, no school-made English subject needed
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    assert t["next_item"] is not None
    assert _evidence(cid) == [("E.G1.letter_names", "correct")]
    with SessionLocal() as db:
        ev = db.scalars(select(Evidence).where(Evidence.child_id == cid)).one()
        assert ev.source == "home_voice" and ev.checkpoint_id.startswith("E.")


@needs_english
def test_english_start_stage_and_hindi_session_untouched(client, kid, sandbox, fakes, clock):
    h, cid = kid
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # every English lesson secure at school -> the session warms up one stage in
        for cp in G1 + G2:
            for d in (3, 2, 1):
                db.add(Evidence(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=cid,
                                checkpoint_id=cp, result="correct", source="teacher_tap", confidence=1.0,
                                at=now - timedelta(days=d)))
        db.commit()
    assert _start(client, h, lang="en")["stage"] == "word_build"
    hi = _start(client, h, lang="hi")
    assert hi["stage"] == "letter"  # Hindi ladder ignores English statuses
    assert all(t["checkpoint_id"] in STAGE_CHECKPOINTS["letter"] for t in fakes.gen_calls[-1]["topics"])
    before = _evidence(cid)
    _turn(client, h, hi, hi["item"]["id"], RIGHT)
    assert all(cp.startswith("L.") for cp, _ in _evidence(cid)[len(before):])


@needs_english
def test_old_custom_english_subject_still_adds_its_topics(client, kid, sandbox, fakes, clock):
    h, cid = kid
    th = sandbox["teacher_headers"]
    with SessionLocal() as db:  # a school that made its own "English" before it was built in
        if not db.scalar(select(CustomSubject.id).where(CustomSubject.school_id == sandbox["school_id"])):
            db.add(CustomSubject(school_id=sandbox["school_id"], key="english", name_en="English", name_hi="English"))
            db.commit()
    r = client.post(f"/v1/classes/{sandbox['class_id']}/syllabus/topics", headers=th,
                    json={"subject": "english", "chapter": "Extra", "title": "My own English topic"})
    assert r.status_code == 200, r.text
    _start(client, h, lang="en")
    topics = fakes.gen_calls[-1]["topics"]
    assert any(t["custom"] and t["title_en"] == "My own English topic" for t in topics)
    assert any(t["checkpoint_id"] in STAGE_CHECKPOINTS_EN["letter"] for t in topics)
