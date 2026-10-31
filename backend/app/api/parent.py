"""Parent API: consent gate, pack, structured session (harness turns), history, data deletion.

A child can only start a session after the parent gate (phone + PIN). The session needs a
downloaded pack; when offline the app runs the same harness locally with canned lines.

Content language: Hindi/English responses are unchanged. For a parent whose content language is
another one, the parent-facing texts gain machine-translated `<base>_<lang>` fields (labelled
`content_lang` / `machine_translated`). The practice activities themselves are reviewed Hindi content
judged against Hindi targets, so their speech-to-text stays Hindi (with the parent's provider).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import features
from app.api.deps import current_parent, validate_media
from app.core.security import hash_phone, hash_pin, make_token, verify_pin
from app.db import get_db
from app.models.tables import (Child, Classroom, Evidence, HomeSession, ParentAccount, School, VoiceSession,
                               VoiceTurn)
from app.services import ledger, parent_insights, tutor
from app.services.mastery import find_gap
from app.services.content import get_content
from app.speech import get_asr
from app.speech.scorer import score_read

router = APIRouter(prefix="/v1")


class ConsentIn(BaseModel):
    school_code: str
    child_roll: int
    parent_phone: str = Field(min_length=8, max_length=15)
    consents: bool
    pin: str = Field(min_length=4, max_length=6)
    language: str = "hi"


@router.post("/parent/consent")
def parent_consent(body: ConsentIn, db: Session = Depends(get_db)):
    if not body.consents:
        raise HTTPException(422, "consent is required")
    school = db.scalar(select(School).where(School.code == body.school_code.upper().strip()))
    if not school:
        raise HTTPException(404, "school not found")
    kids = _children_by_roll(db, school.id, body.child_roll)  # lowest class first, deterministic
    if not kids:
        raise HTTPException(404, "child not found")
    child = kids[0]
    if child.consent_on is None:
        raise HTTPException(403, "school has not recorded a parent consent form for this child yet")
    if db.scalar(select(ParentAccount).where(ParentAccount.child_id == child.id)):
        raise HTTPException(409, "parent account already set up. Sign in instead")
    p = ParentAccount(school_id=school.id, child_id=child.id, phone_hash=hash_phone(body.parent_phone),
                      pin_hash=hash_pin(body.pin), language=body.language)
    db.add(p)
    db.flush()
    return {"token": make_token(str(p.id), "parent"), "child": _pub(child)}


class ParentLoginIn(BaseModel):
    school_code: str
    child_roll: int
    parent_phone: str
    pin: str


@router.post("/parent/login")
def parent_login(body: ParentLoginIn, db: Session = Depends(get_db)):
    school = db.scalar(select(School).where(School.code == body.school_code.upper().strip()))
    if not school:
        raise HTTPException(401, "school not found")
    kids = _children_by_roll(db, school.id, body.child_roll)
    if not kids:
        raise HTTPException(401, "child not found")
    phone = hash_phone(body.parent_phone)
    for child in kids:
        p = db.scalar(select(ParentAccount).where(ParentAccount.child_id == child.id))
        if p and p.phone_hash == phone and verify_pin(body.pin, p.pin_hash):
            return {"token": make_token(str(p.id), "parent"), "child": _pub(child)}
    raise HTTPException(401, "invalid credentials")


def _children_by_roll(db: Session, school_id: int, roll: int) -> list[Child]:
    return list(db.scalars(select(Child).join(Classroom, Child.class_id == Classroom.id)
                           .where(Classroom.school_id == school_id, Child.roll_no == roll)
                           .order_by(Classroom.grade, Classroom.section)))


def _pub(child: Child) -> dict:
    return {"id": child.id, "first_name": child.first_name, "roll_no": child.roll_no, "class": None}


@router.get("/parent/child")
def parent_child(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    child = db.get(Child, parent.child_id)
    cls = db.get(Classroom, child.class_id)
    st = ledger.child_statuses(db, [child.id])[child.id]
    focus = tutor.choose_focus({cp: r.status for cp, r in st.items()}, get_content())
    label = {"needs_intervention": "अभी अभ्यास चाहिए", "needs_practice": "अभ्यास जारी रखें",
             "on_track": "अच्छा चल रहा है", "not_started": "नया शुरू करें"}
    label_en = {"needs_intervention": "Needs practice now", "needs_practice": "Keep practising",
                "on_track": "Going well", "not_started": "Start something new"}
    cps = get_content().checkpoints
    names = [{"checkpoint_id": f["checkpoint_id"], "status": f["status"],
              "title_hi": cps[f["checkpoint_id"]].title_hi if f["checkpoint_id"] in cps else "",
              "title_en": cps[f["checkpoint_id"]].title_en if f["checkpoint_id"] in cps else "",
              "label_hi": label.get(f["status"], ""),
              "label_en": label_en.get(f["status"], "")} for f in focus]
    # The home screen reads `child` verbatim; merge the school-gate identity into it.
    return _localized(db, parent, child, {"child": {**_pub(child), "class": cls.label}, "focus": names,
                                          "streak": _streak(db, child.id)})


def _localized(db: Session, parent: ParentAccount, child: Child, payload: dict) -> dict:
    """Additive `<base>_<lang>` fields for a parent whose content language is not hi/en."""
    lang = parent_insights.parent_content_lang(db, parent)
    if lang in ("hi", "en"):
        return payload
    return parent_insights.localize(db, payload, lang, school_id=parent.school_id, name=child.first_name)


def _hindi_extra(db: Session, parent: ParentAccount, texts: list[str]) -> tuple[str, list[str], bool] | None:
    """Hindi-only texts (home summaries) in the parent's content language, or None for hi/en."""
    lang = parent_insights.parent_content_lang(db, parent)
    if lang in ("hi", "en"):
        return None
    child = db.get(Child, parent.child_id)
    got = parent_insights.translate_en(db, texts, lang, school_id=parent.school_id, source="hi",
                                       name=child.first_name if child else None)
    return lang, [t for t, _ in got], any(ok for _, ok in got)


def _stt_configured(lang: str) -> bool:
    try:
        from app.speech import capabilities
        return bool(capabilities.providers_for("stt", lang))
    except Exception:
        return False


def _transcribe(db: Session, parent: ParentAccount, audio: bytes, filename: str, lang: str = "hi") -> str:
    """Speech-to-text with the parent's preferred provider (the speech layer falls back)."""
    from app import speech
    fn = getattr(speech, "transcribe", None)
    if fn is None or not _stt_configured(lang):  # no provider set up: the legacy (mock) recogniser
        return get_asr().transcribe(audio, filename).text
    try:
        from app.services import prefs
        preferred = prefs.provider_for(db, parent=parent)
    except Exception:
        preferred = "sarvam"
    return fn(audio, filename, lang=lang, preferred=preferred).text


def _streak(db: Session, child_id: int) -> int:
    days = {s.started_at.date() for s in db.scalars(select(HomeSession).where(HomeSession.child_id == child_id))}
    days |= {v.started_at.date() for v in db.scalars(select(VoiceSession).where(VoiceSession.child_id == child_id))}
    n, d = 0, datetime.now(timezone.utc).date()
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


@router.get("/parent/pack")
def parent_pack(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    """Downloadable session pack: activities + canned lines, usable with no network."""
    child = db.get(Child, parent.child_id)
    st = ledger.child_statuses(db, [child.id])[child.id]
    plan = tutor.build_plan(child.first_name, {cp: r.status for cp, r in st.items()}, get_content())
    plan["canned_lines"] = features.FALLBACK_LINES
    plan["version"] = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    return plan


def _session_plan(db: Session, child: Child, before: datetime | None = None) -> dict:
    """Plan from evidence recorded before the session, so home turns can't reshuffle it mid-session."""
    st = ledger.child_statuses(db, [child.id], before=before)[child.id]
    return tutor.build_plan(child.first_name, {cp: r.status for cp, r in st.items()}, get_content())


class SessionStart(BaseModel):
    offline: bool = False


@router.post("/parent/sessions")
def start_session(body: SessionStart | None = None, parent: ParentAccount = Depends(current_parent),
                  db: Session = Depends(get_db)):
    child = db.get(Child, parent.child_id)
    plan = _session_plan(db, child)
    s = HomeSession(school_id=parent.school_id, child_id=child.id, offline=bool(body and body.offline))
    db.add(s)
    db.flush()
    first = plan["activities"][0] if plan["activities"] else None
    intro = tutor.fixed_intro(tutor.activity_from_dict(first), child.first_name) if first else "आज कुछ अभ्यास नहीं है।"
    return {"session_id": s.id, "plan": plan, "index": 0, "intro_hi": intro,
            "activity": first, "max_attempts": tutor.MAX_ATTEMPTS}


class TurnMeta(BaseModel):
    index: int
    attempt: int
    activity_ref: str
    tap: str | None = None
    transcript: str | None = None
    offline: bool = False


@router.post("/parent/sessions/{session_id}/turn")
async def session_turn(session_id: int, meta: str = Form(...), audio: UploadFile | None = File(None),
                       parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    hs = db.get(HomeSession, session_id)
    if not hs or hs.child_id != parent.child_id:
        raise HTTPException(404, "session not found")
    child = db.get(Child, parent.child_id)
    cls = db.get(Classroom, child.class_id)
    try:
        m = TurnMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(422, f"bad meta: {e.errors()[0]['msg']}")
    plan = _session_plan(db, child, before=hs.started_at)
    if m.index < 0 or m.index >= len(plan["activities"]):
        raise HTTPException(422, "bad activity index")
    # Judge the activity the child actually sees; the index only places it in the plan.
    act = tutor.find_activity(m.activity_ref, get_content()) or tutor.activity_from_dict(plan["activities"][m.index])
    audio_bytes = await audio.read() if audio else b""
    validate_media(audio_bytes, None)
    transcript = m.transcript
    asr_status = "provided"
    if not transcript and audio_bytes:
        try:
            transcript = _transcribe(db, parent, audio_bytes, audio.filename or "turn.wav")
            asr_status = "asr" if transcript else "silent"
        except Exception:  # ASR outage: judge as unheard rather than failing the turn
            transcript, asr_status = "", "failed"

    # child-safety classification on anything the child said (online only)
    category = "learning"
    if transcript and not m.offline:
        category = features.classify_child_input(db, school_id=parent.school_id, text=transcript)
    if category in ("distress", "personal"):
        return {"judged": "none", "line_hi": "यह बात किसी बड़े (मम्मी, पापा या अध्यापक) को बताइए।",
                "line_status": "safety", "advance": False, "next_index": m.index, "next_activity": None,
                "done": False, "record_evidence": False, "safety_flag": category, "asr": asr_status,
                "attempt": m.attempt, "activity": act.__dict__}

    turn = tutor.next_turn(db, child_name=child.first_name, plan=plan, index=m.index, attempt=m.attempt,
                           activity=act, transcript=transcript, tap=m.tap, school_id=parent.school_id,
                           offline=m.offline)
    if turn["record_evidence"]:
        tutor.record_evidence(db, school_id=parent.school_id, class_id=child.class_id, child_id=child.id,
                              activity=act, verdict="correct" if turn["judged"] == "correct" else "wrong",
                              home_session_id=hs.id)
        hs.evidence_count += 1
    turn["asr"] = asr_status
    turn["heard"] = transcript
    turn["activity"] = act.__dict__
    return turn


@router.post("/parent/sessions/{session_id}/end")
def end_session(session_id: int, summary: str | None = Form(None), parent: ParentAccount = Depends(current_parent),
                db: Session = Depends(get_db)):
    hs = db.get(HomeSession, session_id)
    if not hs or hs.child_id != parent.child_id:
        raise HTTPException(404, "session not found")
    hs.ended_at = datetime.now(timezone.utc)
    child = db.get(Child, parent.child_id)
    evs = list(db.scalars(select(Evidence).where(Evidence.child_id == child.id,
                                                 Evidence.at >= hs.started_at)))
    struggles = sorted({e.checkpoint_id for e in evs if e.result == "incorrect"})
    text, status = features.home_summary(db, school_id=parent.school_id, activities=[e.checkpoint_id for e in evs],
                                          struggles=[get_content().checkpoints[s].title_hi for s in struggles
                                                     if s in get_content().checkpoints])
    hs.summary_hi = text
    out = {"summary_hi": text, "summary_status": status, "evidence": hs.evidence_count}
    extra = _hindi_extra(db, parent, [text]) if text else None
    if extra:
        lang, (local,), mt = extra
        out.update({f"summary_{lang}": local, "content_lang": lang, "machine_translated": mt})
    return out


class OfflineItem(BaseModel):
    activity_ref: str
    tap: str | None = None  # last tap; spoken items done offline carry none


class OfflineSync(BaseModel):
    started_at: datetime
    ended_at: datetime | None = None
    session_id: int | None = None  # set when the session started online and lost the network
    items: list[OfflineItem] = Field(default_factory=list, max_length=50)


@router.post("/parent/sessions/sync")
def sync_offline_session(body: OfflineSync, parent: ParentAccount = Depends(current_parent),
                         db: Session = Depends(get_db)):
    """Upload practice done offline. Taps are re-judged here; spoken items can't be verified
    offline, so they count as practised (no evidence). Safe to retry: a synced session is skipped."""
    child = db.get(Child, parent.child_id)
    now = datetime.now(timezone.utc)
    started = min(body.started_at.astimezone(timezone.utc), now).replace(tzinfo=None)
    ended = min((body.ended_at or now).astimezone(timezone.utc), now)
    if body.session_id is not None:
        hs = db.get(HomeSession, body.session_id)
        if not hs or hs.child_id != child.id:
            raise HTTPException(404, "session not found")
        if hs.ended_at is not None:
            return {"synced": False, "session_id": hs.id, "evidence": hs.evidence_count}
    else:
        hs = db.scalar(select(HomeSession).where(HomeSession.child_id == child.id,
                                                 HomeSession.started_at == started))
        if hs:
            return {"synced": False, "session_id": hs.id, "evidence": hs.evidence_count}
        hs = HomeSession(school_id=parent.school_id, child_id=child.id, started_at=started, offline=True)
        db.add(hs)
        db.flush()
    content = get_content()
    struggles, practised = set(), []
    for it in body.items:
        act = tutor.find_activity(it.activity_ref, content)
        if not act:
            continue
        practised.append(act.checkpoint_id)
        if not act.type.startswith("tap") or it.tap is None:
            continue
        verdict = tutor.judge(act, transcript=None, tap=it.tap)
        tutor.record_evidence(db, school_id=parent.school_id, class_id=child.class_id, child_id=child.id,
                              activity=act, verdict=verdict, home_session_id=hs.id)
        hs.evidence_count += 1
        if verdict != "correct" and act.checkpoint_id in content.checkpoints:
            struggles.add(content.checkpoints[act.checkpoint_id].title_hi)
    hs.ended_at = ended
    hs.summary_hi, _ = features.home_summary(db, school_id=parent.school_id, activities=practised,
                                             struggles=sorted(struggles))
    return {"synced": True, "session_id": hs.id, "evidence": hs.evidence_count}


@router.get("/parent/history")
def parent_history(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(HomeSession).where(HomeSession.child_id == parent.child_id)
                           .order_by(HomeSession.started_at.desc()).limit(20)))
    out = [{"id": s.id, "started_at": s.started_at.isoformat(), "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "activities": s.evidence_count, "summary_hi": s.summary_hi, "offline": s.offline} for s in rows]
    texts = list(dict.fromkeys(r["summary_hi"] for r in out if r["summary_hi"]))
    extra = _hindi_extra(db, parent, texts) if texts else None
    if extra:
        lang, local, mt = extra
        by_src = dict(zip(texts, local))
        for r in out:
            if r["summary_hi"]:
                r[f"summary_{lang}"] = by_src[r["summary_hi"]]
                r["machine_translated"] = mt
    return out


@router.delete("/parent/child/data")
def parent_delete(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    db.execute(delete(Evidence).where(Evidence.child_id == parent.child_id,
                                      Evidence.source.in_(("home_voice", "home_tap"))))
    db.execute(delete(HomeSession).where(HomeSession.child_id == parent.child_id))
    voice_ids = select(VoiceSession.id).where(VoiceSession.child_id == parent.child_id)
    db.execute(delete(VoiceTurn).where(VoiceTurn.session_id.in_(voice_ids)))
    db.execute(delete(VoiceSession).where(VoiceSession.child_id == parent.child_id))
    return {"deleted": True}


@router.get("/parent/teacher_note")
def teacher_note(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    """The 'what to practise' card is derived from school-confirmed evidence only."""
    child = db.get(Child, parent.child_id)
    st = ledger.child_statuses(db, [child.id])[child.id]
    g = find_gap(get_content(), {cp: r.status for cp, r in st.items()})
    if not g:
        return {"has_gap": False}
    cp = get_content().checkpoints.get(g.checkpoint_id)
    return _localized(db, parent, child, {
        "has_gap": True, "title_hi": cp.title_hi if cp else g.checkpoint_id,
        "title_en": cp.title_en if cp else g.checkpoint_id, "chapter": cp.chapter if cp else "", "status": g.status})
