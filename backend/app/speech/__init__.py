"""Speech in and out for every content language, through Sarvam (default) or Gnani.

`transcribe` and `synthesize` try the caller's preferred provider first, then the other one, skipping
any provider that has no key or does not support the language. A provider is abandoned on an
exception, a timeout, an HTTP error or an empty result, and the next one is tried. With no key at all
the app still runs: STT returns an empty transcript and TTS returns None (the phone's voice speaks).

`get_asr()` / `has_asr()` / `ASRProvider` are kept for older call sites; they now go through the
same router, so they are language-aware too.
"""
from __future__ import annotations

import io
import logging
import re
import wave
from dataclasses import dataclass, field
from typing import Protocol

from app.config import get_settings
from app.speech import capabilities
from app.speech.capabilities import DEFAULT_PROVIDER, PROVIDERS, normalize_lang
from app.speech.providers import CLIENTS, ProviderError

log = logging.getLogger(__name__)

_LETTER_OR_DIGIT = re.compile(r"\w", re.UNICODE)


@dataclass
class Transcript:
    text: str
    lang: str = "hi"
    provider: str | None = None  # who produced `text`; None when nobody did
    fallback_used: bool = False  # True when `provider` is not the first one tried
    error: str | None = None  # why something went wrong (or was clipped), safe to show
    avg_confidence: float = 1.0  # kept for old callers
    failed: bool = False  # every provider tried raised (old callers expect an exception then)
    tried: list[str] = field(default_factory=list)

    @property
    def language(self) -> str:  # old field name
        return self.lang


@dataclass
class Speech:
    audio: bytes
    mime: str
    provider: str


def _clip_wav(audio: bytes, max_s: float) -> tuple[bytes, bool]:
    """Keep the first `max_s` seconds of a PCM WAV. Anything that is not a readable WAV is returned as is."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            params = w.getparams()
            if not params.framerate or params.nframes / params.framerate <= max_s:
                return audio, False
            frames = w.readframes(int(max_s * params.framerate))
    except (wave.Error, EOFError, ValueError):
        return audio, False
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return out.getvalue(), True


def _usable_text(text: str) -> bool:
    return bool(_LETTER_OR_DIGIT.search(text or ""))


def transcribe(audio: bytes, filename: str, lang: str = "hi", keyterms: list[str] | None = None,
               preferred: str = DEFAULT_PROVIDER) -> Transcript:
    """Speech → text in `lang`. Never raises; read `error` / `failed` on the result."""
    code = normalize_lang(lang)
    s = get_settings()
    audio, clipped = _clip_wav(audio, s.stt_max_seconds)
    note = f"audio longer than {s.stt_max_seconds:g} s: only the first {s.stt_max_seconds:g} s were transcribed" \
        if clipped else None
    chain = capabilities.order("stt", code, preferred)
    if not chain:
        why = "no speech provider configured" if not any(capabilities.configured(p) for p in PROVIDERS) \
            else f"no configured provider transcribes '{code}'"
        return Transcript(text="", lang=code, error=why, avg_confidence=0.0)
    errors: list[str] = []
    raised = 0
    for i, name in enumerate(chain):
        try:
            text = CLIENTS[name].stt(audio, filename, code, keyterms).strip()
        except ProviderError as e:
            errors.append(e.reason)
            raised += 1
            log.warning("speech stt fallback: %s", e.reason)
            continue
        except Exception as e:  # a bug in one client must not take the request down
            errors.append(f"{name}: {type(e).__name__}")
            raised += 1
            log.warning("speech stt fallback: %s failed (%s)", name, type(e).__name__)
            continue
        if not _usable_text(text):
            errors.append(f"{name}: empty transcript")
            continue
        return Transcript(text=text, lang=code, provider=name, fallback_used=i > 0,
                          error="; ".join(filter(None, [note, *errors])) or None, tried=chain[:i + 1])
    return Transcript(text="", lang=code, error="; ".join(filter(None, [note, *errors])), avg_confidence=0.0,
                      failed=raised == len(chain), tried=list(chain))


def synthesize(text: str, lang: str = "hi", preferred: str = DEFAULT_PROVIDER) -> Speech | None:
    """Text → audio in `lang`, or None when no configured provider can speak it (use the phone's voice)."""
    text = (text or "").strip()
    if not text:
        return None
    code = normalize_lang(lang)
    for name in capabilities.order("tts", code, preferred):
        try:
            audio, mime = CLIENTS[name].tts(text, code)
        except ProviderError as e:
            log.warning("speech tts fallback: %s", e.reason)
            continue
        except Exception as e:
            log.warning("speech tts fallback: %s failed (%s)", name, type(e).__name__)
            continue
        if len(audio) < 64:  # a WAV header alone is 44 bytes: nothing to play
            log.warning("speech tts fallback: %s returned no audio", name)
            continue
        return Speech(audio=audio, mime=mime, provider=name)
    return None


# ---------------------------------------------------------------- old interface (kept for call sites)

class ASRProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript: ...

    def tts(self, text: str, language: str = "hi") -> bytes: ...


class RouterASR:
    """`get_asr()` when a key is set: the router behind the old method names.

    As before, a total outage raises (callers turn that into `asr: failed`), while an empty result
    comes back as an empty transcript.
    """

    def __init__(self, preferred: str = DEFAULT_PROVIDER) -> None:
        self.preferred = preferred
        self.name = preferred

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript:
        t = transcribe(audio, filename, lang=language, keyterms=keyterms, preferred=self.preferred)
        if t.failed:
            raise RuntimeError(t.error or "speech recognition failed")
        return t

    def tts(self, text: str, language: str = "hi") -> bytes:
        sp = synthesize(text, lang=language, preferred=self.preferred)
        return sp.audio if sp else b""


SarvamASR = RouterASR  # old name


class MockASR:
    """No-key mode: returns silence so callers take the explicit `low_audio_quality` path."""

    name = "mock"

    def transcribe(self, audio: bytes, filename: str, language: str = "hi",
                   keyterms: list[str] | None = None) -> Transcript:
        return Transcript(text="", lang=normalize_lang(language), avg_confidence=0.0)

    def tts(self, text: str, language: str = "hi") -> bytes:
        return b""


def has_asr() -> bool:
    return any(capabilities.configured(p) for p in PROVIDERS)


def get_asr(preferred: str = DEFAULT_PROVIDER) -> ASRProvider:
    return RouterASR(preferred) if has_asr() else MockASR()


__all__ = ["Transcript", "Speech", "transcribe", "synthesize", "ASRProvider", "RouterASR", "SarvamASR",
           "MockASR", "get_asr", "has_asr", "capabilities"]
