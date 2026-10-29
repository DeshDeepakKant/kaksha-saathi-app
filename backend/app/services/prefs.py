"""Per-user language and voice preferences (docs/lang_provider_contract.md section 3).

No stored row means the defaults, which reproduce the app's behaviour from before preferences existed.
Validation of new values lives here too so the routes and any other caller agree on what is allowed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.i18n.languages import APP_LANGS, LANGUAGES
from app.models.tables import ParentAccount, Teacher, UserPrefs, utcnow
from app.speech import capabilities

DEFAULTS = {"voice_provider": capabilities.DEFAULT_PROVIDER, "app_lang": "en", "content_lang": "hi"}
FIELDS = tuple(DEFAULTS)
KINDS = ("teacher", "parent")


class PrefsError(ValueError):
    """A preference value that is not allowed; `field` names the offending field."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _row(db: Session, kind: str, user_id: int) -> UserPrefs | None:
    return db.scalar(select(UserPrefs).where(UserPrefs.kind == kind, UserPrefs.user_id == user_id))


def get_prefs(db: Session, kind: str, user_id: int) -> dict:
    """`{voice_provider, app_lang, content_lang, stored}`; defaults (stored=False) when nothing is saved."""
    row = _row(db, kind, user_id)
    if row is None:
        return {**DEFAULTS, "stored": False}
    return {"voice_provider": row.voice_provider, "app_lang": row.app_lang,
            "content_lang": row.content_lang, "stored": True}


def validate(fields: dict) -> None:
    """Raise PrefsError for a value outside the allowed sets. None values are 'leave unchanged'."""
    vp, app, content = fields.get("voice_provider"), fields.get("app_lang"), fields.get("content_lang")
    if vp is not None and vp not in capabilities.PROVIDERS:
        raise PrefsError("voice_provider", f"voice_provider must be one of {list(capabilities.PROVIDERS)}")
    if app is not None and app not in APP_LANGS:
        raise PrefsError("app_lang", f"app_lang must be one of {list(APP_LANGS)}")
    if content is not None:
        allowed = capabilities.content_languages()
        if content not in allowed:
            raise PrefsError("content_lang", f"content_lang must be one of {allowed}")


def set_prefs(db: Session, kind: str, user_id: int, school_id: int, **fields) -> dict:
    """Save the given fields (others keep their stored or default value) and return the new prefs."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown preference fields: {sorted(unknown)}")
    fields = {k: v for k, v in fields.items() if v is not None}
    validate(fields)
    row = _row(db, kind, user_id)
    if row is None:
        row = UserPrefs(kind=kind, user_id=user_id, school_id=school_id, **DEFAULTS)
        db.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    row.updated_at = utcnow()
    db.flush()
    return get_prefs(db, kind, user_id)


def _who(teacher: Teacher | None, parent: ParentAccount | None) -> tuple[str, int] | None:
    if teacher is not None:
        return "teacher", teacher.id
    if parent is not None:
        return "parent", parent.id
    return None


def content_lang_for(db: Session, teacher: Teacher | None = None, parent: ParentAccount | None = None) -> str:
    """The content language for this user: what children read, hear and speak. Default 'hi'.

    A stored code is returned as long as it is a known language, even if no speech provider currently
    covers it (keys can come and go; text features still work and speech falls back to the phone)."""
    who = _who(teacher, parent)
    if who is None:
        return DEFAULTS["content_lang"]
    code = get_prefs(db, *who)["content_lang"]
    return code if code in LANGUAGES else DEFAULTS["content_lang"]


def provider_for(db: Session, teacher: Teacher | None = None, parent: ParentAccount | None = None) -> str:
    """The user's preferred speech provider. Default 'sarvam'."""
    who = _who(teacher, parent)
    if who is None:
        return DEFAULTS["voice_provider"]
    vp = get_prefs(db, *who)["voice_provider"]
    return vp if vp in capabilities.PROVIDERS else DEFAULTS["voice_provider"]
