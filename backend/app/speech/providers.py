"""HTTP clients for the speech providers. One request each; the router in `__init__` does fallback.

Every failure (HTTP error, timeout, malformed body) is raised as `ProviderError` with a short reason
that never contains the key. Keys come from `config.py` (environment), nowhere else.
"""
from __future__ import annotations

import base64
import binascii
import json

import httpx

from app.config import get_settings

# Tests swap this for an `httpx.MockTransport`; production uses httpx's default transport.
_transport: httpx.BaseTransport | None = None

_MIME = {"wav": "audio/wav", "webm": "audio/webm", "m4a": "audio/mp4", "aac": "audio/aac",
         "mp3": "audio/mpeg", "ogg": "audio/ogg"}


class ProviderError(Exception):
    """A provider could not produce a result; `reason` is safe to log and show."""

    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def audio_mime(filename: str) -> str:
    return _MIME.get(filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _client(timeout_s: float) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)), transport=_transport)


def _post(name: str, url: str, timeout_s: float, **kw) -> httpx.Response:
    try:
        with _client(timeout_s) as c:
            r = c.post(url, **kw)
    except httpx.TimeoutException:
        raise ProviderError(f"{name}: timed out after {timeout_s:g} s")
    except httpx.HTTPError as e:
        raise ProviderError(f"{name}: network error ({type(e).__name__})")
    if r.status_code >= 400:
        raise ProviderError(f"{name}: HTTP {r.status_code}", status=r.status_code)
    return r


def _json(name: str, r: httpx.Response) -> dict:
    try:
        j = r.json()
    except ValueError:
        raise ProviderError(f"{name}: response was not JSON")
    if not isinstance(j, dict):
        raise ProviderError(f"{name}: unexpected response shape")
    return j


class Sarvam:
    name = "sarvam"

    @staticmethod
    def code(lang: str) -> str:
        return {"or": "od"}.get(lang, lang) + "-IN"  # Sarvam calls Odia od-IN

    def stt(self, audio: bytes, filename: str, lang: str, keyterms: list[str] | None = None) -> str:
        s = get_settings()
        # keyterms are documented for saaras:v4 only, so they are not sent with saaras:v3
        data = {"model": s.sarvam_stt_model, "mode": "transcribe", "language_code": self.code(lang)}
        files = {"file": (filename, audio, audio_mime(filename))}
        r = _post("sarvam stt", f"{s.sarvam_base}/speech-to-text", s.stt_timeout_s,
                  headers={"api-subscription-key": s.sarvam_api_key}, data=data, files=files)
        return str(_json("sarvam stt", r).get("transcript") or "")

    def tts(self, text: str, lang: str) -> tuple[bytes, str]:
        s = get_settings()
        body = {"text": text, "language_code": self.code(lang), "model": s.sarvam_tts_model,
                "speaker": s.sarvam_tts_speaker, "speech_sample_rate": 22050, "output_audio_codec": "wav"}
        r = _post("sarvam tts", f"{s.sarvam_base}/text-to-speech", s.tts_timeout_s,
                  headers={"api-subscription-key": s.sarvam_api_key}, json=body)
        audios = _json("sarvam tts", r).get("audios") or []
        if not audios or not isinstance(audios[0], str):
            raise ProviderError("sarvam tts: no audio in response")
        try:
            return base64.b64decode(audios[0]), "audio/wav"
        except (binascii.Error, ValueError):
            raise ProviderError("sarvam tts: audio was not base64")


# Formats Gnani's REST STT takes. webm (the browser recorder) is not one: skip the call, Sarvam hears it.
_GNANI_AUDIO_EXT = frozenset({"wav", "mp3", "ogg", "flac", "aac", "m4a"})


class Gnani:
    name = "gnani"

    @staticmethod
    def code(lang: str) -> str:
        return lang + "-IN"

    def stt(self, audio: bytes, filename: str, lang: str, keyterms: list[str] | None = None) -> str:
        s = get_settings()
        if filename.rsplit(".", 1)[-1].lower() not in _GNANI_AUDIO_EXT:
            raise ProviderError("gnani stt: audio format not supported")
        # format=transcribe writes numbers as digits, which is what the reading scorer compares
        # (it also treats Hindi number words and digits as equal), instead of spelled-out words.
        data = {"language_code": self.code(lang), "model": s.gnani_stt_model, "format": "transcribe"}
        if keyterms and s.gnani_stt_model == "prisma-v3.0":  # roster names and target words, up to 200
            data["keyterms"] = json.dumps([k for k in keyterms if k][:200], ensure_ascii=False)
        files = {"audio_file": (filename, audio, audio_mime(filename))}
        r = _post("gnani stt", f"{s.gnani_base}/stt/v3", s.stt_timeout_s,
                  headers={"X-API-Key-ID": s.gnani_api_key}, data=data, files=files)
        j = _json("gnani stt", r)
        if j.get("success") is False:
            raise ProviderError("gnani stt: request not successful")
        return str(j.get("transcript") or "")

    def tts(self, text: str, lang: str) -> tuple[bytes, str]:
        s = get_settings()
        body = {"text": text, "voice": s.gnani_tts_voice, "model": s.gnani_tts_model,
                "language": self.code(lang), "audio_config": {"sample_rate": 22050, "container": "wav"}}
        r = _post("gnani tts", f"{s.gnani_base}/api/v1/tts/inference", s.tts_timeout_s,
                  headers={"X-API-Key-ID": s.gnani_api_key}, json=body)
        mime = r.headers.get("content-type", "audio/wav").split(";", 1)[0].strip() or "audio/wav"
        if not mime.startswith("audio/"):
            raise ProviderError(f"gnani tts: unexpected content type {mime}")
        return r.content, mime


CLIENTS = {"sarvam": Sarvam(), "gnani": Gnani()}
