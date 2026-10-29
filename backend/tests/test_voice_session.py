"""30-minute voice session engine + API (docs/voice_session_contract.md).

The other modules of the feature (AI tutor, assessment, report) are replaced with small fakes at the
engine's seams, so these tests pin the engine's own logic: ladder, tries, streaks, silence, timer,
idempotency, evidence, safety, report storage and tenancy. Children are made in a sandbox school so
the seeded DEMO data other tests count on is never changed.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.ai import features
from app.core.security import hash_phone, hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import (
    Child, Classroom, Evidence, ParentAccount, School, Teacher, VoiceSession, VoiceTurn,
)
from app.services import voice_session as vse
from app.services.voice_types import MAX_ATTEMPTS, STAGE_CHECKPOINTS, Assessment

RIGHT, ALMOST, NOPE = "RIGHT", "ALMOST", "NOPE"


# ------------------------------------------------------------------ fakes at the engine's seams
class Fakes:
    def __init__(self):
        self.n = 0
        self.gen_calls = []
        self.kind = {"letter": "read_letter", "word_build": "build_word", "word_read": "read_word",
                     "sentence_build": "make_sentence", "reading": "read_sentence"}
        self.no_checkpoint = False
        self.paragraph = False
        self.report_kwargs = None

    def generate_items(self, db, *, school_id, lang, grade, stage, topics, avoid, weak_sounds, n=6, use_ai=True):
        self.gen_calls.append({"stage": stage, "lang": lang, "topics": topics, "avoid": list(avoid),
                               "weak_sounds": list(weak_sounds)})
        custom = [t for t in topics if t["custom"]]
        cp = None if self.no_checkpoint else (custom or topics or [{"checkpoint_id": None}])[0]["checkpoint_id"]
        out = []
        for k in range(n):
            self.n += 1
            kind = "read_paragraph" if self.paragraph else self.kind[stage]
            it = {"id": f"f{self.n}", "stage": stage, "kind": kind, "lang": lang, "checkpoint_id": cp,
                  "prompt": "{name}, go", "display": {"text": f"t{self.n}"}, "target": f"t{self.n}",
                  "accept": [f"a{self.n}"], "required_words": [], "keywords": [f"k{self.n}"],
                  "max_record_s": 5, "difficulty": 1 + k % 3, "source": "bank"}
            if kind == "read_paragraph":
                it["followups"] = [{"id": f"q{self.n}", "stage": stage, "kind": "answer_question", "lang": lang,
                                    "checkpoint_id": cp, "prompt": "Why?", "display": {"question": "Why?"},
                                    "target": "because", "accept": ["since"], "keywords": ["because"],
                                    "difficulty": 1}]
            out.append(it)
        return out, "bank"

    @staticmethod
    def assess_item(item, transcript, duration_s=None):
        if transcript == RIGHT:
            return Assessment("correct", 1.0, transcript, words=[{"target": "x", "heard": "x", "status": "correct"}])
        if transcript == ALMOST:
            return Assessment("close", 0.6, transcript)
        if not transcript:
            return Assessment("silent", 0.0, "")
        return Assessment("wrong", 0.0, transcript,
                          errors=[{"type": "substitution", "target": "श", "heard": "स", "word": "x"}])

    @staticmethod
    def tutor_line(db, *, school_id, lang, situation, item, assessment, attempt):
        return f"[{situation}:{attempt}]", "fallback"

    @staticmethod
    def evaluate_open(db, *, school_id, lang, item, transcript, code):
        return code

    def build_report(self, **kw):
        self.report_kwargs = kw
        return {"lang": kw["lang"], "items_attempted": len(kw["items"]), "accuracy": 0.5,
                "highest_stage": "letter", "narrative": {}, "next_steps": {"hi": [], "en": []}}

    @staticmethod
    def write_narrative(db, *, school_id, lang, report):
        return {"narrative": {"parent_hi": "{name} ने अच्छा किया", "parent_en": "{name} did well",
                              "teacher_en": "t", "teacher_hi": "t"},
                "next_steps": {"hi": ["अभ्यास"], "en": ["practise"]}}, "fallback"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    for name in ("generate_items", "assess_item", "tutor_line", "evaluate_open", "build_report", "write_narrative"):
        monkeypatch.setattr(vse, name, getattr(f, name))
    monkeypatch.setattr(vse, "transcribe", lambda audio, filename, lang: "")
    return f


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(vse, "CLOCK", c)
    return c


# ------------------------------------------------------------------ sandbox school
@pytest.fixture(scope="module")
def sandbox():
    with SessionLocal() as db:
        school = School(name="Voice Test School", code="VS" + uuid.uuid4().hex[:8].upper())
        db.add(school)
        db.flush()
        t = Teacher(school_id=school.id, name="Voice Teacher", pin_hash=hash_pin("4321"))
        db.add(t)
        db.flush()
        cls = Classroom(school_id=school.id, teacher_id=t.id, grade=2, section="V", label="2V")
        db.add(cls)
        db.commit()
        out = {"school_id": school.id, "class_id": cls.id, "teacher_id": t.id,
               "teacher_headers": {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}, "roll": 0}
    return out


@pytest.fixture
def kid(sandbox):
    """A fresh child with a parent account in the sandbox class: (parent headers, child id)."""
    sandbox["roll"] += 1
    with SessionLocal() as db:
        c = Child(class_id=sandbox["class_id"], roll_no=sandbox["roll"], first_name="Meena")
        db.add(c)
        db.flush()
        p = ParentAccount(school_id=sandbox["school_id"], child_id=c.id, phone_hash=hash_phone("9000000000"),
                          pin_hash=hash_pin("0000"))
        db.add(p)
        db.commit()
        return {"Authorization": f"Bearer {make_token(str(p.id), 'parent')}"}, c.id


def _start(client, h, lang="hi"):
    r = client.post("/v1/parent/voice/sessions", headers=h, json={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def _turn(client, h, s, item_id, transcript=None, ctid=None, audio=None, status=200):
    meta = {"item_id": item_id, "client_turn_id": ctid or uuid.uuid4().hex}
    if transcript is not None:
        meta["transcript"] = transcript
    files = {"audio": ("t.wav", audio, "audio/wav")} if audio else None
    r = client.post(f"/v1/parent/voice/sessions/{s['id']}/turn", headers=h, data={"meta": json.dumps(meta)},
                    files=files)
    assert r.status_code == status, r.text
    return r.json()


def _evidence(child_id):
    with SessionLocal() as db:
        return [(e.checkpoint_id, e.result) for e in db.scalars(
            select(Evidence).where(Evidence.child_id == child_id, Evidence.source == "home_voice").order_by(Evidence.id))]


def _fail_item(client, h, s, item):
    """Five wrong tries; returns the last turn."""
    t = None
    for _ in range(MAX_ATTEMPTS):
        t = _turn(client, h, s, item["id"], NOPE)
    return t


# ------------------------------------------------------------------ tests
def test_start_shape(client, parent_headers, fakes, clock):
    s = _start(client, parent_headers)
    for k in ("id", "lang", "status", "started_at", "elapsed_s", "target_minutes", "stage", "item", "attempt",
              "transcript", "tutor"):
        assert k in s, k
    assert s["status"] == "active" and s["lang"] == "hi" and s["target_minutes"] == 30 and s["attempt"] == 1
    assert s["stage"] == "letter"  # seeded roll 12 has no secure letter checkpoints
    assert s["item"]["kind"] == "read_letter" and "{name}" not in s["item"]["prompt"]
    assert s["tutor"]["text"].startswith("[greet") and s["transcript"][0]["role"] == "tutor"
    # topics passed to the generator: the class literacy syllabus filtered to the stage
    topics = fakes.gen_calls[0]["topics"]
    assert topics and all(t["checkpoint_id"] in STAGE_CHECKPOINTS["letter"] for t in topics)
    assert {"checkpoint_id", "title_hi", "title_en", "custom"} <= set(topics[0])
    with SessionLocal() as db:  # keep the shared seeded child clean
        db.query(VoiceTurn).filter(VoiceTurn.session_id == s["id"]).delete()
        db.query(VoiceSession).filter(VoiceSession.id == s["id"]).delete()
        db.commit()


def test_correct_path_climbs_and_hides_answers(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    item = s["item"]
    assert item["difficulty"] == 1
    t1 = _turn(client, h, s, item["id"], RIGHT)
    assert t1["verdict"] == "correct" and t1["next_item"]["id"] != item["id"] and t1["attempt"] == 1
    assert t1["tutor"]["text"].startswith("[praise:1]") and not t1["stage_changed"]
    assert t1["attempts_left"] == MAX_ATTEMPTS and t1["asr"] == "provided"
    t2 = _turn(client, h, s, t1["next_item"]["id"], RIGHT)
    assert t2["next_item"]["difficulty"] == 2  # 2 successes in a row -> harder item
    t3 = _turn(client, h, s, t2["next_item"]["id"], RIGHT)
    assert t3["stage_changed"] and t3["stage"] == "word_build"  # 3 -> next stage
    assert "[stage_up:1]" in t3["tutor"]["text"]
    nxt = t3["next_item"]
    assert nxt["kind"] == "build_word"
    assert not {"target", "accept", "keywords"} & set(nxt)  # the child must not see the answer
    assert [l["role"] for l in t3["transcript_append"]] == ["child", "tutor"]
    full = client.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert full["session"]["stage"] == "word_build" and full["report"] is None
    assert not {"target", "accept", "keywords"} & set(full["session"]["item"])
    assert len(full["session"]["transcript"]) == 7  # greet + 3 x (child, tutor)


def test_retry_escalates_then_moves_on_easier(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    # climb difficulty first: two successes -> difficulty 2
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    t = _turn(client, h, s, t["next_item"]["id"], RIGHT)
    item = t["next_item"]
    assert item["difficulty"] == 2
    for n in range(1, MAX_ATTEMPTS):
        t = _turn(client, h, s, item["id"], NOPE if n % 2 else ALMOST)
        assert t["next_item"]["id"] == item["id"]  # same item again
        assert t["attempt"] == n + 1 and t["attempts_left"] == MAX_ATTEMPTS - n
        assert t["tutor"]["text"].startswith(f"[retry_hint:{n}]")
    t = _turn(client, h, s, item["id"], NOPE)
    assert t["item_result"] == "failed" and t["tutor"]["text"].startswith(f"[move_on:{MAX_ATTEMPTS}]")
    assert t["next_item"]["id"] != item["id"] and t["next_item"]["difficulty"] == 1  # easier next
    assert t["attempt"] == 1 and t["stage"] == "letter"
    assert _evidence(cid)[-1][1] == "incorrect"
    # weak sounds from the errors steer the next generation
    client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={"reason": "parent_stop"})
    failed = fakes.report_kwargs["items"][item["id"]]
    assert failed["result"] == "failed" and failed["attempts_used"] == MAX_ATTEMPTS
    assert failed["heard"] == NOPE and failed["errors"][0]["target"] == "श"
    assert any("श" in c["weak_sounds"] for c in fakes.gen_calls)


def test_two_failed_items_step_down_never_below_letter(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    t = {"next_item": s["item"]}
    for _ in range(3):
        t = _turn(client, h, s, t["next_item"]["id"], RIGHT)
    assert t["stage"] == "word_build"
    t = _fail_item(client, h, s, t["next_item"])
    assert t["stage"] == "word_build" and not t["stage_changed"]
    t = _fail_item(client, h, s, t["next_item"])
    assert t["stage"] == "letter" and t["stage_changed"] and "[stage_down:1]" in t["tutor"]["text"]
    t = _fail_item(client, h, s, t["next_item"])
    t = _fail_item(client, h, s, t["next_item"])
    assert t["stage"] == "letter" and not t["stage_changed"]


def test_silence_and_asr_failure_do_not_use_a_try(client, kid, fakes, clock, monkeypatch):
    h, cid = kid
    s = _start(client, h)
    item = s["item"]
    t = _turn(client, h, s, item["id"], NOPE)
    assert t["attempt"] == 2
    t = _turn(client, h, s, item["id"], "")
    assert t["verdict"] == "silent" and t["asr"] == "silent" and t["attempt"] == 2
    assert t["next_item"]["id"] == item["id"] and t["tutor"]["text"].startswith("[intro_item")
    assert [l["role"] for l in t["transcript_append"]] == ["tutor"]
    t = _turn(client, h, s, item["id"], audio=b"RIFF0000WAVE")  # mock transcribe hears nothing
    assert t["asr"] == "silent" and t["attempt"] == 2

    def boom(audio, filename, lang):
        raise RuntimeError("asr down")
    monkeypatch.setattr(vse, "transcribe", boom)
    t = _turn(client, h, s, item["id"], audio=b"RIFF0000WAVE")
    assert t["asr"] == "failed" and t["verdict"] == "silent" and t["attempt"] == 2
    assert t["tutor"]["text"].startswith("[silent:2]")  # third silence in a row: Saathi checks in
    assert _evidence(cid) == []


def test_asr_gets_the_session_language(client, kid, fakes, clock, monkeypatch):
    h, cid = kid
    seen = []
    monkeypatch.setattr(vse, "transcribe", lambda audio, filename, lang: seen.append(lang) or RIGHT)
    s = _start(client, h, lang="en")
    t = _turn(client, h, s, s["item"]["id"], audio=b"RIFF0000WAVE")
    assert seen == ["en"] and t["asr"] == "asr" and t["verdict"] == "correct"


def test_idempotent_replay(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    a = _turn(client, h, s, s["item"]["id"], NOPE, ctid="turn-1")
    b = _turn(client, h, s, s["item"]["id"], NOPE, ctid="turn-1")
    assert a == b and a["attempt"] == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.session_id == s["id"])) == 3
    c = _turn(client, h, s, s["item"]["id"], NOPE, ctid="turn-2")
    assert c["attempt"] == 3
    # a replay of an old turn still returns its stored answer after the session moved on
    assert _turn(client, h, s, s["item"]["id"], NOPE, ctid="turn-1") == a
    # a new turn on an item that is no longer current is refused
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    _turn(client, h, s, s["item"]["id"], RIGHT, status=409)
    assert t["next_item"]["id"] != s["item"]["id"]


def test_break_and_time_up_after_30_minutes(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    item, breaks, t = s["item"], 0, None
    for _ in range(40):
        clock.advance(170)  # under the idle cap, so all of it counts
        t = _turn(client, h, s, item["id"], "")
        breaks += "[break:1]" in t["tutor"]["text"]
        if t["done"]:
            break
        assert t["remaining_s"] > 0
    assert t["done"] and t["remaining_s"] == 0 and t["next_item"] is None
    assert t["elapsed_s"] >= 30 * 60 and breaks == 1
    assert "[wrap_up" in t["tutor"]["text"]
    later = _turn(client, h, s, item["id"], RIGHT)
    assert later["done"] and later["next_item"] is None and later["transcript_append"] == []
    # a long pause (app paused) adds at most the idle cap
    s2 = _start(client, h)
    clock.advance(3600)
    t2 = _turn(client, h, s2, s2["item"]["id"], "")
    assert not t2["done"] and t2["elapsed_s"] == vse.IDLE_CAP_S
    # a time-up session is finalised (report built) when it is opened
    d = client.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert d["session"]["status"] == "ended" and d["report"]["end_reason"] == "time_up"


def test_evidence_rows(client, kid, fakes, clock):
    h, cid = kid
    s = _start(client, h)
    t = _turn(client, h, s, s["item"]["id"], RIGHT)                    # try 1 -> correct
    t = _turn(client, h, s, t["next_item"]["id"], NOPE)
    t = _turn(client, h, s, t["next_item"]["id"], NOPE)
    t = _turn(client, h, s, t["next_item"]["id"], RIGHT)                # try 3 -> partial
    t = _turn(client, h, s, t["next_item"]["id"], "")                   # silent -> nothing
    r = client.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h,
                    json={"item_id": t["next_item"]["id"], "client_turn_id": "sk1"})
    assert r.status_code == 200 and r.json()["verdict"] == "skipped"     # skipped -> nothing
    t = _fail_item(client, h, s, r.json()["next_item"])                 # 5 fails -> incorrect
    ev = _evidence(cid)
    assert [e[1] for e in ev] == ["correct", "partial", "incorrect"]
    assert all(e[0] in STAGE_CHECKPOINTS["letter"] for e in ev)
    # a double-tapped skip on the old item changes nothing
    again = client.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h,
                        json={"item_id": r.json()["next_item"]["id"]}).json()
    assert again["next_item"]["id"] == t["next_item"]["id"]
    # items without a checkpoint never write evidence
    fakes.no_checkpoint = True
    s2 = _start(client, h)
    _turn(client, h, s2, s2["item"]["id"], RIGHT)
    assert len(_evidence(cid)) == 3


def test_english_topics_and_evidence_stay_off_the_hindi_map(client, kid, sandbox, fakes, clock):
    h, cid = kid
    th = sandbox["teacher_headers"]
    s = _start(client, h, lang="en")  # no school English subject: only built-in English lessons can get evidence
    assert s["stage"] == "letter"
    _turn(client, h, s, s["item"]["id"], RIGHT)
    assert all(cp.startswith("E.") for cp, _ in _evidence(cid))  # never the Hindi map
    before = len(_evidence(cid))
    r = client.post("/v1/subjects", headers=th, json={"name": "English"})
    assert r.status_code in (200, 409), r.text
    r = client.post(f"/v1/classes/{sandbox['class_id']}/syllabus/topics", headers=th,
                    json={"subject": "english", "chapter": "Letters", "title": "Letter sounds a-z"})
    assert r.status_code == 200, r.text
    s = _start(client, h, lang="en")
    topics = fakes.gen_calls[-1]["topics"]
    custom = [t for t in topics if t["custom"]]
    assert custom and custom[0]["title_en"] == "Letter sounds a-z"
    _turn(client, h, s, s["item"]["id"], RIGHT)  # fake picks the custom English topic
    assert _evidence(cid)[before:] == [(custom[0]["checkpoint_id"], "correct")]


def test_start_stage_from_child_statuses(client, kid, sandbox, fakes, clock):
    h, cid = kid
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:  # letters and word building secure at school -> warm up at word_build
        for cp in STAGE_CHECKPOINTS["letter"] + STAGE_CHECKPOINTS["word_build"]:
            for d in (3, 2, 1):
                db.add(Evidence(school_id=sandbox["school_id"], class_id=sandbox["class_id"], child_id=cid,
                                checkpoint_id=cp, result="correct", source="teacher_tap", confidence=1.0,
                                at=now - timedelta(days=d)))
        db.commit()
    s = _start(client, h)
    assert s["stage"] == "word_build"
    assert _start(client, h, lang="en")["stage"] == "letter"  # English starts at letter without English evidence


def test_safety_flag(client, kid, fakes, clock, monkeypatch):
    h, cid = kid
    asked = []

    def classify(db, *, school_id, text):
        asked.append(text)
        return "distress" if "HURT" in text else "learning"
    monkeypatch.setattr(features, "classify_child_input", classify)
    s = _start(client, h)
    _turn(client, h, s, s["item"]["id"], RIGHT)
    assert asked == []  # short answers to reading items are not classified
    s = _start(client, h)
    item = s["item"]
    t = _turn(client, h, s, item["id"], "HURT me " * 10)  # far longer than the target
    assert t["safety_flag"] == "distress" and t["next_item"]["id"] == item["id"] and t["attempt"] == 1
    assert "बड़े" in t["tutor"]["text"] and t["transcript_append"][0]["role"] == "tutor"
    with SessionLocal() as db:
        vs = db.get(VoiceSession, s["id"])
        assert vs.safety_flag == "distress" and vs.state["safety_flags"][0]["category"] == "distress"
        assert all("HURT" not in (r.text or "") for r in db.scalars(select(VoiceTurn).where(
            VoiceTurn.session_id == s["id"])))  # the child's words are not kept
    # open answers (make_sentence) are always classified
    fakes.kind["letter"] = "make_sentence"
    s = _start(client, h)
    t = _turn(client, h, s, s["item"]["id"], "HURT")
    assert t["safety_flag"] == "distress" and t["verdict"] == "none"
    assert [e[1] for e in _evidence(cid)] == ["correct"]  # only the first session's answer counted


def test_paragraph_followups_hide_answers(client, kid, fakes, clock):
    h, cid = kid
    fakes.paragraph = True
    s = _start(client, h)
    assert s["item"]["kind"] == "read_paragraph" and "followups" not in s["item"]
    assert s["item"]["display"]["text"] and s["item"]["target"]  # reading items show the text to read
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    q = t["next_item"]
    assert q["kind"] == "answer_question" and q["display"]["question"] == "Why?"
    assert not {"target", "accept", "keywords"} & set(q)


def test_end_report_stored_and_visible_to_parent_and_teacher(client, kid, sandbox, fakes, clock,
                                                             teacher_headers):
    h, cid = kid
    s = _start(client, h)
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    _turn(client, h, s, t["next_item"]["id"], NOPE)  # an unfinished item at the end
    clock.advance(60)
    r = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={"reason": "parent_stop"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["session_id"] == s["id"] and rep["narrative"]["parent_en"] == "Meena did well"
    assert rep["next_steps"]["en"] == ["practise"] and rep["narrative_status"] == "fallback"
    assert rep["end_reason"] == "parent_stop" and rep["minutes"] == 1.0
    kw = fakes.report_kwargs
    assert kw["lang"] == "hi" and kw["content"] is not None
    assert [i["result"] for i in kw["items"].values()] == ["first_try", "unfinished"]
    assert [(t["item_id"], t["attempt"], t["verdict"]) for t in kw["turns"]] == [
        (iid, 1, v) for iid, v in zip(kw["items"], ("correct", "wrong"))]  # judged tries only, no tutor lines
    # ending twice returns the stored report; turns after the end get the wrap-up
    assert client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h).json() == rep
    assert _turn(client, h, s, "whatever", RIGHT)["done"] is True
    d = client.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert d["session"]["status"] == "ended" and d["report"] == rep and d["session"]["item"] is None
    lst = client.get("/v1/parent/voice/sessions", headers=h).json()
    row = next(x for x in lst if x["id"] == s["id"])
    assert {"id", "lang", "started_at", "minutes", "items", "accuracy", "highest_stage", "status"} <= set(row)
    assert row["status"] == "ended" and row["items"] == 2
    th = sandbox["teacher_headers"]
    td = client.get(f"/v1/voice_sessions/{s['id']}", headers=th)
    assert td.status_code == 200 and td.json()["report"] == rep
    assert len(td.json()["session"]["transcript"]) >= 4
    tl = client.get(f"/v1/children/{cid}/voice_sessions", headers=th)
    assert tl.status_code == 200 and any(x["id"] == s["id"] for x in tl.json())
    # another school's teacher, and another child's parent, see nothing
    assert client.get(f"/v1/voice_sessions/{s['id']}", headers=teacher_headers).status_code == 404
    assert client.get(f"/v1/children/{cid}/voice_sessions", headers=teacher_headers).status_code == 404
    other, _ = _make_other_parent(sandbox)
    assert client.get(f"/v1/parent/voice/sessions/{s['id']}", headers=other).status_code == 404
    assert client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=other).status_code == 404
    assert client.get(f"/v1/voice_sessions/{s['id']}", headers=h).status_code == 403


def test_report_falls_back_when_report_modules_fail(client, kid, fakes, clock, monkeypatch):
    h, cid = kid

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(vse, "build_report", boom)
    monkeypatch.setattr(vse, "write_narrative", boom)
    s = _start(client, h)
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    _fail_item(client, h, s, t["next_item"])
    rep = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h).json()
    assert rep["items_attempted"] == 2 and rep["first_try"] == 1 and rep["failed"] == 1
    assert rep["accuracy"] == 0.5 and rep["mistakes"][0]["attempts"] == MAX_ATTEMPTS
    assert rep["narrative_status"] == "fallback" and "Meena" in rep["narrative"]["parent_en"]


def test_generation_failure_uses_emergency_items(client, kid, fakes, clock, monkeypatch):
    h, cid = kid

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(vse, "generate_items", boom)
    s = _start(client, h)
    assert s["item"]["kind"] == "read_letter" and s["item"]["checkpoint_id"] is None
    t = _turn(client, h, s, s["item"]["id"], RIGHT)
    assert t["next_item"] and _evidence(cid) == []


def test_parent_token_required(client, teacher_headers):
    assert client.post("/v1/parent/voice/sessions", json={"lang": "hi"}).status_code == 401
    assert client.post("/v1/parent/voice/sessions", headers=teacher_headers, json={"lang": "hi"}).status_code == 403


def _make_other_parent(sandbox):
    sandbox["roll"] += 1
    with SessionLocal() as db:
        c = Child(class_id=sandbox["class_id"], roll_no=sandbox["roll"], first_name="Other")
        db.add(c)
        db.flush()
        p = ParentAccount(school_id=sandbox["school_id"], child_id=c.id, phone_hash=hash_phone("9000000001"),
                          pin_hash=hash_pin("0000"))
        db.add(p)
        db.commit()
        return {"Authorization": f"Bearer {make_token(str(p.id), 'parent')}"}, c.id


def test_real_modules_end_to_end(client, kid, clock):
    """No fakes: the real item bank, assessment, tutor lines and report (no API key) work with the engine."""
    for mod in ("app.ai.voice_tutor", "app.speech.assess", "app.services.voice_report"):
        pytest.importorskip(mod)
    h, cid = kid
    s = _start(client, h)
    assert s["item"] and s["tutor"]["text"] and "{name}" not in s["tutor"]["text"]
    t = {"next_item": s["item"]}
    results = []
    for n in range(8):
        it = t["next_item"]
        with SessionLocal() as db:  # the server-side item (the app never sees hidden answers)
            raw = db.get(VoiceSession, s["id"]).state["items"][it["id"]]
        answer = raw.get("target") or (raw.get("display") or {}).get("text") or " ".join(raw.get("required_words") or [])
        t = _turn(client, h, s, it["id"], answer if n % 3 else "zzz qqq")
        results.append(t["verdict"])
        assert t["tutor"]["text"] and t["next_item"]
    assert "correct" in results
    rep = client.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h).json()
    assert rep["session_id"] == s["id"] and rep["items_attempted"] >= 1
    assert rep["narrative"]["parent_en"] and rep["narrative_status"] in ("ai", "fallback")
    assert {"first_try", "after_retry", "failed", "skipped", "accuracy", "highest_stage", "stages", "mistakes",
            "difficult_words", "difficult_sounds", "topics_attention", "fluency", "next_steps"} <= set(rep)
    assert "Meena" in json.dumps(rep, ensure_ascii=False) or "{name}" not in json.dumps(rep, ensure_ascii=False)
