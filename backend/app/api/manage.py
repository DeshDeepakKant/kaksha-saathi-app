"""Correcting mistakes (feature 7): undo/restore an evidence row, edit or remove a student, rename a
custom topic, reorder a syllabus. Teacher JWT, every row scoped to the teacher's school.

Contract: docs/teacher_loop_contract.md ("Backend-Manage"). Mastery only counts confirmed evidence,
so undo/restore change a child's statuses with no other bookkeeping.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_teacher, owned_child, owned_class
from app.api.teacher import _subject
from app.db import get_db
from app.models.tables import Child, CustomCheckpoint, Evidence, Teacher
from app.services import coverage
from app.services.content import get_content

router = APIRouter(prefix="/v1")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


# ------------------------------------------------------------------ evidence undo / restore
def _owned_evidence(evidence_id: int, teacher: Teacher, db: Session) -> Evidence:
    ev = db.get(Evidence, evidence_id)
    if ev is None or ev.school_id != teacher.school_id:
        raise HTTPException(404, "evidence not found")
    return ev


def _move(evidence_id: int, teacher: Teacher, db: Session, frm: str, to: str) -> dict:
    ev = _owned_evidence(evidence_id, teacher, db)
    if ev.status != frm:
        raise HTTPException(409, f"only {frm} evidence can be set to {to} (this one is {ev.status})")
    ev.status = to
    db.flush()
    return {"id": ev.id, "status": ev.status}


@router.post("/evidence/{evidence_id}/undo")
def undo_evidence(evidence_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    return _move(evidence_id, teacher, db, "confirmed", "rejected")


@router.post("/evidence/{evidence_id}/restore")
def restore_evidence(evidence_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    return _move(evidence_id, teacher, db, "rejected", "confirmed")


# ------------------------------------------------------------------ students
class ChildEditIn(BaseModel):
    first_name: str | None = Field(default=None, max_length=60)
    roll_no: int | None = None
    class_id: int | None = None
    active: bool | None = None


def _child_out(ch: Child) -> dict:
    return {"id": ch.id, "first_name": ch.first_name, "roll_no": ch.roll_no, "class_id": ch.class_id,
            "active": ch.active}


@router.post("/children/{child_id}/edit")
def edit_child(child_id: int, body: ChildEditIn, teacher: Teacher = Depends(current_teacher),
               db: Session = Depends(get_db)):
    ch = owned_child(child_id, teacher, db)
    name = None
    if body.first_name is not None:
        name = _clean(body.first_name)
        if not name:
            raise HTTPException(422, "name can't be empty")
    target = owned_class(body.class_id, teacher, db).id if body.class_id is not None else ch.class_id
    roll = body.roll_no if body.roll_no is not None else ch.roll_no
    if (target, roll) != (ch.class_id, ch.roll_no) and db.scalar(
            select(Child.id).where(Child.class_id == target, Child.roll_no == roll, Child.id != ch.id)):
        raise HTTPException(409, "roll number already used in that class")
    if name is not None:
        ch.first_name = name
    ch.class_id, ch.roll_no = target, roll
    if body.active is not None:
        ch.active = body.active
    db.flush()
    return _child_out(ch)


@router.get("/classes/{class_id}/children/inactive")
def inactive_children(class_id: int, teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    cls = owned_class(class_id, teacher, db)
    rows = db.scalars(select(Child).where(Child.class_id == cls.id, Child.active.is_(False))
                      .order_by(Child.roll_no))
    return [{"id": c.id, "first_name": c.first_name, "roll_no": c.roll_no} for c in rows]


# ------------------------------------------------------------------ syllabus topics
class TopicRenameIn(BaseModel):
    subject: str
    title_en: str | None = Field(default=None, max_length=120)
    title_hi: str | None = Field(default=None, max_length=120)


@router.post("/classes/{class_id}/syllabus/topics/{checkpoint_id}/rename")
def rename_topic(class_id: int, checkpoint_id: str, body: TopicRenameIn,
                 teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    subject = _subject(body.subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    content = get_content()
    if checkpoint_id in content.checkpoints and checkpoint_id not in content.custom_ids:
        raise HTTPException(422, "library topics can't be renamed")
    row = db.get(CustomCheckpoint, checkpoint_id)
    if row is None or row.school_id != teacher.school_id:
        raise HTTPException(404, "topic not found")
    if row.subject != subject:
        raise HTTPException(422, f"topic {checkpoint_id} belongs to {row.subject}, not {subject}")
    en = _clean(body.title_en) if body.title_en is not None else None
    hi = _clean(body.title_hi) if body.title_hi is not None else None
    if en is None and hi is None:
        raise HTTPException(422, "give title_en or title_hi")
    if en == "" or hi == "":
        raise HTTPException(422, "a title can't be empty")
    if en is not None:
        row.title_en = en
    if hi is not None:
        row.title_hi = hi
    db.flush()
    coverage.register(row)
    return coverage.syllabus(db, cls, subject)


class ReorderIn(BaseModel):
    subject: str
    order: list[str] = Field(max_length=200)


@router.post("/classes/{class_id}/syllabus/reorder")
def reorder_syllabus(class_id: int, body: ReorderIn, teacher: Teacher = Depends(current_teacher),
                     db: Session = Depends(get_db)):
    subject = _subject(body.subject, db, teacher)
    cls = owned_class(class_id, teacher, db)
    prev, rows = coverage.effective_items(db, cls, subject)
    rows = sorted(rows, key=lambda r: r["position"])
    current = [r["checkpoint_id"] for r in rows]
    if sorted(body.order) != sorted(current):
        raise HTTPException(422, "order must list exactly the current topics")
    if body.order != current:
        by_id: dict[str, list[dict]] = {}
        for r in rows:
            by_id.setdefault(r["checkpoint_id"], []).append(r)
        # each topic keeps its own chapter; only the positions change
        coverage.write_version(db, cls, teacher, subject, prev.source if prev else "template",
                               [by_id[cid].pop(0) for cid in body.order])
    return coverage.syllabus(db, cls, subject)
