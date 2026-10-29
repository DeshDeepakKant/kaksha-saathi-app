"""Server speech for both apps: POST /v1/speech/tts → audio, or 204 so the phone's own voice speaks."""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import _bearer
from app.core.security import decode_token
from app.db import get_db
from app.models.tables import ParentAccount, Teacher
from app.speech import synthesize
from app.speech.capabilities import APP_LANGS, DEFAULT_PROVIDER, PROVIDERS, normalize_lang

router = APIRouter(prefix="/v1")

MAX_TTS_CHARS = 2000
_CACHE_SIZE = 128
_cache: OrderedDict[tuple[str, str, str], tuple[bytes, str, str]] = OrderedDict()
_cache_lock = Lock()


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    lang: str = "hi"


def current_user(authorization: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> Teacher | ParentAccount:
    """A teacher or a parent: either token kind is accepted here."""
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
    if not user:
        raise HTTPException(401, "user not found")
    return user


def _preferred(db: Session, user: Teacher | ParentAccount) -> str:
    try:
        from app.services.prefs import provider_for
    except ImportError:  # preferences not merged yet
        return DEFAULT_PROVIDER
    try:
        p = provider_for(db, teacher=user) if isinstance(user, Teacher) else provider_for(db, parent=user)
    except Exception:
        return DEFAULT_PROVIDER
    return p if p in PROVIDERS else DEFAULT_PROVIDER


def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
        return hit


def _cache_put(key, value) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


@router.post("/speech/tts")
def speech_tts(body: TTSIn, user=Depends(current_user), db: Session = Depends(get_db)):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text is empty")
    lang = normalize_lang(body.lang)
    if lang not in APP_LANGS:
        raise HTTPException(422, f"unknown language '{body.lang}'")
    preferred = _preferred(db, user)
    key = (lang, preferred, text)
    hit = _cache_get(key)
    if hit is None:
        sp = synthesize(text, lang=lang, preferred=preferred)
        if sp is None:
            return Response(status_code=204)
        hit = (sp.audio, sp.mime, sp.provider)
        _cache_put(key, hit)
    audio, mime, provider = hit
    return Response(content=audio, media_type=mime, headers={"X-Speech-Provider": provider})
