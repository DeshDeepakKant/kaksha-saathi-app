"""Shared helpers for the parent-app end-to-end backend tests (test_parent_e2e_*.py).

No tests here. Everything destructive runs in a throwaway "sandbox" school (own school, teacher, class,
children and parent accounts) that is removed when the module finishes, so the seeded DEMO data the rest
of the suite counts on is never changed. The real voice engine, assessment and report modules are used
(no fakes); only ANTHROPIC/SARVAM keys are empty (conftest), so every AI path takes its deterministic
fallback.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.core.security import hash_phone, hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import (
    AiCall, Attendance, CaptureSession, Child, Classroom, CustomCheckpoint, CustomSubject, Evidence, GroupSession,
    HomeSession, LevelCheck, ParentAccount, Plan, Roadmap, RoadmapItem, School, Teacher, UsageCounter,
    VoiceSession, VoiceTurn,
)

DEMO_PARENT = {"school_code": "DEMO", "child_roll": 12, "parent_phone": "9876500000", "pin": "0000"}
WRONG = "zzqx"           # never right for any item kind
HIDDEN = ("target", "accept", "keywords")


def tok(sub, kind: str) -> dict:
    return {"Authorization": f"Bearer {make_token(str(sub), kind)}"}


class World:
    """A sandbox school with one class (grade 2) and as many children / parent accounts as a test needs."""

    def __init__(self):
        self.code = "E2" + uuid.uuid4().hex[:8].upper()
        with SessionLocal() as db:
            sch = School(name="E2E sandbox", code=self.code)
            db.add(sch)
            db.flush()
            t = Teacher(school_id=sch.id, name="E2E Teacher", pin_hash=hash_pin("4321"))
            db.add(t)
            db.flush()
            self.school_id, self.teacher_id = sch.id, t.id
            cls = Classroom(school_id=sch.id, teacher_id=t.id, grade=2, section="E", label="2E")
            db.add(cls)
            db.commit()
            self.class_id = cls.id
        self.teacher_headers = tok(self.teacher_id, "teacher")
        self._roll = 0
        self._sec = 0

    def klass(self, grade: int = 3) -> int:
        with SessionLocal() as db:
            self._sec += 1
            cls = Classroom(school_id=self.school_id, teacher_id=self.teacher_id, grade=grade,
                            section=f"X{self._sec}", label=f"{grade}X{self._sec}")
            db.add(cls)
            db.commit()
            return cls.id

    def child(self, name: str = "Meena", *, account: bool = True, consent: bool = True, roll: int | None = None,
              class_id: int | None = None, phone: str = "9000000000", pin: str = "0000",
              level: str | None = "beginner") -> dict:
        """-> {id, roll, name, class_id, headers (parent token or None), parent_id}

        `level`: the level-check result (highest level passed) recorded for both subjects. Voice sessions
        practise the child's level, so "beginner" means they start at `letter`, the bottom of the ladder.
        None: no evidence at all (the plan falls back to placement)."""
        if roll is None:
            self._roll += 1
            roll = self._roll
        with SessionLocal() as db:
            c = Child(class_id=class_id or self.class_id, roll_no=roll, first_name=name,
                      consent_on=date.today() - timedelta(days=5) if consent else None,
                      consent_source="parent_form_photo" if consent else None)
            db.add(c)
            db.flush()
            if level:
                idx = {"beginner": -1, "letter": 0, "word": 1, "sentence": 2, "story": 3}[level]
                for subject in ("literacy", "english"):
                    db.add(LevelCheck(school_id=self.school_id, class_id=c.class_id, child_id=c.id, subject=subject,
                                      level_index=idx, level_key=level, at=datetime.utcnow() - timedelta(days=3)))
            pid, headers = None, None
            if account:
                p = ParentAccount(school_id=self.school_id, child_id=c.id, phone_hash=hash_phone(phone),
                                  pin_hash=hash_pin(pin))
                db.add(p)
                db.flush()
                pid, headers = p.id, tok(p.id, "parent")
            db.commit()
            return {"id": c.id, "roll": roll, "name": name, "class_id": c.class_id, "headers": headers,
                    "parent_id": pid}

    def cleanup(self):
        with SessionLocal() as db:
            sid = self.school_id
            cls_ids = select(Classroom.id).where(Classroom.school_id == sid)
            kid_ids = select(Child.id).where(Child.class_id.in_(cls_ids))
            vs_ids = select(VoiceSession.id).where(VoiceSession.school_id == sid)
            db.execute(delete(LevelCheck).where(LevelCheck.school_id == sid))
            db.execute(delete(VoiceTurn).where(VoiceTurn.session_id.in_(vs_ids)))
            db.execute(delete(VoiceSession).where(VoiceSession.school_id == sid))
            db.execute(delete(Evidence).where(Evidence.school_id == sid))
            db.execute(delete(CaptureSession).where(CaptureSession.school_id == sid))
            db.execute(delete(HomeSession).where(HomeSession.school_id == sid))
            db.execute(delete(Attendance).where(Attendance.child_id.in_(kid_ids)))
            db.execute(delete(LevelCheck).where(LevelCheck.school_id == sid))
            db.execute(delete(GroupSession).where(GroupSession.school_id == sid))
            db.execute(delete(Plan).where(Plan.school_id == sid))
            db.execute(delete(RoadmapItem).where(RoadmapItem.roadmap_id.in_(
                select(Roadmap.id).where(Roadmap.school_id == sid))))
            db.execute(delete(Roadmap).where(Roadmap.school_id == sid))
            db.execute(delete(CustomCheckpoint).where(CustomCheckpoint.school_id == sid))
            db.execute(delete(CustomSubject).where(CustomSubject.school_id == sid))
            db.execute(delete(AiCall).where(AiCall.school_id == sid))
            db.execute(delete(UsageCounter).where(UsageCounter.school_id == sid))
            db.execute(delete(ParentAccount).where(ParentAccount.school_id == sid))
            db.execute(delete(Child).where(Child.class_id.in_(cls_ids)))
            db.execute(delete(Classroom).where(Classroom.school_id == sid))
            db.execute(delete(Teacher).where(Teacher.school_id == sid))
            db.execute(delete(School).where(School.id == sid))
            db.commit()


# ------------------------------------------------------------------ the voice API as the app drives it
def start(client, h, lang="hi", expect=200):
    r = client.post("/v1/parent/voice/sessions", headers=h, json={"lang": lang})
    assert r.status_code == expect, r.text
    return r.json()


def turn(client, h, sid, item_id, transcript=None, *, ctid=None, audio=None, duration_s=None, expect=200,
         filename="t.wav"):
    meta = {"item_id": item_id, "client_turn_id": ctid or uuid.uuid4().hex}
    if transcript is not None:
        meta["transcript"] = transcript
    if duration_s is not None:
        meta["duration_s"] = duration_s
    files = {"audio": (filename, audio, "audio/wav")} if audio is not None else None
    r = client.post(f"/v1/parent/voice/sessions/{sid}/turn", headers=h, data={"meta": json.dumps(meta)}, files=files)
    assert r.status_code == expect, (r.status_code, r.text[:300])
    return r.json()


def skip(client, h, sid, item_id, ctid=None, expect=200):
    body = {"item_id": item_id}
    if ctid:
        body["client_turn_id"] = ctid
    r = client.post(f"/v1/parent/voice/sessions/{sid}/skip", headers=h, json=body)
    assert r.status_code == expect, r.text[:300]
    return r.json()


def end(client, h, sid, reason=None, expect=200):
    r = client.post(f"/v1/parent/voice/sessions/{sid}/end", headers=h, json={"reason": reason} if reason else None)
    assert r.status_code == expect, r.text[:300]
    return r.json()


def full_item(sid: int, item_id: str) -> dict:
    """The item with its hidden answer fields, read straight from the engine's stored state."""
    with SessionLocal() as db:
        return db.get(VoiceSession, sid).state["items"][item_id]


def right_answer(it: dict) -> str:
    """What a child who reads/answers correctly would say (the recogniser's transcript)."""
    k = it["kind"]
    if k == "make_sentence":
        return " ".join(it["required_words"]) + (" है" if it["lang"] == "hi" else " is nice")
    if k == "answer_question":
        return (it.get("keywords") or [it.get("target")])[0]
    return it.get("target") or it["display"]["text"]


def home_voice_evidence(child_id: int) -> list[tuple[str, str]]:
    with SessionLocal() as db:
        return [(e.checkpoint_id, e.result) for e in db.scalars(
            select(Evidence).where(Evidence.child_id == child_id, Evidence.source == "home_voice")
            .order_by(Evidence.id))]


def silent_wav(seconds: float = 0.3, rate: int = 16000) -> bytes:
    """A real, valid 16-bit mono WAV of pure silence."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ------------------------------------------------------------------ fixtures (import them into a test module)
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def rc():
    """A client that turns server crashes into 500 responses, so a crash is a FAIL line, not an exception."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def w():
    world = World()
    yield world
    world.cleanup()
