"""Language and voice preferences, and the list of languages and speech providers.

GET/POST /v1/me/prefs (teacher), GET/POST /v1/parent/prefs (parent), GET /v1/languages (either token).
Contract: docs/lang_provider_contract.md section 3.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import _bearer, current_parent, current_teacher
from app.core.security import decode_token
from app.db import get_db
from app.i18n.languages import APP_LANGS, BETA_LANGS, LANGUAGES
from app.models.tables import ParentAccount, Teacher
from app.services import prefs as prefs_svc
from app.speech import capabilities

router = APIRouter(prefix="/v1", tags=["prefs"])


class PrefsIn(BaseModel):
    """Any subset; omitted or null fields keep their current value."""
    voice_provider: str | None = None
    app_lang: str | None = None
    content_lang: str | None = None


class PrefsOut(BaseModel):
    voice_provider: str
    app_lang: str
    content_lang: str
    stored: bool


def _save(db: Session, kind: str, user_id: int, school_id: int, body: PrefsIn) -> dict:
    try:
        return prefs_svc.set_prefs(db, kind, user_id, school_id, **body.model_dump())
    except prefs_svc.PrefsError as e:
        raise HTTPException(422, {"field": e.field, "message": str(e)})


@router.get("/me/prefs", response_model=PrefsOut)
def teacher_prefs(teacher: Teacher = Depends(current_teacher), db: Session = Depends(get_db)):
    return prefs_svc.get_prefs(db, "teacher", teacher.id)


@router.post("/me/prefs", response_model=PrefsOut)
def save_teacher_prefs(body: PrefsIn, teacher: Teacher = Depends(current_teacher),
                       db: Session = Depends(get_db)):
    return _save(db, "teacher", teacher.id, teacher.school_id, body)


@router.get("/parent/prefs", response_model=PrefsOut)
def parent_prefs(parent: ParentAccount = Depends(current_parent), db: Session = Depends(get_db)):
    return prefs_svc.get_prefs(db, "parent", parent.id)


@router.post("/parent/prefs", response_model=PrefsOut)
def save_parent_prefs(body: PrefsIn, parent: ParentAccount = Depends(current_parent),
                      db: Session = Depends(get_db)):
    return _save(db, "parent", parent.id, parent.school_id, body)


def any_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A teacher or a parent with a valid token (the language list is the same for both)."""
    try:
        payload = decode_token(_bearer(authorization))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "invalid token")
    model = {"teacher": Teacher, "parent": ParentAccount}.get(payload.get("kind"))
    if model is None:
        raise HTTPException(403, "teacher or parent token required")
    user = db.get(model, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "user not found")
    return user


@router.get("/languages")
def languages(_user=Depends(any_user)):
    """App languages (all 23), content languages (those a configured provider can hear and speak, or
    Hindi + English with no provider), and the speech providers."""
    def lang_row(code: str) -> dict:
        lg = LANGUAGES[code]
        return {"code": code, "name_en": lg.name_en, "name_native": lg.name_native, "rtl": lg.rtl,
                "beta": code in BETA_LANGS}

    return {
        "app_languages": [lang_row(c) for c in APP_LANGS],
        "content_languages": [{**{k: v for k, v in lang_row(c).items() if k != "beta"},
                               "stt": capabilities.providers_for("stt", c),
                               "tts": capabilities.providers_for("tts", c)}
                              for c in capabilities.content_languages()],
        # NAMES is optional in the speech module; fall back to the capitalised key ("Sarvam", "Gnani")
        "providers": [{"key": p, "name": getattr(capabilities, "NAMES", {}).get(p, p.title()),
                       "configured": capabilities.configured(p),
                       "default": p == capabilities.DEFAULT_PROVIDER}
                      for p in capabilities.PROVIDERS],
    }
