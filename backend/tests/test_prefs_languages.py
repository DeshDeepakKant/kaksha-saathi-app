"""Per-user language/voice preferences and the /v1/languages list (docs/lang_provider_contract.md §3).

Uses its own app with the prefs router so it runs whether or not main.py registers the router yet.
Tokens come from the real login routes (same JWT secret, same database)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api import prefs as prefs_api
from app.db import SessionLocal
from app.i18n.languages import APP_LANGS
from app.models.tables import ParentAccount, Teacher, UserPrefs
from app.services import prefs as prefs_svc
from app.speech import capabilities


@pytest.fixture(scope="module")
def pc():
    app = FastAPI()
    app.include_router(prefs_api.router)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_prefs():
    with SessionLocal() as db:
        db.execute(delete(UserPrefs))
        db.commit()
    yield


def test_defaults_when_nothing_stored(pc, teacher_headers, parent_headers):
    want = {"voice_provider": "gnani", "app_lang": "en", "content_lang": "hi", "stored": False}
    assert pc.get("/v1/me/prefs", headers=teacher_headers).json() == want
    assert pc.get("/v1/parent/prefs", headers=parent_headers).json() == want


def test_partial_update_keeps_other_fields(pc, teacher_headers):
    r = pc.post("/v1/me/prefs", json={"app_lang": "mr"}, headers=teacher_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"voice_provider": "gnani", "app_lang": "mr", "content_lang": "hi", "stored": True}
    r = pc.post("/v1/me/prefs", json={"voice_provider": "sarvam", "content_lang": "en"}, headers=teacher_headers)
    assert r.json() == {"voice_provider": "sarvam", "app_lang": "mr", "content_lang": "en", "stored": True}
    assert pc.get("/v1/me/prefs", headers=teacher_headers).json()["app_lang"] == "mr"


def test_teacher_and_parent_prefs_are_separate(pc, teacher_headers, parent_headers):
    pc.post("/v1/me/prefs", json={"app_lang": "ta"}, headers=teacher_headers)
    r = pc.post("/v1/parent/prefs", json={"app_lang": "ur"}, headers=parent_headers)
    assert r.json()["app_lang"] == "ur"
    assert pc.get("/v1/me/prefs", headers=teacher_headers).json()["app_lang"] == "ta"


@pytest.mark.parametrize("body,field", [
    ({"app_lang": "xx"}, "app_lang"),
    ({"voice_provider": "google"}, "voice_provider"),
    ({"content_lang": "mr"}, "content_lang"),  # no speech key in tests -> only hi/en are content languages
    ({"content_lang": "zz"}, "content_lang"),
])
def test_invalid_values_are_422(pc, teacher_headers, body, field):
    r = pc.post("/v1/me/prefs", json=body, headers=teacher_headers)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["field"] == field
    assert pc.get("/v1/me/prefs", headers=teacher_headers).json()["stored"] is False


def test_tokens_are_checked(pc, teacher_headers, parent_headers):
    assert pc.get("/v1/me/prefs").status_code == 401
    assert pc.get("/v1/parent/prefs", headers=teacher_headers).status_code == 403
    assert pc.post("/v1/me/prefs", json={}, headers=parent_headers).status_code == 403
    assert pc.get("/v1/languages").status_code == 401
    assert pc.get("/v1/languages", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_languages_without_speech_keys(pc, teacher_headers, parent_headers):
    for h in (teacher_headers, parent_headers):
        r = pc.get("/v1/languages", headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert [a["code"] for a in j["app_languages"]] == list(APP_LANGS)
        ur = next(a for a in j["app_languages"] if a["code"] == "ur")
        assert ur["rtl"] is True and ur["name_native"] == "اردو"
        assert [c["code"] for c in j["content_languages"]] == ["hi", "en"]
        assert all(c["stt"] == [] and c["tts"] == [] for c in j["content_languages"])
        assert j["providers"] == [
            {"key": "gnani", "name": "Gnani", "configured": False, "default": True},
            {"key": "sarvam", "name": "Sarvam", "configured": False, "default": False},
        ]


def test_content_language_follows_configured_providers(pc, teacher_headers, monkeypatch):
    monkeypatch.setattr(capabilities, "configured", lambda p: p == "sarvam")
    j = pc.get("/v1/languages", headers=teacher_headers).json()
    codes = [c["code"] for c in j["content_languages"]]
    assert codes == ["en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "ml", "or", "pa"]
    mr = next(c for c in j["content_languages"] if c["code"] == "mr")
    assert mr["stt"] == ["sarvam"] and mr["tts"] == ["sarvam"]
    r = pc.post("/v1/me/prefs", json={"content_lang": "mr"}, headers=teacher_headers)
    assert r.status_code == 200 and r.json()["content_lang"] == "mr"


def test_service_helpers(teacher_headers, parent_headers):
    with SessionLocal() as db:
        t = db.query(Teacher).first()
        p = db.query(ParentAccount).first()
        assert prefs_svc.content_lang_for(db, teacher=t) == "hi"
        assert prefs_svc.provider_for(db, parent=p) == "gnani"
        assert prefs_svc.content_lang_for(db) == "hi"
        prefs_svc.set_prefs(db, "teacher", t.id, t.school_id, voice_provider="sarvam", content_lang="en")
        assert prefs_svc.content_lang_for(db, teacher=t) == "en"
        assert prefs_svc.provider_for(db, teacher=t) == "sarvam"
        assert prefs_svc.provider_for(db, parent=p) == "gnani"  # parent untouched
        with pytest.raises(prefs_svc.PrefsError):
            prefs_svc.set_prefs(db, "parent", p.id, p.school_id, app_lang="klingon")
        with pytest.raises(ValueError):
            prefs_svc.set_prefs(db, "parent", p.id, p.school_id, colour="blue")
        db.commit()
