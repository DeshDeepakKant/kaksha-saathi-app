"""Which speech provider can hear (STT) and speak (TTS) which language.

Codes are the ISO 639 codes of the language registry (Odia is `or`); each provider maps them to its
own codes in `providers.py`. A provider counts only when its key is configured.
"""
from __future__ import annotations

from app.config import get_settings

try:  # the registry owns the canonical order; this copy keeps the module usable on its own
    from app.i18n.languages import APP_LANGS
except ImportError:  # pragma: no cover - registry not merged yet
    APP_LANGS: tuple[str, ...] = ("en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "ml", "or", "pa", "as",
                                  "ur", "sa", "ne", "kok", "mai", "doi", "sd", "ks", "brx", "mni", "sat")

PROVIDERS = ("gnani", "sarvam")
# Gnani first (its newest Prisma/Timbre models, per language it supports); Sarvam answers when Gnani is
# not configured, does not cover the language, or fails. `order()` skips unconfigured providers.
DEFAULT_PROVIDER = "gnani"
PROVIDER_NAMES = {"sarvam": "Sarvam", "gnani": "Gnani"}

_GNANI_LANGS = frozenset({"en", "hi", "bn", "gu", "kn", "ml", "mr", "pa", "ta", "te"})
SUPPORT: dict[str, dict[str, frozenset[str]]] = {
    "sarvam": {"stt": frozenset(APP_LANGS),  # saaras:v3 transcribes all 23
               "tts": frozenset({"en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"})},
    "gnani": {"stt": _GNANI_LANGS, "tts": _GNANI_LANGS},
}

_ALIASES = {"od": "or", "ori": "or"}  # provider-style codes that callers may pass back to us


def normalize_lang(lang: str | None) -> str:
    """'hi-IN' / 'HI' / 'od' → 'hi' / 'hi' / 'or'. Unknown codes pass through (lower-cased)."""
    code = (lang or "hi").strip().lower().replace("_", "-").split("-", 1)[0]
    return _ALIASES.get(code, code)


def configured(provider: str) -> bool:
    s = get_settings()
    key = {"sarvam": s.sarvam_api_key, "gnani": s.gnani_api_key}.get(provider, "")
    return bool(key and key.strip())


def supports(provider: str, cap: str, lang: str) -> bool:
    return normalize_lang(lang) in SUPPORT.get(provider, {}).get(cap, frozenset())


def order(cap: str, lang: str, preferred: str | None = None) -> list[str]:
    """Configured providers that support `cap` in `lang`: `preferred` first, then the rest."""
    first = preferred if preferred in PROVIDERS else DEFAULT_PROVIDER
    ranked = [first] + [p for p in PROVIDERS if p != first]
    return [p for p in ranked if configured(p) and supports(p, cap, lang)]


def providers_for(cap: str, lang: str) -> list[str]:
    return order(cap, lang, DEFAULT_PROVIDER)


def content_languages() -> list[str]:
    """Languages a child can both hear and speak in, in APP_LANGS order.

    With no provider configured the app still works by typing + the phone's own voice: hi and en.
    """
    if not any(configured(p) for p in PROVIDERS):
        return ["hi", "en"]
    return [c for c in APP_LANGS if providers_for("stt", c) and providers_for("tts", c)]
