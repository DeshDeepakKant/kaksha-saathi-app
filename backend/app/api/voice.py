"""30-minute voice learning session API (docs/voice_session_contract.md). Parent runs it; teacher reads it.

The engine (`services/voice_session.py`) returns raw items; this layer fills the child's name into
`{name}` placeholders and never sends the answer of an item the child must work out
(`target`/`accept`/`keywords` of build_word, answer_question, say_sound).

Language: `lang` may be any content language the speech providers can both hear and speak
(`speech.capabilities.content_languages()`, plus hi/en which always work by typing and the phone's
voice); omitted, it is the parent's content language (Settings), else Hindi.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.deps import current_parent, current_teacher, owned_child, validate_media
from app.db import get_db
from app.models.tables import Child, Classroom, HomeFocus, ParentAccount, Teacher, VoiceSession
from app.services import ledger, prefs, voice_plan, voice_session as engine
from app.services.content import get_content
from app.services.voice_types import STAGES, VOICE_LANGS
from app.speech import capabilities

router = APIRouter(prefix="/v1")

HIDDEN_ANSWER_KINDS = ("build_word", "answer_question", "say_sound")
_ANSWER_KEYS = ("target", "accept", "keywords")


# ------------------------------------------------------------------ output shaping
def _fill(obj, name: str):
    if isinstance(obj, str):
        return obj.replace("{name}", name)
    if isinstance(obj, list):
        return [_fill(x, name) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, name) for k, v in obj.items()}
    return obj


def public_item(item: dict | None) -> dict | None:
    if not item:
        return None
    it = {k: v for k, v in item.items() if k not in ("followups", "followup_ids")}
    if it.get("kind") in HIDDEN_ANSWER_KINDS:
        for k in _ANSWER_KEYS:
            it.pop(k, None)
    return it


def _public(payload: dict, name: str, item_key: str) -> dict:
    out = copy.deepcopy(payload)
    if item_key in out:
        out[item_key] = public_item(out[item_key])
    return _fill(out, name)


def _detail(db: Session, vs: VoiceSession, name: str) -> dict:
    d = engine.detail(db, vs)
    return {"session": _public(d["session"], name, "item"), "report": _fill(d["report"], name)}


# ------------------------------------------------------------------ parent
class StartIn(BaseModel):
    lang: str | None = Field(default=None, max_length=8)  # omitted: the parent's content language


def session_langs() -> list[str]:
    """Languages a voice session can run in right now (needs item, line and speech support)."""
    try:
        langs = list(capabilities.content_languages())
    except Exception:
        langs = []
    return [c for c in dict.fromkeys(["hi", "en", *langs]) if c in VOICE_LANGS]


def _session_lang(db: Session, parent: ParentAccount, asked: str | None) -> str:
    allowed = session_langs()
    if asked:
        if asked not in allowed:
            raise HTTPException(422, f"lang must be one of: {', '.join(allowed)}")
        return asked
    try:
        mine = prefs.content_lang_for(db, parent=parent)
    except Exception:
        mine = "hi"
    return mine if mine in allowed else "hi"


def _provider(db: Session, parent: ParentAccount) -> str | None:
    try:
        return prefs.provider_for(db, parent=parent)
    except Exception:
        return None


class TurnMeta(BaseModel):
    item_id: str = Field(min_length=1, max_length=80)
    client_turn_id: str = Field(min_length=1, max_length=64)
    transcript: str | None = Field(default=None, max_length=2000)
    duration_s: float | None = Field(default=None, ge=0, le=600)


class SkipIn(BaseModel):
    item_id: str = Field(min_length=1, max_length=80)
    client_turn_id: str | None = Field(default=None, max_length=64)


class EndIn(BaseModel):
    reason: Literal["time_up", "parent_stop"] = "parent_stop"


def _own(db: Session, parent: ParentAccount, session_id: int) -> VoiceSession:
    vs = db.get(VoiceSession, session_id)
    if not vs or vs.child_id != parent.child_id:
        raise HTTPException(404, "session not found")
    return vs


def _name(db: Session, child_id: int) -> str:
    return db.get(Child, child_id).first_name


@router.post("/parent/voice/sessions")
def start_voice_session(body: StartIn | None = None, parent: ParentAccount = Depends(current_parent),
                        db: Session = Depends(get_db)):
    child = db.get(Child, parent.child_id)
    lang = _session_lang(db, parent, (body or StartIn()).lang)
    vs = engine.start(db, child=child, lang=lang, provider=_provider(db, parent))
    return _public(engine.session_view(db, vs), child.first_name, "item")


@router.post("/parent/voice/sessions/{session_id}/turn")
async def voice_turn(session_id: int, meta: str = Form(...), audio: UploadFile | None = File(None),
                     parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    vs = _own(db, parent, session_id)
    try:
        m = TurnMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(422, f"bad meta: {e.errors()[0]['msg']}")
    audio_bytes = await audio.read() if audio else b""
    validate_media(audio_bytes, None)
    try:
        t = engine.turn(db, vs, item_id=m.item_id, client_turn_id=m.client_turn_id, transcript_text=m.transcript,
                        duration_s=m.duration_s, audio=audio_bytes,
                        filename=(audio.filename if audio else None) or "turn.wav")
    except engine.StaleItem as e:
        raise HTTPException(409, f"item {m.item_id} is not the current item ({e.args[0]})")
    return _public(t, _name(db, vs.child_id), "next_item")


@router.post("/parent/voice/sessions/{session_id}/skip")
def voice_skip(session_id: int, body: SkipIn, parent: ParentAccount = Depends(current_parent),
               db: Session = Depends(get_db)):
    vs = _own(db, parent, session_id)
    t = engine.skip(db, vs, item_id=body.item_id, client_turn_id=body.client_turn_id)
    return _public(t, _name(db, vs.child_id), "next_item")


@router.post("/parent/voice/sessions/{session_id}/end")
def voice_end(session_id: int, body: EndIn | None = None, parent: ParentAccount = Depends(current_parent),
              db: Session = Depends(get_db)):
    vs = _own(db, parent, session_id)
    report = engine.end(db, vs, reason=(body or EndIn()).reason)
    return _fill(report, _name(db, vs.child_id))


@router.get("/parent/voice/plan")
def voice_plan_preview(lang: str | None = Query(default=None, max_length=8),
                       parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    """The plan for the child's next session in `lang` ("Today's practice" before starting). Writes nothing."""
    child = db.get(Child, parent.child_id)
    return voice_plan.preview(db, child, _session_lang(db, parent, lang))


@router.get("/parent/voice/sessions")
def voice_sessions(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return engine.list_for_child(db, parent.child_id)


@router.get("/parent/voice/sessions/{session_id}")
def voice_session_detail(session_id: int, parent: ParentAccount = Depends(current_parent),
                         db: Session = Depends(get_db)):
    vs = _own(db, parent, session_id)
    return _detail(db, vs, _name(db, vs.child_id))


# ------------------------------------------------------------------ teacher (read-only, tenant-checked)
@router.get("/children/{child_id}/voice_sessions")
def child_voice_sessions(child_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    owned_child(child_id, teacher, db)
    return engine.list_for_child(db, child_id)


@router.get("/voice_sessions/{session_id}")
def teacher_voice_session(session_id: int, teacher: Teacher = Depends(current_teacher),
                          db: Session = Depends(get_db)):
    vs = db.get(VoiceSession, session_id)
    if not vs:
        raise HTTPException(404, "session not found")
    try:
        child = owned_child(vs.child_id, teacher, db)
    except HTTPException:
        raise HTTPException(404, "session not found")
    return _detail(db, vs, child.first_name)


# ------------------------------------------------------------------ teacher: home practice focus
Subject = Literal["literacy", "english"]


class HomeFocusIn(BaseModel):
    subject: Subject
    stage: str
    checkpoint_ids: list[str] = Field(default_factory=list, max_length=8)
    note: str | None = Field(default=None, max_length=200)
    days: int = Field(default=7, ge=1, le=30)


def _deactivate(db: Session, child_id: int, subject: str) -> None:
    db.execute(update(HomeFocus).where(HomeFocus.child_id == child_id, HomeFocus.subject == subject,
                                       HomeFocus.active.is_(True)).values(active=False))


@router.get("/children/{child_id}/home_focus")
def get_home_focus(child_id: int, subject: Subject = "literacy", teacher: Teacher = Depends(current_teacher),
                   db: Session = Depends(get_db)):
    child = owned_child(child_id, teacher, db)
    return voice_plan.home_focus_view(db, child, subject)


@router.put("/children/{child_id}/home_focus")
def put_home_focus(child_id: int, body: HomeFocusIn, teacher: Teacher = Depends(current_teacher),
                   db: Session = Depends(get_db)):
    child = owned_child(child_id, teacher, db)
    if body.stage not in STAGES:
        raise HTTPException(422, f"stage must be one of: {', '.join(STAGES)}")
    content = get_content()
    for cp in body.checkpoint_ids:
        c = content.checkpoints.get(cp)
        if c is None or (cp not in content.custom_ids and c.subject != body.subject):
            raise HTTPException(422, f"unknown {body.subject} checkpoint: {cp}")
        if cp in content.custom_ids and not cp.startswith(f"C{teacher.school_id}-"):
            raise HTTPException(422, f"unknown {body.subject} checkpoint: {cp}")  # another school's topic
    _deactivate(db, child.id, body.subject)
    cls = db.get(Classroom, child.class_id)
    note = (body.note or "").strip() or None
    db.add(HomeFocus(school_id=cls.school_id, child_id=child.id, subject=body.subject, stage=body.stage,
                     checkpoint_ids=list(dict.fromkeys(body.checkpoint_ids)), note=note, created_by=teacher.id,
                     created_at=datetime.now(timezone.utc), until=ledger.school_today() + timedelta(days=body.days),
                     active=True))
    db.flush()
    return voice_plan.home_focus_view(db, child, body.subject)


@router.delete("/children/{child_id}/home_focus")
def delete_home_focus(child_id: int, subject: Subject = "literacy", teacher: Teacher = Depends(current_teacher),
                      db: Session = Depends(get_db)):
    child = owned_child(child_id, teacher, db)
    _deactivate(db, child.id, subject)
    db.flush()
    return voice_plan.home_focus_view(db, child, subject)
