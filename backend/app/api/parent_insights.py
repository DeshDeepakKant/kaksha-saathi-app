"""Parent insights API (school → home): what the class is learning, the child's journey, tips for
specific mistakes, teacher-noticed moments and the weekly summary. Parent JWT; own child only.

Contract: docs/parent_insights_contract.md. All texts are deterministic templates (no runtime AI).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import current_parent
from app.db import get_db
from app.models.tables import ParentAccount
from app.services import parent_insights as insights
from app.services.subjects import resolve_subject

router = APIRouter(prefix="/v1")


@router.get("/parent/school_week")
def school_week(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return insights.school_week(db, parent.child_id)


@router.get("/parent/journey")
def journey(subject: str = Query("numeracy", max_length=16), parent: ParentAccount = Depends(current_parent),
            db: Session = Depends(get_db)):
    # "english", "hindi", "maths" and a school's own subjects all work; anything else is a 422
    return insights.journey(db, parent.child_id, resolve_subject(db, parent.school_id, subject))


@router.get("/parent/tips")
def tips(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return insights.tips_for(db, parent.child_id)


@router.get("/parent/moments")
def moments(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return insights.moments(db, parent.child_id)


@router.get("/parent/weekly")
def weekly(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return insights.weekly(db, parent.child_id)
