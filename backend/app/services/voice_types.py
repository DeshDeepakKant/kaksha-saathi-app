"""Shared vocabulary for the 30-minute voice learning session (see docs/voice_session_contract.md).

Every module of the feature imports its constants and shapes from here so the parts built in
parallel (session engine, AI tutor, assessment, report, apps) agree on one contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

TARGET_MINUTES = 30
MAX_ATTEMPTS = 5          # tries per item before moving on and recording the difficulty
LANGS = ("hi", "en")        # languages with a reviewed item bank and hand-written Saathi lines
# Every content language a session can run in (docs/lang_provider_contract.md): hi/en as above;
# the others get per-language ladder/voice files or Claude-written items, and translated lines.
VOICE_LANGS = ("en", "hi", "bn", "mr", "te", "ta", "gu", "kn", "ml", "or", "pa")


def voice_lang(lang: str | None) -> str:
    """A language the session supports (unknown codes fall back to Hindi, as before)."""
    return lang if lang in VOICE_LANGS else "hi"


def is_reviewed_lang(lang: str | None) -> bool:
    return lang in LANGS


def is_home_lang(lang: str | None) -> bool:
    """The child's own (classroom) language: every language except English, which is taught as a
    second language. Home-language sessions practise the built-in literacy checkpoints."""
    return lang != "en"

# The reading ladder, easiest first (the order the session climbs).
STAGES = ("letter", "word_build", "word_read", "sentence_build", "reading")

# What a child does in each kind of item.
KINDS = (
    "read_letter",      # letter: read the letter shown / say its sound
    "say_sound",        # letter: say the first sound of a spoken word ("क से क्या?")
    "build_word",       # word_build: blend the tiles shown into one word and say it
    "read_word",        # word_read: read the word shown
    "make_sentence",    # sentence_build: say a sentence using the words shown
    "read_sentence",    # reading: read a short sentence
    "read_paragraph",   # reading: read a short paragraph aloud
    "answer_question",  # reading: answer a question about the paragraph just read
)

# Built-in literacy checkpoints each stage practises (Hindi track). Teacher topics are added on top.
STAGE_CHECKPOINTS: dict[str, tuple[str, ...]] = {
    "letter": ("L.G1.phonological", "L.G1.swar", "L.G1.vyanjan"),
    "word_build": ("L.G1.blend_no_matra", "L.G1.matra_basic", "L.G2.word_formation", "L.G2.conjuncts"),
    "word_read": ("L.G1.read_matra_words", "L.G2.all_matras", "L.G2.conjuncts"),
    "sentence_build": ("L.G3.sentence_formation", "L.G1.oral_vocab"),
    "reading": ("L.G1.read_short_sentences", "L.G2.fluency_45_60", "L.G3.fluency_60",
                "L.G2.comprehension_literal", "L.G3.comprehension_inferential"),
}

# The same ladder for English, taught as a second language (docs/english_subject_contract.md):
# practised through the built-in `english` subject, so English answers land on `E.*` checkpoints.
STAGE_CHECKPOINTS_EN: dict[str, tuple[str, ...]] = {
    "letter": ("E.G1.letter_names", "E.G1.letter_sounds"),
    "word_build": ("E.G1.build_cvc", "E.G2.spell_words"),
    "word_read": ("E.G1.read_cvc", "E.G2.blends_digraphs"),
    "sentence_build": ("E.G2.make_sentence", "E.G3.sentence_formation"),
    "reading": ("E.G1.read_short_sent", "E.G2.read_sentences", "E.G3.read_passage"),
}
# Item kind -> English checkpoint when the item does not name one (a say_sound item is a letter sound).
KIND_CHECKPOINT_EN: dict[str, str] = {
    "read_letter": "E.G1.letter_names", "say_sound": "E.G1.letter_sounds", "build_word": "E.G1.build_cvc",
    "read_word": "E.G1.read_cvc", "make_sentence": "E.G2.make_sentence",
    "read_sentence": "E.G1.read_short_sent", "read_paragraph": "E.G2.read_sentences",
}


def stage_checkpoints(lang: str | None, stage: str) -> tuple[str, ...]:
    """The built-in checkpoints a stage practises: `E.*` for English sessions, `L.*` (Hindi track) otherwise."""
    table = STAGE_CHECKPOINTS if is_home_lang(lang) else STAGE_CHECKPOINTS_EN
    return table.get(stage, ())


VERDICTS = ("correct", "close", "wrong", "silent")


@dataclass
class Assessment:
    """Deterministic judgement of one spoken answer (app/speech/assess.py)."""
    verdict: str                                     # one of VERDICTS
    score: float                                     # 0..1
    heard: str                                       # cleaned transcript
    words: list[dict] = field(default_factory=list)  # [{target, heard, status: correct|close|wrong|missed|extra}]
    errors: list[dict] = field(default_factory=list) # [{type, target, heard, word}] type: substitution|omission|insertion|matra|order|missing_word|meaning
    fluency: dict | None = None                      # {"wcpm": float, "duration_s": float} for read_paragraph
    notes: str = ""
    judged_by: str = "code"                          # "code" | "ai" (open answers refined by Claude)

    def to_dict(self) -> dict:
        return asdict(self)
