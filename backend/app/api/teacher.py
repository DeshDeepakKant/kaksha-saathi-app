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
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai import features
from app.ai.llm import budget_remaining
from app.api.deps import current_teacher, owned_child, owned_class, validate_media
from app.core.security import make_token, verify_pin
from app.db import get_db
from app.models.tables import (
    AiCall, Attendance, CaptureSession, Child, Classroom, Evidence, InterventionLog, Plan, Roadmap,
    RoadmapItem, School, Teacher,
)
from app.services import ledger
from app.services.content import get_content
from app.services.mastery import RESULT_VALUES
from app.services.resolver import resolve_names
from app.speech import get_asr, has_asr
from app.speech.scorer import score_read

router = APIRouter(prefix="/v1")


def _now() -> datetime:
    return datetime.now(timezone.utc)


SUBJECT_ALIASES = {"math": "numeracy", "maths": "numeracy", "ganit": "numeracy",
                   "hindi": "literacy", "reading": "literacy"}


def _subject(subject: str) -> str:
    """Normalise a subject; an unknown one is a 422, not an empty board."""
    s = (subject or "").strip().lower()
    s = SUBJECT_ALIASES.get(s, s)
    if s not in get_content().subjects:
        raise HTTPException(422, f"unknown subject '{subject}' (use numeracy or literacy)")
    return s


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
                   db: Session = Depends(get_db), day: date | None = None):
    cls = owned_class(class_id, teacher, db)
    day = day or date.today()
    for ch in ledger.class_children(db, cls.id):
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
    subject = _subject(subject)
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
    body.subject = _subject(body.subject)
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    if not 3 <= len(body.items) <= 80:
        raise HTTPException(422, "roadmap needs 3–80 items")
    prev = ledger.current_roadmap(db, cls.id, body.subject)
    rm = Roadmap(school_id=cls.school_id, class_id=cls.id, subject=body.subject,
                 version=(prev.version + 1) if prev else 1, source=body.source, confirmed_by=teacher.id)
    db.add(rm)
    db.flush()
    for i, it in enumerate(body.items):
        cid = it.get("checkpoint_id") or ""
        if cid and cid not in content.checkpoints:
            raise HTTPException(422, f"unknown checkpoint {cid}")
        chapter = it.get("chapter") or (content.checkpoints[cid].chapter if cid else "अन्य")
        db.add(RoadmapItem(roadmap_id=rm.id, position=int(it.get("position", i)), chapter=str(chapter)[:120],
                           checkpoint_id=cid, custom_title=(it.get("custom_title") or None)))
    return {"id": rm.id, "version": rm.version}


@router.post("/classes/{class_id}/roadmap/draft")
async def draft_roadmap(class_id: int, subject: str = Form(...), image: UploadFile = File(...),
                        teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Index photo → DRAFT chapters matched to graph checkpoints (teacher edits before confirming)."""
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    data = await image.read()
    validate_media(None, data)
    content = get_content()
    p = features.draft_roadmap(db, school_id=cls.school_id, image=data,
                               media_type=image.content_type or "image/jpeg", subject=subject, grade=cls.grade)
    items = []
    for ch in p.payload.get("chapters", []):
        items.append({"chapter": ch["title"], "checkpoint_id": None, "custom_title": ch["title"],
                      "position": len(items)})
        for sub in ch["subtopics"]:
            match = _match_checkpoint(content, sub["text"], subject, cls.grade)
            items.append({"chapter": ch["title"], "checkpoint_id": match,
                          "custom_title": None if match else sub["text"], "position": len(items)})
    return {"status": p.ai_status, "note": p.note, "confidence": p.payload.get("confidence", 0), "items": items}


def _match_checkpoint(content, text: str, subject: str, grade: int) -> str | None:
    from rapidfuzz import fuzz
    best, best_score = None, 0
    for c in content.for_grade(subject, grade):
        s = max(fuzz.partial_ratio(text, c.title_hi), fuzz.partial_ratio(text, c.title_en))
        if s > best_score:
            best, best_score = c.id, s
    return best if best_score >= 70 else None


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
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    audio_bytes = await audio.read() if audio else None
    validate_media(audio_bytes, None)
    text = (transcript or "").strip()
    if not text and audio_bytes:
        try:
            text = get_asr().transcribe(audio_bytes, audio.filename or "note.m4a").text
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
                              checkpoint_ids=cids, content=content, subject=subject)
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
            "children": [{"id": c.id, "roll_no": c.roll_no, "first_name": c.first_name} for c in children]}


@router.post("/classes/{class_id}/captures/photo")
async def capture_photo(class_id: int, child_id: int = Form(...), image: UploadFile = File(...),
                        subject: str = Form("numeracy"), teacher: Teacher = Depends(current_teacher),
                        db: Session = Depends(get_db)):
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    ch = owned_child(child_id, teacher, db)
    if ch.class_id != cls.id:
        raise HTTPException(422, "child not in class")
    data = await image.read()
    validate_media(None, data)
    content = get_content()
    rm = ledger.current_roadmap(db, cls.id, subject)
    cids = ledger.roadmap_checkpoint_ids(rm) or [c.id for c in content.for_grade(subject, cls.grade)]
    p = features.analyze_photo(db, school_id=cls.school_id, image=data,
                               media_type=image.content_type or "image/jpeg", checkpoint_ids=cids, content=content)
    page = p.payload.get("page", {})
    if p.ai_status == "ready" and not page.get("legible", True):
        return {"capture_id": None, "ai_status": "retake", "reason": "illegible",
                "message": "फ़ोटो साफ़ नहीं है। पन्ने के ऊपर से लें और रोशनी अच्छी रखें।"}
    questions = [_verify_arithmetic(q) for q in p.payload.get("questions", [])]
    payload = {"child_id": ch.id, "roll_no": ch.roll_no, "questions": questions, "page": page}
    cap = _capture(db, cls, teacher, "photo", payload, input_ref=f"photo:{uuid.uuid4().hex[:12]}",
                   ai_status=p.ai_status)
    return {"capture_id": cap.id, "ai_status": p.ai_status, "note": p.note, "questions": questions,
            "checkpoints": _cp_labels(content, cids), "page": page,
            "child": {"id": ch.id, "first_name": ch.first_name}}


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
    body = json.loads(body_json)
    ch = owned_child(int(body["child_id"]), teacher, db)
    content = get_content()
    cp = content.checkpoints.get(body["checkpoint_id"])
    if not cp:
        raise HTTPException(422, "unknown checkpoint")
    targets = [str(t) for t in body["target_items"]][:6]
    audio_bytes = await audio.read() if audio else b""
    validate_media(audio_bytes, None)
    text = (transcript or "").strip()
    if not text and audio_bytes:
        text = get_asr().transcribe(audio_bytes, audio.filename or "voice.m4a", keyterms=targets).text
    if not text:
        return {"capture_id": None, "ai_status": "low_audio_quality",
                "message": "आवाज़ ठीक से नहीं सुनाई दी। शांत जगह पर दोबारा रिकॉर्ड करें।"}
    score = score_read(targets, text)
    p = features.interpret_voice(db, school_id=cls.school_id, checkpoint_id=cp.id, score=score.to_dict(),
                                 transcript=text, content=content)
    payload = {"child_id": ch.id, "roll_no": ch.roll_no, "checkpoint_id": cp.id, "targets": targets,
               "transcript": text, "score": score.to_dict(), "proposal": p.payload}
    cap = _capture(db, cls, teacher, "voice", payload, input_text=text, ai_status=p.ai_status)
    return {"capture_id": cap.id, "ai_status": p.ai_status, "score": score.to_dict(), "proposal": p.payload,
            "checkpoint": {"id": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en,
                           "misconceptions": list(cp.misconceptions)},
            "child": {"id": ch.id, "first_name": ch.first_name}}


@router.get("/checkpoints/{checkpoint_id}/targets")
def voice_targets(checkpoint_id: str, teacher: Teacher = Depends(current_teacher)):
    content = get_content()
    cp = content.checkpoints.get(checkpoint_id)
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


@router.post("/classes/{class_id}/captures/tap")
def capture_tap(class_id: int, body: TapIn, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    ids = {c.id for c in ledger.class_children(db, cls.id)}
    created = 0
    for it in body.items:
        if it.child_id not in ids:
            raise HTTPException(422, "child not in class")
        if it.checkpoint_id not in content.checkpoints or it.result not in RESULT_VALUES:
            raise HTTPException(422, "invalid checkpoint/result")
        misc = it.misconception if it.misconception in content.checkpoints[it.checkpoint_id].misconceptions else None
        db.add(Evidence(school_id=cls.school_id, class_id=cls.id, child_id=it.child_id,
                        checkpoint_id=it.checkpoint_id, result=it.result, source="teacher_tap",
                        confidence=1.0, misconception=misc, status="confirmed", created_by=teacher.id))
        created += 1
    db.flush()
    return {"committed": created}


@router.post("/classes/{class_id}/captures/probe")
def capture_probe(class_id: int, child_id: int, checkpoint_id: str, passed: int, total: int,
                  teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    ch = owned_child(child_id, teacher, db)
    if ch.class_id != cls.id:
        raise HTTPException(422, "child not in this class")
    content = get_content()
    if content.checkpoints.get(checkpoint_id) is None:
        raise HTTPException(422, "unknown checkpoint")
    ratio = passed / max(1, total)
    result = "correct" if ratio >= 0.75 else ("partial" if ratio >= 0.4 else "incorrect")
    db.add(Evidence(school_id=cls.school_id, class_id=cls.id, child_id=ch.id, checkpoint_id=checkpoint_id,
                    result=result, score=ratio, source="guided_probe", confidence=1.0,
                    status="confirmed", created_by=teacher.id))
    return {"result": result}


@router.get("/checkpoints/{checkpoint_id}/probe")
def get_probe(checkpoint_id: str, teacher: Teacher = Depends(current_teacher)):
    content = get_content()
    cp = content.checkpoints.get(checkpoint_id)
    if not cp:
        raise HTTPException(404, "unknown checkpoint")
    p = content.probes.get(checkpoint_id)
    return {"checkpoint": {"id": cp.id, "title_hi": cp.title_hi, "title_en": cp.title_en}, "probe": p,
            "suggestion": p["title_hi"] if p else "प्रश्न पूछकर जाँचें"}


@router.get("/captures/{capture_id}")
def get_capture(capture_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cap = db.get(CaptureSession, capture_id)
    if not cap or cap.school_id != teacher.school_id:
        raise HTTPException(404, "capture not found")
    return {"id": cap.id, "kind": cap.kind, "ai_status": cap.ai_status, "status": cap.status,
            "payload": cap.payload, "input_text": cap.input_text}


class ConfirmIn(BaseModel):
    accepted: list[dict]  # [{child_id, checkpoint_id, result, misconception?, confidence?, quote?}]
    reject_all: bool = False


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
            cid, cp_id, res = int(a["child_id"]), a["checkpoint_id"], a["result"]
            if cid not in valid_children or cp_id not in content.checkpoints or res not in RESULT_VALUES:
                raise HTTPException(422, "invalid evidence item")
            misc = a.get("misconception")
            db.add(Evidence(school_id=cap.school_id, class_id=cap.class_id, child_id=cid, checkpoint_id=cp_id,
                            result=res, score=a.get("score"), source=source,
                            confidence=float(a.get("confidence", 0.8)),
                            misconception=misc if misc in content.checkpoints[cp_id].misconceptions else None,
                            session_id=cap.id, quote=(a.get("quote") or None), status="confirmed",
                            created_by=teacher.id))
            committed += 1
    cap.status = "discarded" if body.reject_all else "confirmed"
    return {"committed": committed, "status": cap.status}


@router.get("/ai_activity")
def ai_activity(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    """Live guardrail counter (settings screen + submission evidence)."""
    rows = list(db.scalars(select(CaptureSession).where(CaptureSession.school_id == teacher.school_id)))
    proposed = sum(len(c.payload.get("drafts", [])) + len(c.payload.get("questions", []))
                   + (1 if c.kind == "voice" else 0) for c in rows)
    calls = list(db.scalars(select(AiCall).where(AiCall.school_id == teacher.school_id)))
    return {"captures": len(rows), "proposals": proposed,
            "confirmed": sum(1 for c in rows if c.status == "confirmed"),
            "rejected": sum(1 for c in rows if c.status == "discarded"),
            "degraded": sum(1 for c in rows if c.ai_status != "ready"),
            "ai_calls": len(calls), "cost_inr": round(sum(c.cost_inr for c in calls), 2),
            "validation_failures": sum(1 for c in calls if c.validation_status != "ok")}


# ------------------------------------------------------------------ plans / board / profiles
@router.post("/classes/{class_id}/plans")
def make_plan(class_id: int, subject: str, for_date: date | None = None, force: bool = False,
              teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    plan = ledger.todays_plan(db, cls, subject, for_date or _now().date(), get_content(), force=force)
    return {"id": plan.id, "subject": plan.subject, "for_date": plan.for_date.isoformat(),
            "generated_by": plan.generated_by, **plan.payload}


@router.get("/classes/{class_id}/plans/latest")
def latest_plan(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    plan = db.scalar(select(Plan).where(Plan.class_id == cls.id, Plan.subject == subject)
                     .order_by(Plan.for_date.desc()).limit(1))
    if not plan:
        return {"exists": False}
    return {"exists": True, "id": plan.id, "for_date": plan.for_date.isoformat(),
            "generated_by": plan.generated_by, **plan.payload}


@router.post("/plans/{plan_id}/groups/{group_key}/done")
def plan_group_done(plan_id: int, group_key: str, teacher: Teacher = Depends(current_teacher),
                    db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if not plan or plan.school_id != teacher.school_id:
        raise HTTPException(404, "plan not found")
    db.add(InterventionLog(school_id=plan.school_id, plan_id=plan.id, group_key=group_key))
    return {"ok": True}


@router.get("/classes/{class_id}/board")
def class_board(class_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
                db: Session = Depends(get_db)):
    subject = _subject(subject)
    cls = owned_class(class_id, teacher, db)
    grouping, _st, children, _rm = ledger.build_groups(db, cls, subject)
    by_id = {c.id: c for c in children}

    def pub(ids):
        return [{"id": m, "first_name": by_id[m].first_name, "roll_no": by_id[m].roll_no}
                for m in ids if m in by_id]

    return {"class": {"id": cls.id, "label": cls.label},
            "groups": [{"key": g.key, "title_hi": g.title_hi, "title_en": g.title_en,
                        "chapter": g.chapter, "status": g.status,
                        "reason": g.reason, "members": pub(g.members)} for g in grouping.groups],
            "on_track": pub(grouping.on_track), "unassessed": pub(grouping.unassessed)}


@router.get("/children/{child_id}/profile")
def profile(child_id: int, subject: str, teacher: Teacher = Depends(current_teacher),
            db: Session = Depends(get_db)):
    subject = _subject(subject)
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
        subject = _subject(subject)
        cps = get_content().checkpoints
        q = q.where(Evidence.checkpoint_id.in_([c for c, cp in cps.items() if cp.subject == subject]))
    rows = db.scalars(q.order_by(Evidence.at.desc()).limit(limit))
    return [{"checkpoint_id": e.checkpoint_id, "result": e.result, "source": e.source,
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
    return {"deleted": True}


@router.delete("/classes/{class_id}/data")
def delete_class_data(class_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    ids = [c.id for c in ledger.class_children(db, cls.id)]
    if ids:
        db.execute(delete(Evidence).where(Evidence.child_id.in_(ids)))
        db.execute(delete(Attendance).where(Attendance.class_id == cls.id))
    db.execute(delete(CaptureSession).where(CaptureSession.class_id == cls.id))
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
        out.append({"id": c.id, "subject": c.subject, "grade": c.grade, "chapter": c.chapter,
                    "title_hi": c.title_hi, "title_en": c.title_en, "misconceptions": list(c.misconceptions),
                    "assess_via": list(c.assess_via)})
    return out


@router.get("/content/status")
def content_status():
    content = get_content()
    return {"checkpoints": len(content.checkpoints), "activities": len(content.activities),
            "activities_reviewed": sum(1 for a in content.activities.values() if a.get("reviewed")),
            "practice_items": len(content.practice_items), "probes": len(content.probes)}
