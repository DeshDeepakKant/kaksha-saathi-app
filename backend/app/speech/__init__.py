"""Speech provider interface. Sarvam is primary; a mock provider lets the app run with no keys."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings


@dataclass
class Transcript:
    text: str
    language: str = "hi"
    avg_confidence: float = 1.0


class ASRProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript: ...

    def tts(self, text: str, language: str = "hi") -> bytes: ...


class SarvamASR:
    name = "sarvam"

    def __init__(self) -> None:
        s = get_settings()
        self.key = s.sarvam_api_key
        self.base = s.sarvam_base

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript:
        headers = {"api-subscription-key": self.key}
        data = {"model": "saarika:v2.5", "language_code": "hi-IN" if language == "hi" else "en-IN"}
        files = {"file": (filename, audio, "application/octet-stream")}
        with httpx.Client(timeout=60) as c:
            r = c.post(f"{self.base}/speech-to-text", headers=headers, data=data, files=files)
            r.raise_for_status()
            j = r.json()
        return Transcript(text=(j.get("transcript") or "").strip(), language=language)

    def tts(self, text: str, language: str = "hi") -> bytes:
        headers = {"api-subscription-key": self.key, "Content-Type": "application/json"}
        body = {"inputs": [text], "target_language_code": "hi-IN" if language == "hi" else "en-IN",
                "speaker": "meera", "speech_sample_rate": 22050, "model": "bulbul:v2"}
        with httpx.Client(timeout=60) as c:
            r = c.post(f"{self.base}/text-to-speech", headers=headers, json=body)
            r.raise_for_status()
            return base64.b64decode(r.json()["audios"][0])


class MockASR:
    """No-key mode: returns silence so callers take the explicit `low_audio_quality` path."""

    name = "mock"

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript:
        return Transcript(text="", language=language, avg_confidence=0.0)

    def tts(self, text: str, language: str = "hi") -> bytes:
        return b""


def get_asr() -> ASRProvider:
    s = get_settings()
    return SarvamASR() if s.sarvam_api_key else MockASR()


def has_asr() -> bool:
    return bool(get_settings().sarvam_api_key)
