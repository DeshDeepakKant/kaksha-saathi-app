"""Speech router: provider order, fallback, language mapping and the /v1/speech/tts endpoint.

No real Sarvam/Gnani call is made: HTTP goes through an httpx MockTransport.
"""
import base64
import io
import json
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import speech
from app.api import speech as speech_api
from app.config import get_settings
from app.speech import capabilities, providers

WAV_BYTES = b"RIFF" + b"\x00" * 200  # stands in for real TTS audio


def _wav(seconds: float, rate: int = 8000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return out.getvalue()


def _form(req: httpx.Request) -> bytes:
    req.read()
    return req.content


def _field(req: httpx.Request, name: str, value: str) -> bool:
    return f'name="{name}"\r\n\r\n{value}\r\n'.encode() in _form(req)


class Net:
    """Scripted provider responses. `routes[(provider, cap)]` is a list consumed per call."""

    def __init__(self):
        self.calls: list[tuple[str, str, httpx.Request]] = []
        self.routes: dict[tuple[str, str], list] = {}

    def on(self, provider, cap, *responses):
        self.routes[(provider, cap)] = list(responses)
        return self

    def handler(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        provider = "sarvam" if "sarvam" in host else "gnani"
        cap = "stt" if ("speech-to-text" in path or path.endswith("/stt/v3")) else "tts"
        self.calls.append((provider, cap, req))
        queue = self.routes.get((provider, cap)) or ["500"]
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        if r == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        if r == "500":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        if isinstance(r, int):
            return httpx.Response(r, json={"error": {"message": "bad"}})
        return r

    def order(self):
        return [(p, c) for p, c, _ in self.calls]


def stt_ok(provider, text):
    return httpx.Response(200, json={"transcript": text, "request_id": "x"} if provider == "sarvam"
                          else {"success": True, "transcript": text, "model": "prisma-v3.0"})


def tts_ok(provider):
    if provider == "sarvam":
        return httpx.Response(200, json={"request_id": "x", "audios": [base64.b64encode(WAV_BYTES).decode()]})
    return httpx.Response(200, content=WAV_BYTES, headers={"content-type": "audio/wav"})


@pytest.fixture
def keys(monkeypatch):
    s = get_settings()

    def set_keys(sarvam="", gnani=""):
        monkeypatch.setattr(s, "sarvam_api_key", sarvam)
        monkeypatch.setattr(s, "gnani_api_key", gnani)

    set_keys()
    return set_keys


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(providers, "_transport", httpx.MockTransport(n.handler))
    speech_api._cache.clear()
    yield n
    speech_api._cache.clear()


# ------------------------------------------------------------------ capabilities

def test_language_codes_normalise():
    assert capabilities.normalize_lang("hi-IN") == "hi"
    assert capabilities.normalize_lang("od-IN") == "or"
    assert capabilities.normalize_lang(None) == "hi"
    assert providers.Sarvam.code("or") == "od-IN" and providers.Gnani.code("mr") == "mr-IN"


def test_sarvam_hears_all_23_and_speaks_11():
    assert capabilities.SUPPORT["sarvam"]["stt"] == frozenset(capabilities.APP_LANGS)
    assert len(capabilities.APP_LANGS) == 23
    assert len(capabilities.SUPPORT["sarvam"]["tts"]) == 11
    assert not capabilities.supports("gnani", "stt", "or")


def test_content_languages_follow_configured_keys(keys):
    assert capabilities.content_languages() == ["hi", "en"]
    keys(sarvam="k")
    sarvam_only = capabilities.content_languages()
    assert sarvam_only == [c for c in capabilities.APP_LANGS if c in capabilities.SUPPORT["sarvam"]["tts"]]
    assert sarvam_only[:2] == ["en", "hi"] and "or" in sarvam_only and "as" not in sarvam_only
    keys(gnani="g")
    assert "or" not in capabilities.content_languages() and len(capabilities.content_languages()) == 10


def test_providers_for_puts_default_first(keys):
    keys(sarvam="k", gnani="g")
    assert capabilities.DEFAULT_PROVIDER == "gnani"
    assert capabilities.providers_for("stt", "hi") == ["gnani", "sarvam"]
    assert capabilities.order("stt", "hi", "sarvam") == ["sarvam", "gnani"]
    assert capabilities.order("stt", "hi", None) == ["gnani", "sarvam"]
    assert capabilities.providers_for("stt", "or") == ["sarvam"]  # Gnani does not cover Odia
    assert capabilities.providers_for("tts", "as") == []


# ------------------------------------------------------------------ no key

def test_no_key_uses_mock_and_never_calls_out(keys, net):
    assert speech.has_asr() is False
    asr = speech.get_asr()
    assert isinstance(asr, speech.MockASR)
    assert asr.transcribe(b"\x00", "a.wav", language="mr").text == ""
    t = speech.transcribe(b"\x00", "a.wav", lang="hi")
    assert t.text == "" and t.provider is None and "no speech provider" in t.error
    assert speech.synthesize("नमस्ते", "hi") is None
    assert net.calls == []


# ------------------------------------------------------------------ STT

def test_sarvam_stt_request_shape(keys, net):
    keys(sarvam="k")
    net.on("sarvam", "stt", stt_ok("sarvam", " नमस्ते "))
    t = speech.transcribe(b"\x00" * 10, "note.wav", lang="hi")
    assert (t.text, t.provider, t.fallback_used, t.error) == ("नमस्ते", "sarvam", False, None)
    _, _, req = net.calls[0]
    assert req.url.path == "/speech-to-text" and req.headers["api-subscription-key"] == "k"
    assert _field(req, "model", "saaras:v3") and _field(req, "mode", "transcribe")
    assert _field(req, "language_code", "hi-IN")


def test_odia_maps_to_od_IN_and_skips_gnani(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("sarvam", "stt", stt_ok("sarvam", "ନମସ୍କାର"))
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="or", preferred="gnani")
    assert t.provider == "sarvam" and t.lang == "or" and t.fallback_used is False
    assert net.order() == [("sarvam", "stt")]
    assert _field(net.calls[0][2], "language_code", "od-IN")


def test_preferred_provider_first_then_fallback_on_http_error(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "stt", "500").on("sarvam", "stt", stt_ok("sarvam", "मराठी"))
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="mr", preferred="gnani")
    assert net.order() == [("gnani", "stt"), ("sarvam", "stt")]
    assert t.provider == "sarvam" and t.fallback_used is True and "gnani stt: HTTP 500" in t.error
    g = net.calls[0][2]
    assert g.headers["X-API-Key-ID"] == "g" and g.url.path == "/stt/v3"
    assert _field(g, "language_code", "mr-IN") and _field(g, "model", "prisma-v3.0")
    assert b'name="audio_file"' in _form(g)


def test_timeout_falls_back(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "stt", "timeout").on("sarvam", "stt", stt_ok("sarvam", "hello"))
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="en")
    assert t.provider == "sarvam" and t.fallback_used and "timed out" in t.error


def test_empty_transcript_falls_back(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "stt", stt_ok("gnani", "  ")).on("sarvam", "stt", stt_ok("sarvam", "पाँच"))
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="hi")
    assert t.text == "पाँच" and t.provider == "sarvam" and "empty transcript" in t.error


def test_all_empty_is_empty_not_failed(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("sarvam", "stt", stt_ok("sarvam", "")).on("gnani", "stt", stt_ok("gnani", "..."))
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="hi")
    assert t.text == "" and t.provider is None and t.failed is False
    assert speech.get_asr().transcribe(b"\x00", "a.wav").text == ""  # old callers: silence, no exception


def test_total_outage_raises_for_old_callers(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("sarvam", "stt", "500").on("gnani", "stt", "timeout")
    t = speech.transcribe(b"\x00" * 10, "a.wav", lang="hi")
    assert t.failed and t.text == "" and "sarvam" in t.error and "gnani" in t.error
    with pytest.raises(RuntimeError):
        speech.get_asr().transcribe(b"\x00", "a.wav", language="hi")


def test_unsupported_language_has_no_provider(keys, net):
    keys(gnani="g")  # Gnani does not hear Assamese
    t = speech.transcribe(b"\x00", "a.wav", lang="as")
    assert t.text == "" and "'as'" in t.error and net.calls == []


def test_long_wav_is_clipped_and_said_so(keys, net):
    keys(sarvam="k")
    net.on("sarvam", "stt", stt_ok("sarvam", "कहानी"))
    long_wav = _wav(31)
    t = speech.transcribe(long_wav, "read.wav", lang="hi")
    assert t.text == "कहानी" and "first 30 s" in t.error
    sent = _form(net.calls[0][2])
    assert len(sent) < len(long_wav)


def test_short_wav_is_untouched(keys, net):
    keys(sarvam="k")
    net.on("sarvam", "stt", stt_ok("sarvam", "ठीक"))
    assert speech.transcribe(_wav(2), "a.wav").error is None


def test_old_interface_is_language_aware(keys, net):
    keys(sarvam="k")
    net.on("sarvam", "stt", stt_ok("sarvam", "বাংলা"))
    asr = speech.get_asr()
    assert asr.transcribe(b"\x00" * 10, "a.wav", language="bn", keyterms=["x"]).text == "বাংলা"
    assert _field(net.calls[0][2], "language_code", "bn-IN")


# ------------------------------------------------------------------ TTS

def test_sarvam_tts_request_shape(keys, net):
    keys(sarvam="k")
    net.on("sarvam", "tts", tts_ok("sarvam"))
    sp = speech.synthesize("नमस्ते", "mr")
    assert sp.audio == WAV_BYTES and sp.mime == "audio/wav" and sp.provider == "sarvam"
    body = json.loads(net.calls[0][2].content)
    assert body["model"] == "bulbul:v3" and body["language_code"] == "mr-IN" and body["text"] == "नमस्ते"
    assert body["speaker"] == get_settings().sarvam_tts_speaker


def test_tts_falls_back_to_sarvam(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "tts", 429).on("sarvam", "tts", tts_ok("sarvam"))
    sp = speech.synthesize("hello", "en")
    assert net.order() == [("gnani", "tts"), ("sarvam", "tts")]
    assert sp.provider == "sarvam" and sp.audio == WAV_BYTES
    body = json.loads(net.calls[1][2].content)
    assert body["language_code"] == "en-IN" and body["model"] and body["speaker"]


def test_gnani_is_first_and_speaks_with_timbre_v3(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "tts", tts_ok("gnani"))
    sp = speech.synthesize("hello", "en")
    assert sp.provider == "gnani" and net.order() == [("gnani", "tts")]
    body = json.loads(net.calls[0][2].content)
    assert body["model"] == "timbre-v3.0" and body["language"] == "en-IN" and body["voice"]


def test_gnani_stt_request_uses_prisma_v3_digits_and_keyterms(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "stt", stt_ok("gnani", "23"))
    t = speech.transcribe(b"\x00" * 10, "a.m4a", lang="hi", keyterms=["गिनती", "पाँच"])
    assert t.provider == "gnani" and not t.fallback_used and net.order() == [("gnani", "stt")]
    req = net.calls[0][2]
    body = req.content.decode("utf-8", "ignore")
    assert req.headers["X-API-Key-ID"] == "g" and req.url.path == "/stt/v3"
    for part in ("prisma-v3.0", "hi-IN", "transcribe", "गिनती"):
        assert part in body, part


def test_webm_skips_gnani_without_a_wasted_call(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("sarvam", "stt", stt_ok("sarvam", "नमस्ते"))
    t = speech.transcribe(b"\x00" * 10, "turn.webm", lang="hi")
    assert net.order() == [("sarvam", "stt")] and t.provider == "sarvam" and t.fallback_used


def test_tts_empty_audio_falls_back(keys, net):
    keys(sarvam="k", gnani="g")
    net.on("gnani", "tts", httpx.Response(200, content=b"", headers={"content-type": "audio/wav"}))
    net.on("sarvam", "tts", tts_ok("sarvam"))
    assert speech.synthesize("hello", "en", preferred="gnani").provider == "sarvam"


def test_tts_none_when_language_unspoken(keys, net):
    keys(sarvam="k", gnani="g")
    assert speech.synthesize("नमस्ते", "sa") is None and net.calls == []
    assert speech.synthesize("   ", "hi") is None


# ------------------------------------------------------------------ /v1/speech/tts

@pytest.fixture
def api(client):
    app = FastAPI()
    app.include_router(speech_api.router)
    with TestClient(app) as c:
        yield c


def test_tts_endpoint_204_without_provider(api, teacher_headers, keys, net):
    r = api.post("/v1/speech/tts", json={"text": "नमस्ते", "lang": "hi"}, headers=teacher_headers)
    assert r.status_code == 204 and r.content == b""


def test_tts_endpoint_audio_for_teacher_and_parent_and_caches(api, teacher_headers, parent_headers, keys, net):
    """Same preferred provider for both callers -> the second request is a cache hit."""
    from sqlalchemy import delete
    from app.db import SessionLocal
    from app.models.tables import UserPrefs
    with SessionLocal() as db:  # other tests may have stored a different provider for these demo users
        db.execute(delete(UserPrefs))
        db.commit()
    keys(sarvam="k")
    net.on("sarvam", "tts", tts_ok("sarvam"))
    for h in (teacher_headers, parent_headers):
        r = api.post("/v1/speech/tts", json={"text": "नमस्ते", "lang": "mr"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "audio/wav" and r.headers["X-Speech-Provider"] == "sarvam"
        assert r.content == WAV_BYTES
    assert len(net.calls) == 1  # second request served from the cache


def test_tts_endpoint_204_for_language_nobody_speaks(api, parent_headers, keys, net):
    keys(sarvam="k")
    r = api.post("/v1/speech/tts", json={"text": "नमः", "lang": "sa"}, headers=parent_headers)
    assert r.status_code == 204 and net.calls == []


def test_tts_endpoint_validation_and_auth(api, teacher_headers, keys, net):
    assert api.post("/v1/speech/tts", json={"text": "x", "lang": "hi"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert api.post("/v1/speech/tts", json={"text": "x"}, headers=bad).status_code == 401
    assert api.post("/v1/speech/tts", json={"text": "x" * 2001}, headers=teacher_headers).status_code == 422
    assert api.post("/v1/speech/tts", json={"text": "x", "lang": "zz"}, headers=teacher_headers).status_code == 422
    assert api.post("/v1/speech/tts", json={"text": "   "}, headers=teacher_headers).status_code == 422
