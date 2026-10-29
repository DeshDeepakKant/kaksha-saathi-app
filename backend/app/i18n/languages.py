"""The 23 languages the apps know about (ISO 639 codes; Odia is `or` internally)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name_en: str
    name_native: str
    script: str
    rtl: bool


APP_LANGS: tuple[str, ...] = ("en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "ml", "or", "pa", "as", "ur",
                              "sa", "ne", "kok", "mai", "doi", "sd", "ks", "brx", "mni", "sat")

# Languages whose app strings and voices are thin; the pickers label them "beta".
BETA_LANGS = frozenset({"brx", "doi", "ks", "kok", "mai", "mni", "sa", "sat", "sd"})

_ROWS = (
    ("en", "English", "English", "Latin", False),
    ("hi", "Hindi", "हिन्दी", "Devanagari", False),
    ("bn", "Bengali", "বাংলা", "Bengali", False),
    ("mr", "Marathi", "मराठी", "Devanagari", False),
    ("te", "Telugu", "తెలుగు", "Telugu", False),
    ("ta", "Tamil", "தமிழ்", "Tamil", False),
    ("gu", "Gujarati", "ગુજરાતી", "Gujarati", False),
    ("kn", "Kannada", "ಕನ್ನಡ", "Kannada", False),
    ("ml", "Malayalam", "മലയാളം", "Malayalam", False),
    ("or", "Odia", "ଓଡ଼ିଆ", "Odia", False),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi", False),
    ("as", "Assamese", "অসমীয়া", "Bengali", False),
    ("ur", "Urdu", "اردو", "Arabic", True),
    ("sa", "Sanskrit", "संस्कृतम्", "Devanagari", False),
    ("ne", "Nepali", "नेपाली", "Devanagari", False),
    ("kok", "Konkani", "कोंकणी", "Devanagari", False),
    ("mai", "Maithili", "मैथिली", "Devanagari", False),
    ("doi", "Dogri", "डोगरी", "Devanagari", False),
    ("sd", "Sindhi", "سنڌي", "Arabic", True),
    ("ks", "Kashmiri", "کٲشُر", "Arabic", True),
    ("brx", "Bodo", "बड़ो", "Devanagari", False),
    ("mni", "Manipuri", "ꯃꯤꯇꯩꯂꯣꯟ", "Meetei Mayek", False),
    ("sat", "Santali", "ᱥᱟᱱᱛᱟᱲᱤ", "Ol Chiki", False),
)

LANGUAGES: dict[str, Language] = {r[0]: Language(*r) for r in _ROWS}
assert tuple(LANGUAGES) == APP_LANGS


def language(code: str) -> Language:
    """The language for an ISO code. KeyError for an unknown code."""
    return LANGUAGES[code]


def prompt_instruction(code: str) -> str:
    """One line for a prompt telling Claude which language and script to write in."""
    lang = language(code)
    native = "" if lang.name_native == lang.name_en else f"{lang.name_native}, "
    return (f"Write every learner-facing and classroom text in {lang.name_en} "
            f"({native}{lang.script} script). Keep numerals as digits.")
