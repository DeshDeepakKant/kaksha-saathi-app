"""Teacher API: auth, roster, roadmaps, captures (note/photo/voice/tap/probe), evidence confirm, plans,
profiles, export/delete.

Design rules enforced here:
  * AI output is always a *proposal*; only /captures/{id}/confirm (or the zero-AI tap route) writes
    confirmed evidence.
  * Every child/class access is tenant-scoped through `owned_class` / `owned_child`.
  * Arithmetic on work pages is recomputed in code; the model's verdict never overrides it.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai import features
from app.ai.llm import budget_remaining
from app.api.deps import current_teacher, image_media_type, owned_child, owned_class, validate_media
from app.core.security import decode_token, make_token, verify_pin
from app.db import get_db
from app.models.tables import (
    AiCall, Attendance, CaptureSession, Child, Classroom, Evidence, GroupSession, InterventionLog, LevelCheck,
    ParentAccount, Plan, Roadmap, RoadmapItem, School, Teacher,
)
from app.services import content_lang, followups, ledger, prefs
from app.services.subjects import resolve_subject
from app.services.content import get_content, match_checkpoint
from app.services.mastery import RESULT_VALUES
from app.services.resolver import resolve_names
from app.speech import get_asr, has_asr  # noqa: F401 - get_asr unused here now (STT: content_lang.transcribe); tests still patch it
from app.speech.scorer import score_read

router = APIRouter(prefix="/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _subject(subject: str, db: Session, teacher: Teacher) -> str:
    """Normalise a subject for this school; an unknown one is a 422, not an empty board."""
    return resolve_subject(db, teacher.school_id, subject)


def _cp(content, cid: str, school_id: int):
    """Checkpoint by id, or None. A school's custom topics (`C<school>-<n>`) are visible only to it."""
    cp = content.checkpoints.get(cid or "")
    if cp is not None and cid in content.custom_ids and not cid.startswith(f"C{school_id}-"):
        return None
    return cp


def toast_lines() -> dict:
    """Canned, teacher-reviewed UI lines shared by both apps (served via /v1/me)."""
    return {
        "grid_saved": "दर्ज हो गया।",
        "offline": "इंटरनेट नहीं है — बाद में दोबारा कोशिश करें।",
        "reassess_done": "अपडेट हो गया — समूह बदल सकते हैं।",
    }


# ------------------------------------------------------------------ auth & bootstrap
class LoginIn(BaseModel):
    school_code: str
    pin: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    school = db.scalar(select(School).where(School.code == body.school_code.upper().strip()))
    if not school:
        raise HTTPException(401, "school not found")
    for t in db.scalars(select(Teacher).where(Teacher.school_id == school.id)):
        if verify_pin(body.pin, t.pin_hash):
            return {"token": make_token(str(t.id), "teacher"),
                    "teacher": {"id": t.id, "name": t.name, "school": school.name}}
    raise HTTPException(401, "wrong PIN")


@router.get("/me")
def me(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    school = db.get(School, teacher.school_id)
    return {"id": teacher.id, "name": teacher.name, "school": school.name,
            "capabilities": {"asr": has_asr(), "ai": features.ai_ready()},
            "budget_left_inr": round(budget_remaining(db, teacher.school_id), 2),
            "toasts": toast_lines()}


# ------------------------------------------------------------------ classes / roster
@router.get("/classes")
def list_classes(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Classroom).where(Classroom.school_id == teacher.school_id,
                                                Classroom.teacher_id == teacher.id)):
        n = db.scalar(select(func.count(Child.id)).where(Child.class_id == c.id))
        cons = db.scalar(select(func.count(Child.id)).where(Child.class_id == c.id,
                                                               Child.consent_on.is_not(None)))
        out.append({"id": c.id, "label": c.label, "grade": c.grade, "section": c.section,
                    "children": n, "consented": cons})
    return out


class ChildIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    roll_no: int
    consent_source: str | None = None


@router.post("/classes/{class_id}/children")
def add_child(class_id: int, body: ChildIn, teacher: Teacher = Depends(current_teacher),
              db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    if db.scalar(select(Child).where(Child.class_id == cls.id, Child.roll_no == body.roll_no)):
        raise HTTPException(409, "roll number already used")
    ch = Child(class_id=cls.id, first_name=body.first_name.strip(), roll_no=body.roll_no,
               consent_on=date.today() if body.consent_source else None, consent_source=body.consent_source)
    db.add(ch)
    db.flush()
    return {"id": ch.id}


@router.post("/classes/{class_id}/children/bulk")
def add_children(class_id: int, children: list[ChildIn], teacher: Teacher = Depends(current_teacher),
                 db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    existing = {c.roll_no for c in db.scalars(select(Child).where(Child.class_id == cls.id))}
    added = 0
    for c in children:
        if c.roll_no in existing:
            continue
        db.add(Child(class_id=cls.id, first_name=c.first_name.strip(), roll_no=c.roll_no,
                     consent_on=date.today() if c.consent_source else None, consent_source=c.consent_source))
        existing.add(c.roll_no)
        added += 1
    db.flush()
    return {"added": added}


@router.patch("/children/{child_id}/consent")
def set_consent(child_id: int, source: str = Form(...), teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    ch = owned_child(child_id, teacher, db)
    ch.consent_on = date.today()
    ch.consent_source = source
    return {"ok": True}


@router.post("/classes/{class_id}/attendance")
def set_attendance(class_id: int, absent_rolls: list[int] = Body(..., embed=True), teacher: Teacher = Depends(current_teacher),
                   db: Session = Depends(get_db), day: date | None = None, merge: bool = False):
    """Replace the day's register (everyone not listed is present). With `merge=true` only the listed
    rolls are marked absent and other children's rows are left alone (voice notes report a few at a time)."""
    cls = owned_class(class_id, teacher, db)
    day = day or ledger.school_today()
    for ch in ledger.class_children(db, cls.id):
        if merge and ch.roll_no not in absent_rolls:
            continue
        row = db.scalar(select(Attendance).where(Attendance.child_id == ch.id, Attendance.day == day))
        present = ch.roll_no not in absent_rolls
        if row:
            row.present = present
        else:
            db.add(Attendance(school_id=cls.school_id, class_id=cls.id, child_id=ch.id, day=day, present=present))
    return {"ok": True, "absent": absent_rolls}


@router.get("/classes/{class_id}/roster")
def roster(class_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    return [{"id": c.id, "roll_no": c.roll_no, "first_name": c.first_name,
             "consented": c.consent_on is not None} for c in ledger.class_children(db, cls.id)]


# ------------------------------------------------------------------ roadmaps
@router.get("/classes/{class_id}/roadmap")
def get_roadmap(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    rm = ledger.current_roadmap(db, cls.id, subject)
    content = get_content()
    if not rm:
        return {"subject": subject, "confirmed": False,
                "items": [{"chapter": i["chapter"], "checkpoint_id": i["checkpoint_id"],
                           "title_hi": content.checkpoints[i["checkpoint_id"]].title_hi,
                           "title_en": content.checkpoints[i["checkpoint_id"]].title_en, "position": i["position"]}
                          for i in content.template_roadmap(subject, cls.grade)]}
    return {"subject": subject, "confirmed": True, "version": rm.version, "source": rm.source,
            "items": [{"chapter": i.chapter, "checkpoint_id": i.checkpoint_id,
                       "title_hi": content.checkpoints[i.checkpoint_id].title_hi
                       if i.checkpoint_id in content.checkpoints else (i.custom_title or i.checkpoint_id),
                       "title_en": content.checkpoints[i.checkpoint_id].title_en
                       if i.checkpoint_id in content.checkpoints else "",
                       "position": i.position} for i in rm.items]}


class RoadmapConfirmIn(BaseModel):
    subject: str
    source: str = "template"
    items: list[dict]  # [{chapter, checkpoint_id?, custom_title?, position}]


@router.post("/classes/{class_id}/roadmap")
def confirm_roadmap(class_id: int, body: RoadmapConfirmIn, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    body.subject = _subject(body.subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    if not 3 <= len(body.items) <= 80:
        raise HTTPException(422, "roadmap needs 3–80 items")
    rows = []
    for i, it in enumerate(body.items):
        cid = it.get("checkpoint_id") or ""
        if cid and cid not in content.checkpoints:
            raise HTTPException(422, f"unknown checkpoint {cid}")
        pos = it.get("position", i)
        if isinstance(pos, float) and pos.is_integer():
            pos = int(pos)
        if not isinstance(pos, int) or isinstance(pos, bool):
            raise HTTPException(422, "position must be an integer")
        rows.append((cid, it, pos))
    prev = ledger.current_roadmap(db, cls.id, body.subject)
    rm = Roadmap(school_id=cls.school_id, class_id=cls.id, subject=body.subject,
                 version=(prev.version + 1) if prev else 1, source=body.source, confirmed_by=teacher.id)
    db.add(rm)
    db.flush()
    for cid, it, pos in rows:
        chapter = it.get("chapter") or (content.checkpoints[cid].chapter if cid else "अन्य")
        db.add(RoadmapItem(roadmap_id=rm.id, position=pos, chapter=str(chapter)[:120],
                           checkpoint_id=cid, custom_title=(it.get("custom_title") or None)))
    return {"id": rm.id, "version": rm.version}


@router.post("/classes/{class_id}/roadmap/draft")
async def draft_roadmap(class_id: int, subject: str = Form(...), image: UploadFile = File(...),
                        teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Index photo → DRAFT chapters matched to graph checkpoints (teacher edits before confirming)."""
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    data = await image.read()
    validate_media(None, data)
    content = get_content()
    lang, _provider = content_lang.for_teacher(db, teacher)
    p = features.draft_roadmap(db, school_id=cls.school_id, image=data,
                               media_type=image_media_type(data), subject=subject, grade=cls.grade, lang=lang)
    items = []
    for ch in p.payload.get("chapters", []):
        # a chapter with no sub-topics is itself a topic: match it to an existing lesson when possible
        match = None if ch["subtopics"] else _match_checkpoint(content, ch["title"], subject, cls.grade)
        items.append({"chapter": ch["title"], "checkpoint_id": match, "custom_title": None if match else ch["title"],
                      "position": len(items)})
        for sub in ch["subtopics"]:
            match = _match_checkpoint(content, sub["text"], subject, cls.grade)
            items.append({"chapter": ch["title"], "checkpoint_id": match,
                          "custom_title": None if match else sub["text"], "position": len(items)})
    return {"status": p.ai_status, "note": p.note, "confidence": p.payload.get("confidence", 0), "items": items,
            "content_lang": lang}


_match_checkpoint = match_checkpoint  # shared with the textbook mapper (services/content.py)


# ------------------------------------------------------------------ captures
def _capture(db: Session, cls, teacher, kind, payload, input_ref=None, input_text=None, ai_status="ready"):
    cap = CaptureSession(school_id=cls.school_id, teacher_id=teacher.id, class_id=cls.id, kind=kind,
                         input_ref=input_ref, input_text=input_text, ai_status=ai_status, payload=payload,
                         status="proposed")
    db.add(cap)
    db.flush()
    return cap


def _cp_labels(content, ids: list[str]) -> list[dict]:
    return [{"id": i, "title_hi": content.checkpoints[i].title_hi,
             "misconceptions": list(content.checkpoints[i].misconceptions)}
            for i in ids if i in content.checkpoints]


@router.post("/classes/{class_id}/captures/note")
async def capture_note(class_id: int, transcript: str | None = Form(None), audio: UploadFile | None = File(None),
                       subject: str = Form("numeracy"), teacher: Teacher = Depends(current_teacher),
                       db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    audio_bytes = await audio.read() if audio else None
    validate_media(audio_bytes, None)
    lang, provider = content_lang.for_teacher(db, teacher)
    text = (transcript or "").strip()
    if not text and audio_bytes:
        try:
            text = content_lang.transcribe(audio_bytes, audio.filename or "note.m4a", lang=lang,
                                           preferred=provider).text
        except Exception:
            text = ""
    if not text:
        raise HTTPException(422, "no transcript (audio not understood — use the tap checklist)")
    content = get_content()
    rm = ledger.current_roadmap(db, cls.id, subject)
    cids = ledger.roadmap_checkpoint_ids(rm) or [c.id for c in content.for_grade(subject, cls.grade)]
    children = ledger.class_children(db, cls.id)
    p = features.extract_note(db, school_id=cls.school_id, transcript=text,
                              roster=[(c.roll_no, c.first_name) for c in children],
                              checkpoint_ids=cids, content=content, subject=subject, lang=lang)
    drafts, unresolved = [], []
    for item in p.payload.get("children", []):
        if item.get("roll") is not None:
            ch = next((c for c in children if c.roll_no == item["roll"]), None)
            r = resolve_names(ch.first_name, children) if ch else None
            if r is None or r.child is None:
                continue
        else:
            r = resolve_names(item["name"], children)
            if r.child is None:
                unresolved.append({"name": item["name"], "reason": r.reason})
                continue
        drafts.append({"child_id": r.child.id, "roll_no": r.child.roll_no, "first_name": r.child.first_name,
                       "name_status": r.reason, **{k: v for k, v in item.items() if k != "name"}})
    payload = {"transcript": text, "drafts": drafts,
               "unresolved": unresolved + p.payload.get("unresolved", []),
               "taught": p.payload.get("taught", [])}
    cap = _capture(db, cls, teacher, "note", payload, input_text=text, ai_status=p.ai_status)
    return {"capture_id": cap.id, "ai_status": p.ai_status, "note": p.note,
            "transcript": text, "drafts": drafts, "unresolved": payload["unresolved"],
            "taught": payload["taught"], "checkpoints": _cp_labels(content, cids),
            "children": [{"id": c.id, "roll_no": c.roll_no, "first_name": c.first_name} for c in children],
            "content_lang": lang}


@router.post("/classes/{class_id}/captures/photo")
async def capture_photo(class_id: int, child_id: int = Form(...), image: UploadFile = File(...),
                        subject: str = Form("numeracy"), teacher: Teacher = Depends(current_teacher),
                        db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    ch = owned_child(child_id, teacher, db)
    if ch.class_id != cls.id:
        raise HTTPException(422, "child not in class")
    data = await image.read()
    validate_media(None, data)
    content = get_content()
    rm = ledger.current_roadmap(db, cls.id, subject)
    cids = ledger.roadmap_checkpoint_ids(rm) or [c.id for c in content.for_grade(subject, cls.grade)]
    lang, _provider = content_lang.for_teacher(db, teacher)
    p = features.analyze_photo(db, school_id=cls.school_id, image=data,
                               media_type=image_media_type(data), checkpoint_ids=cids, content=content, lang=lang)
    page = p.payload.get("page", {})
    if p.ai_status == "ready" and not page.get("legible", True):
        return {"capture_id": None, "ai_status": "retake", "reason": "illegible",
                "message": "फ़ोटो साफ़ नहीं है। पन्ने के ऊपर से लें और रोशनी अच्छी रखें। / "
                           "The photo is not clear. Shoot from directly above the page with good light."}
    questions = [_verify_arithmetic(q) for q in p.payload.get("questions", [])]
    payload = {"child_id": ch.id, "roll_no": ch.roll_no, "questions": questions, "page": page}
    cap = _capture(db, cls, teacher, "photo", payload, input_ref=f"photo:{uuid.uuid4().hex[:12]}",
                   ai_status=p.ai_status)
    return {"capture_id": cap.id, "ai_status": p.ai_status, "note": p.note, "questions": questions,
            "checkpoints": _cp_labels(content, cids), "page": page,
            "child": {"id": ch.id, "first_name": ch.first_name}, "content_lang": lang}


def _verify_arithmetic(q: dict) -> dict:
    """Code recomputes; arithmetic always wins over the model's reading."""
    q = dict(q)
    m = re.match(r"^\s*(\d+)\s*([+\-−×x*÷/])\s*(\d+)\s*=?\s*$", q.get("printed", ""))
    ans = re.search(r"(\d+)", q.get("student_answer", "") or "")
    q["arith_checked"] = False
    if m and ans:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        op = {"−": "-", "x": "*", "X": "*", "×": "*", "÷": "/"}.get(op, op)
        try:
            expected = eval(f"{a}{op}{b}")  # noqa: S307 - operands and operator are digits/fixed symbols only
        except Exception:
            return q
        got = int(ans.group(1))
        correct = abs(got - expected) < 1e-9
        q.update({"expected": str(expected), "arith_checked": True,
                  "verdict": "correct" if correct else "incorrect"})
        if q.get("self_verdict") in ("correct", "incorrect") and (q["self_verdict"] == "correct") != correct:
            q["override_note"] = "arithmetic"
        return q
    q["verdict"] = {"correct": "correct", "incorrect": "incorrect"}.get(q.get("self_verdict"), "unclear")
    return q


@router.post("/classes/{class_id}/captures/voice")
async def capture_voice(class_id: int, body_json: str = Form(...), audio: UploadFile | None = File(None),
                        transcript: str | None = Form(None), teacher: Teacher = Depends(current_teacher),
                        db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    try:
        body = json.loads(body_json)
        child_id, cp_id = int(body["child_id"]), str(body["checkpoint_id"])
        raw_targets = body["target_items"]
        if not isinstance(raw_targets, list):
            raise ValueError("target_items must be a list")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, "body_json must be JSON with child_id, checkpoint_id, target_items[]")
    ch = owned_child(child_id, teacher, db)
    if ch.class_id != cls.id:
        raise HTTPException(422, "child not in class")
    content = get_content()
    cp = _cp(content, cp_id, teacher.school_id)
    if not cp:
        raise HTTPException(422, "unknown checkpoint")
    targets = [str(t) for t in raw_targets][:6]
    audio_bytes = await audio.read() if audio else b""
    validate_media(audio_bytes, None)
    lang, provider = content_lang.for_teacher(db, teacher)
    text = (transcript or "").strip()
    if not text and audio_bytes:
        try:
            text = content_lang.transcribe(audio_bytes, audio.filename or "voice.m4a", lang=lang, keyterms=targets,
                                           preferred=provider).text
        except Exception:
            text = ""
    if not text:
        return {"capture_id": None, "ai_status": "low_audio_quality",
                "message": "आवाज़ ठीक से नहीं सुनाई दी। शांत जगह पर दोबारा रिकॉर्ड करें।"}
    score = score_read(targets, text)
    p = features.interpret_voice(db, school_id=cls.school_id, checkpoint_id=cp.id, score=score.to_dict(),
                                 transcript=text, content=content, lang=lang)
    payload = {"child_id": ch.id, "roll_no": ch.roll_no, "checkpoint_id": cp.id, "targets": targets,
               "transcript": text, "score": score.to_dict(), "proposal": p.payload}
    cap = _capture(db, cls, teacher, "voice", payload, input_text=text, ai_status=p.ai_status)
    return {"capture_id": cap.id, "ai_status": p.ai_status, "score": score.to_dict(), "proposal": p.payload,
            "checkpoint": {"id": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en,
                           "misconceptions": list(cp.misconceptions)},
            "child": {"id": ch.id, "first_name": ch.first_name}, "content_lang": lang}


@router.get("/checkpoints/{checkpoint_id}/targets")
def voice_targets(checkpoint_id: str, teacher: Teacher = Depends(current_teacher)):
    content = get_content()
    cp = _cp(content, checkpoint_id, teacher.school_id)
    if not cp:
        raise HTTPException(404, "unknown checkpoint")
    items = content.items_for(checkpoint_id, limit=6)
    return {"checkpoint_id": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en,
            "targets": [i.get("target") or i.get("correct") or i.get("prompt_hi") for i in items],
            "has_items": bool(items)}


class TapItem(BaseModel):
    child_id: int
    checkpoint_id: str
    result: str
    misconception: str | None = None


class TapIn(BaseModel):
    items: list[TapItem]
    client_uuid: str | None = None


def _replayed(db: Session, teacher: Teacher, kind: str, client_uuid: str | None) -> dict | None:
    """Response stored for an earlier tap/probe request with this client_uuid (offline outbox replays)."""
    if not client_uuid:
        return None
    cap = db.scalar(select(CaptureSession).where(
        CaptureSession.school_id == teacher.school_id, CaptureSession.teacher_id == teacher.id,
        CaptureSession.kind == kind, CaptureSession.input_ref == f"{kind}:{client_uuid[:200]}"))
    return (cap.payload or {}).get("response") if cap else None


def _remember(db: Session, cls, teacher: Teacher, kind: str, client_uuid: str, response: dict) -> CaptureSession:
    """Marker row (kind tap/probe, not counted in /ai_activity) holding the response for replays."""
    return _capture(db, cls, teacher, kind, {"client_uuid": client_uuid, "response": response},
                    input_ref=f"{kind}:{client_uuid[:200]}", ai_status="ready")


@router.post("/classes/{class_id}/captures/tap")
def capture_tap(class_id: int, body: TapIn, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    if (done := _replayed(db, teacher, "tap", body.client_uuid)) is not None:
        return done
    content = get_content()
    ids = {c.id for c in ledger.class_children(db, cls.id)}
    created = 0
    marker = _remember(db, cls, teacher, "tap", body.client_uuid, {}) if body.client_uuid else None
    for it in body.items:
        if it.child_id not in ids:
            raise HTTPException(422, "child not in class")
        if _cp(content, it.checkpoint_id, teacher.school_id) is None or it.result not in RESULT_VALUES:
            raise HTTPException(422, "invalid checkpoint/result")
        misc = it.misconception if it.misconception in content.checkpoints[it.checkpoint_id].misconceptions else None
        db.add(Evidence(school_id=cls.school_id, class_id=cls.id, child_id=it.child_id,
                        checkpoint_id=it.checkpoint_id, result=it.result, source="teacher_tap",
                        confidence=1.0, misconception=misc, status="confirmed", created_by=teacher.id,
                        session_id=marker.id if marker else None))
        created += 1
    if marker:
        marker.status = "confirmed"
        marker.payload = {**marker.payload, "response": {"committed": created}}
    db.flush()
    return {"committed": created}


@router.post("/classes/{class_id}/captures/probe")
def capture_probe(class_id: int, child_id: int, checkpoint_id: str, passed: int, total: int,
                  client_uuid: str | None = None,
                  teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    if (done := _replayed(db, teacher, "probe", client_uuid)) is not None:
        return done
    ch = owned_child(child_id, teacher, db)
    if ch.class_id != cls.id:
        raise HTTPException(422, "child not in this class")
    content = get_content()
    if _cp(content, checkpoint_id, teacher.school_id) is None:
        raise HTTPException(422, "unknown checkpoint")
    ratio = passed / max(1, total)
    result = "correct" if ratio >= 0.75 else ("partial" if ratio >= 0.4 else "incorrect")
    marker = _remember(db, cls, teacher, "probe", client_uuid, {"result": result}) if client_uuid else None
    if marker:
        marker.status = "confirmed"
    db.add(Evidence(school_id=cls.school_id, class_id=cls.id, child_id=ch.id, checkpoint_id=checkpoint_id,
                    result=result, score=ratio, source="guided_probe", confidence=1.0,
                    status="confirmed", created_by=teacher.id, session_id=marker.id if marker else None))
    return {"result": result}


@router.get("/checkpoints/{checkpoint_id}/probe")
def get_probe(checkpoint_id: str, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    content = get_content()
    cp = _cp(content, checkpoint_id, teacher.school_id)
    if not cp:
        raise HTTPException(404, "unknown checkpoint")
    lang, _provider = content_lang.for_teacher(db, teacher)
    p = content_lang.probe(content.probes.get(checkpoint_id), checkpoint_id, lang)
    out = {"checkpoint": {"id": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en}, "probe": p,
           "suggestion": p["title_hi"] if p else "प्रश्न पूछकर जाँचें", "content_lang": lang}
    if lang != content_lang.SOURCE_LANG:
        out["machine_translated"] = bool(p and p.get("machine_translated"))
        if not p:  # the canned hint
            [out["suggestion"]], out["machine_translated"] = content_lang.translate(
                db, [out["suggestion"]], lang, teacher.school_id)
    return out


@router.get("/captures/{capture_id}")
def get_capture(capture_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cap = db.get(CaptureSession, capture_id)
    if not cap or cap.school_id != teacher.school_id:
        raise HTTPException(404, "capture not found")
    return {"id": cap.id, "kind": cap.kind, "ai_status": cap.ai_status, "status": cap.status,
            "payload": cap.payload, "input_text": cap.input_text}


class AcceptedItem(BaseModel):
    child_id: int
    checkpoint_id: str
    result: str
    misconception: str | None = None
    confidence: float = 0.8  # an explicit null is a 422, not a crash
    score: float | None = None
    quote: str | None = None


class ConfirmIn(BaseModel):
    accepted: list[AcceptedItem]
    reject_all: bool = False
    skipped: int = Field(0, ge=0)  # proposals the teacher swiped away
    edited: int = Field(0, ge=0)  # proposals the teacher changed before accepting


@router.post("/captures/{capture_id}/confirm")
def confirm_capture(capture_id: int, body: ConfirmIn, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    cap = db.get(CaptureSession, capture_id)
    if not cap or cap.school_id != teacher.school_id:
        raise HTTPException(404, "capture not found")
    if cap.status != "proposed":
        raise HTTPException(409, "capture already handled")
    content = get_content()
    valid_children = {c.id for c in ledger.class_children(db, cap.class_id)}
    source = {"note": "teacher_note", "photo": "photo_work", "voice": "class_voice"}.get(cap.kind, "teacher_tap")
    committed = 0
    if not body.reject_all:
        for a in body.accepted:
            if a.child_id not in valid_children or _cp(content, a.checkpoint_id, teacher.school_id) is None \
                    or a.result not in RESULT_VALUES:
                raise HTTPException(422, "invalid evidence item")
            misc = a.misconception
            db.add(Evidence(school_id=cap.school_id, class_id=cap.class_id, child_id=a.child_id,
                            checkpoint_id=a.checkpoint_id, result=a.result, score=a.score, source=source,
                            confidence=max(0.0, min(1.0, a.confidence)),
                            misconception=misc if misc in content.checkpoints[a.checkpoint_id].misconceptions else None,
                            session_id=cap.id, quote=(a.quote[:300] if a.quote else None), status="confirmed",
                            created_by=teacher.id))
            committed += 1
    cap.status = "discarded" if body.reject_all else "confirmed"
    # guardrail counters; re-assign so SQLAlchemy sees the JSON change
    cap.payload = {**(cap.payload or {}), "skipped": body.skipped, "edited": body.edited}
    return {"committed": committed, "status": cap.status}


@router.get("/ai_activity")
def ai_activity(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Live guardrail counter (settings screen + submission evidence)."""
    rows = list(db.scalars(select(CaptureSession).where(CaptureSession.school_id == teacher.school_id,
                                                        CaptureSession.kind.not_in(("tap", "probe")))))
    proposed = sum(len(c.payload.get("drafts", [])) + len(c.payload.get("questions", []))
                   + (1 if c.kind == "voice" else 0) for c in rows)
    calls = list(db.scalars(select(AiCall).where(AiCall.school_id == teacher.school_id)))
    now = _now().replace(tzinfo=None)  # columns hold naive UTC
    today, week_ago = datetime.combine(now.date(), datetime.min.time()), now - timedelta(days=7)
    skipped = sum(int((c.payload or {}).get("skipped") or 0) for c in rows)
    checks_7d = db.scalar(select(func.count(Evidence.id)).where(
        Evidence.school_id == teacher.school_id, Evidence.status == "confirmed", Evidence.at >= week_ago,
        Evidence.source.in_(("teacher_tap", "teacher_note", "class_voice", "photo_work", "guided_probe")))) or 0
    plans_7d = db.scalar(select(func.count(Plan.id)).where(
        Plan.school_id == teacher.school_id, Plan.created_at >= week_ago)) or 0
    return {"captures": len(rows), "proposals": proposed,
            "confirmed": sum(1 for c in rows if c.status == "confirmed"),
            "rejected": sum(1 for c in rows if c.status == "discarded") + skipped,
            "edited": sum(int((c.payload or {}).get("edited") or 0) for c in rows),
            "skipped": skipped,
            "degraded": sum(1 for c in rows if c.ai_status != "ready"),
            "ai_calls": len(calls), "cost_inr": round(sum(c.cost_inr for c in calls), 2),
            "cost_inr_today": round(sum(c.cost_inr for c in calls if c.at and c.at.replace(tzinfo=None) >= today), 2),
            "checks_7d": checks_7d, "plans_7d": plans_7d,
            "validation_failures": sum(1 for c in calls if c.validation_status != "ok")}


# ------------------------------------------------------------------ plans / board / profiles
@router.post("/classes/{class_id}/plans")
def make_plan(class_id: int, subject: str, for_date: date | None = None, force: bool = False,
              teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    lang, _provider = content_lang.for_teacher(db, teacher)
    plan = ledger.todays_plan(db, cls, subject, for_date or ledger.school_today(), content, force=force, lang=lang)
    payload = ledger.localize_plan(ledger.upgrade_plan_payload(plan.payload, ledger.class_children(db, cls.id),
                                                               content), content)
    return {"id": plan.id, "subject": plan.subject, "for_date": plan.for_date.isoformat(),
            "generated_by": plan.generated_by, **payload}


@router.get("/classes/{class_id}/plans/latest")
def latest_plan(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    plan = db.scalar(select(Plan).where(Plan.class_id == cls.id, Plan.subject == subject)
                     .order_by(Plan.for_date.desc()).limit(1))
    if not plan:
        return {"exists": False}
    content = get_content()
    payload = ledger.localize_plan(ledger.upgrade_plan_payload(plan.payload, ledger.class_children(db, cls.id),
                                                               content), content)
    return {"exists": True, "id": plan.id, "for_date": plan.for_date.isoformat(),
            "generated_by": plan.generated_by, **payload}


@router.post("/plans/{plan_id}/groups/{group_key}/done")
def plan_group_done(plan_id: int, group_key: str, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if not plan or plan.school_id != teacher.school_id:
        raise HTTPException(404, "plan not found")
    # one log per (plan, group): the offline outbox may replay this after a lost response
    if not db.scalar(select(InterventionLog.id).where(InterventionLog.plan_id == plan.id,
                                                      InterventionLog.group_key == group_key).limit(1)):
        db.add(InterventionLog(school_id=plan.school_id, plan_id=plan.id, group_key=group_key))
    session = followups.record_done(db, plan, group_key, teacher.id)  # None for assess_first
    return {"ok": True, "session_id": session.id if session else None}


@router.get("/classes/{class_id}/board")
def class_board(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    grouping, _st, children, _rm = ledger.build_groups(db, cls, subject)
    by_id = {c.id: c for c in children}
    content = get_content()
    absent = sorted(cid for cid, present in ledger.attendance_today(db, cls.id, ledger.school_today()).items()
                    if not present and cid in by_id)

    def pub(ids):
        return [{"id": m, "first_name": by_id[m].first_name, "roll_no": by_id[m].roll_no}
                for m in ids if m in by_id]

    return {"class": {"id": cls.id, "label": cls.label},
            "groups": [{"key": g.key, "title_hi": g.title_hi, "title_en": g.title_en,
                        "chapter": g.chapter, "status": g.status, "nipun_ref": ledger.nipun_ref(content, g.checkpoint_id),
                        "reason": g.reason, "members": pub(g.members)} for g in grouping.groups],
            "on_track": pub(grouping.on_track), "unassessed": pub(grouping.unassessed), "absent": absent}


def _group_ref(content, key: str | None) -> dict | None:
    cp = content.checkpoints.get(key or "")
    if not cp:
        return None
    return {"key": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en}


@router.get("/classes/{class_id}/moved")
def class_moved(class_id: int, subject: str, hours: int = Query(24, ge=1, le=24 * 90),
                teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Children whose group differs from `hours` ago (same grouping rules as the board)."""
    subject = _subject(subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    since = _now().replace(tzinfo=None) - timedelta(hours=hours)
    then, then_rank, children = ledger.group_snapshot(db, cls, subject, since)
    now, now_rank, _ = ledger.group_snapshot(db, cls, subject, None)
    moves = []
    seen_before = {cid for cid, st in ledger.child_statuses(db, [c.id for c in children], since, before=since).items()
                   if st}
    for c in children:
        before, after = then.get(c.id), now.get(c.id)
        if before == after:
            continue
        if c.id not in seen_before:
            continue  # first assessment is new information, not a move
        if before is None:
            direction = "slipped"
        elif after is None or now_rank.get(c.id, 0) > then_rank.get(c.id, 0):
            direction = "improved"
        else:
            direction = "changed"
        moves.append({"child_id": c.id, "first_name": c.first_name, "roll_no": c.roll_no,
                      "direction": direction, "from": _group_ref(content, before), "to": _group_ref(content, after)})
    return {"since": since.replace(tzinfo=timezone.utc).isoformat(), "moves": moves}


@router.get("/classes/{class_id}/attendance")
def get_attendance(class_id: int, day: date | None = None, teacher: Teacher = Depends(current_teacher),
                   db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    day = day or ledger.school_today()
    children = {c.id: c for c in ledger.class_children(db, cls.id)}
    absent = sorted(children[cid].roll_no for cid, present in ledger.attendance_today(db, cls.id, day).items()
                    if not present and cid in children)
    return {"day": day.isoformat(), "absent_rolls": absent, "present": len(children) - len(absent)}


@router.get("/children/{child_id}/timeline")
def child_timeline(child_id: int, subject: str, weeks: int = Query(6, ge=1, le=26),
                   teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Roadmap topics by status at each of the last `weeks` week-ends (the last point is now)."""
    subject = _subject(subject, db, teacher)
    ch = owned_child(child_id, teacher, db)
    cls = db.get(Classroom, ch.class_id)
    cps = ledger.class_roadmap_cps(db, cls, subject)
    return {"points": ledger.status_timeline(db, ch, cps, _now(), weeks)}


@router.get("/children/{child_id}/profile")
def profile(child_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
            db: Session = Depends(get_db)):
    subject = _subject(subject, db, teacher)
    ch = owned_child(child_id, teacher, db)
    rm = ledger.current_roadmap(db, ch.class_id, subject)
    return ledger.child_profile(db, ch, rm, get_content(), subject=subject,
                                grade=db.get(Classroom, ch.class_id).grade)


@router.get("/children/{child_id}/history")
def child_history(child_id: int, limit: int = 40, subject: str | None = None,
                  teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    ch = owned_child(child_id, teacher, db)
    q = select(Evidence).where(Evidence.child_id == ch.id, Evidence.status == "confirmed")
    if subject:
        subject = _subject(subject, db, teacher)
        cps = get_content().checkpoints
        q = q.where(Evidence.checkpoint_id.in_([c for c, cp in cps.items() if cp.subject == subject]))
    rows = db.scalars(q.order_by(Evidence.at.desc()).limit(limit))
    return [{"id": e.id, "checkpoint_id": e.checkpoint_id, "result": e.result, "source": e.source,
             "misconception": e.misconception, "at": e.at.isoformat(), "quote": e.quote} for e in rows]


@router.get("/children/{child_id}/export")
def export_child(child_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    ch = owned_child(child_id, teacher, db)
    evs = db.scalars(select(Evidence).where(Evidence.child_id == ch.id)).all()
    return {"child": {"first_name": ch.first_name, "roll_no": ch.roll_no},
            "evidence": [{"checkpoint_id": e.checkpoint_id, "result": e.result, "source": e.source,
                          "status": e.status, "at": e.at.isoformat()} for e in evs]}


@router.delete("/children/{child_id}/data")
def delete_child_data(child_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    ch = owned_child(child_id, teacher, db)
    db.execute(delete(Evidence).where(Evidence.child_id == ch.id))
    db.execute(delete(Attendance).where(Attendance.child_id == ch.id))
    db.execute(delete(LevelCheck).where(LevelCheck.child_id == ch.id))
    return {"deleted": True}


@router.delete("/classes/{class_id}/data")
def delete_class_data(class_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    ids = [c.id for c in ledger.class_children(db, cls.id)]
    if ids:
        db.execute(delete(Evidence).where(Evidence.child_id.in_(ids)))
        db.execute(delete(Attendance).where(Attendance.class_id == cls.id))
    db.execute(delete(LevelCheck).where(LevelCheck.class_id == cls.id))
    db.execute(delete(CaptureSession).where(CaptureSession.class_id == cls.id))
    plans = select(Plan.id).where(Plan.class_id == cls.id)
    db.execute(delete(GroupSession).where(GroupSession.plan_id.in_(plans)))
    db.execute(delete(InterventionLog).where(InterventionLog.plan_id.in_(plans)))  # Done logs block the plan delete
    db.execute(delete(Plan).where(Plan.class_id == cls.id))
    return {"deleted": True}


@router.get("/content/checkpoints")
def list_checkpoints(subject: str | None = None, grade: int | None = None,
                     teacher: Teacher = Depends(current_teacher)):
    content = get_content()
    out = []
    for c in sorted(content.checkpoints.values(), key=lambda c: (c.subject, c.grade, c.chapter)):
        if subject and c.subject != subject:
            continue
        if grade and c.grade > grade:
            continue
        if c.id in content.custom_ids and not c.id.startswith(f"C{teacher.school_id}-"):
            continue  # another school's custom topic
        out.append({"id": c.id, "subject": c.subject, "grade": c.grade, "chapter": c.chapter,
                    "title_hi": c.title_hi, "title_en": c.title_en, "misconceptions": list(c.misconceptions),
                    "nipun_ref": c.nipun_ref, "assess_via": list(c.assess_via)})
    return out


def _content_reader(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A teacher or a parent (both apps show lesson titles): (school_id, content language)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing token")
    try:
        payload = decode_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(401, "invalid token")
    kind, sub = payload.get("kind"), int(payload.get("sub") or 0)
    if kind == "teacher" and (t := db.get(Teacher, sub)):
        return t.school_id, prefs.content_lang_for(db, teacher=t)
    if kind == "parent" and (pa := db.get(ParentAccount, sub)):
        return pa.school_id, prefs.content_lang_for(db, parent=pa)
    raise HTTPException(401, "user not found")


@router.get("/content/titles")
def content_titles(lang: str | None = None, who=Depends(_content_reader)):
    """Lesson titles in a content language: {lang, titles: {checkpoint_id: title}, machine_translated}.
    Without `lang`, the caller's own content language."""
    from app.i18n.languages import LANGUAGES
    school_id, own = who
    lang = (lang or own).strip()
    if lang not in LANGUAGES:
        raise HTTPException(422, f"unknown language {lang}")
    return content_lang.titles(get_content(), lang, school_id)


@router.get("/content/status")
def content_status():
    content = get_content()
    return {"checkpoints": len(content.checkpoints), "activities": len(content.activities),
            "activities_reviewed": sum(1 for a in content.activities.values() if a.get("reviewed")),
            "practice_items": len(content.practice_items), "probes": len(content.probes)}
