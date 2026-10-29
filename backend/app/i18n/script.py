"""Script checks for the 23 languages: is a text written in the language's own script, and how does it
split into readable letters (graphemes)."""
from __future__ import annotations

import unicodedata

from app.i18n.languages import language

# Unicode blocks per script (inclusive ranges).
SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "Latin": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF)),
    "Devanagari": ((0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF)),
    "Bengali": ((0x0980, 0x09FF),),
    "Gurmukhi": ((0x0A00, 0x0A7F),),
    "Gujarati": ((0x0A80, 0x0AFF),),
    "Odia": ((0x0B00, 0x0B7F),),
    "Tamil": ((0x0B80, 0x0BFF),),
    "Telugu": ((0x0C00, 0x0C7F),),
    "Kannada": ((0x0C80, 0x0CFF),),
    "Malayalam": ((0x0D00, 0x0D7F),),
    "Arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "Meetei Mayek": ((0xABC0, 0xABFF), (0xAAE0, 0xAAFF)),
    "Ol Chiki": ((0x1C50, 0x1C7F),),
}

ZWJ, ZWNJ = "\u200d", "\u200c"
_INHERITED = ((0x0300, 0x036F), (0x1AB0, 0x1AFF), (0x20D0, 0x20FF))  # generic combining marks
_TAMIL = ((0x0B80, 0x0BFF),)  # Tamil pulli marks a dead consonant; it does not build a conjunct


def _in(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _is_letter(ch: str) -> bool:
    return unicodedata.category(ch)[0] in ("L", "M")


def foreign_letters(text: str, code: str) -> list[str]:
    """Letters (and vowel signs) in `text` that are not in the language's script.
    Digits, punctuation, symbols and spaces are ignored."""
    ranges = SCRIPT_RANGES[language(code).script]
    out = []
    for ch in text or "":
        if not _is_letter(ch):
            continue
        cp = ord(ch)
        if _in(cp, ranges) or _in(cp, _INHERITED):
            continue
        out.append(ch)
    return out


def in_script(text: str, code: str) -> bool:
    """True when every letter of `text` belongs to the language's script (`en` = Latin).
    Digits, punctuation and spaces are ignored, so "45 − 18 = ?" is in every script."""
    return not foreign_letters(text, code)


def _is_virama(ch: str) -> bool:
    return unicodedata.combining(ch) == 9 and not _in(ord(ch), _TAMIL)


def graphemes(text: str) -> list[str]:
    """Split `text` into readable letters: a base character plus its following combining marks
    (vowel signs, nukta, anusvara...), with virama-joined consonants kept together (क्ष, স্ত, ಕ್ಕ).

    Works for the Brahmic scripts (Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu,
    Kannada, Malayalam); Tamil pulli ends a letter (க்க = க் + க). For other scripts this is one
    character per item, with combining marks attached. Spaces and punctuation are their own items.
    """
    out: list[str] = []
    for ch in text or "":
        if not out:
            out.append(ch)
            continue
        prev = out[-1]
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Mc", "Me") or ch in (ZWJ, ZWNJ):
            out[-1] = prev + ch
            continue
        joined = _is_virama(prev[-1]) or (len(prev) > 1 and prev[-1] == ZWJ and _is_virama(prev[-2]))
        if joined and cat == "Lo":
            out[-1] = prev + ch
        else:
            out.append(ch)
    return out
