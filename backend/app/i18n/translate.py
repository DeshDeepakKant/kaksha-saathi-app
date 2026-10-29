"""Machine translation of short classroom texts through Claude, cached in `translation_cache`.

`translate_texts` never raises: with no key, no budget or a bad answer it returns the source text marked
`untranslated: True`, so every caller keeps working (CLAUDE.md: every AI path has a fallback). Output is
checked by code before it is accepted or cached: right script, same digits, same {placeholders}.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import llm
from app.config import get_settings
from app.i18n.languages import language, prompt_instruction
from app.i18n.script import foreign_letters
from app.models.tables import TranslationCache

PROMPT_VERSION = "translate.v1"
CHUNK_ITEMS = 40
CHUNK_CHARS = 2500

SCHEMA = {
    "type": "object",
    "properties": {"translations": {"type": "array", "items": {"type": "string"},
                                    "description": "One translation per input text, same order."}},
    "required": ["translations"],
}

SYSTEM = """You translate short texts for Kaksha Saathi, an app used by teachers and parents of grade 1-3 \
children in Indian government schools. Texts are classroom instructions, activity steps, questions for a \
child, and short notes for a teacher or parent.

Rules:
- Return exactly one translation per input text, in the same order, through the tool.
- Use simple, natural spoken language, the way a primary teacher in that region talks. No English words \
unless the target language is English.
- Write only in the target language's own script.
- Keep every number as the same ASCII digits (0-9). Keep maths symbols (+ − × ÷ = ? ₹ /) and anything in \
{curly braces} exactly as given.
- If a text quotes Hindi letters, vowel signs (matras), syllables or words as reading material for a child \
(for example "बोलो: का" or "पढ़ो: कु, कू"), replace them with letters, vowel signs, syllables or words of the \
target language that practise the same reading skill. Never leave Hindi letters in a non-Hindi translation.
- Transliterate people's names. Do not add explanations.

Classroom terms: मात्रा = a vowel sign attached to a letter (reading), never "quantity" or "price"; \
उधार = borrowing (regrouping) in subtraction; दहाई / इकाई = tens / ones; गृहभाषा = the child's home language; \
तिलियाँ / सींकें = sticks used for counting."""

_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_LATIN = re.compile(r"[A-Za-z]")


def src_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _numbers(text: str) -> list[str]:
    """Number tokens with any script's digits normalised to ASCII, sorted (order may change in translation)."""
    norm = "".join(str(unicodedata.digit(c)) if unicodedata.category(c) == "Nd" else c for c in text)
    return sorted(re.findall(r"[0-9]+", norm))


def needs_translation(text: str) -> bool:
    """False for empty text and text with no letters at all (e.g. "45 − 18 = ?")."""
    return any(unicodedata.category(c)[0] == "L" for c in text or "")


def text_problems(src: str, out: str, target: str, source: str = "hi") -> list[str]:
    """Why `out` is not an acceptable translation of `src` into `target` (empty list = fine)."""
    probs = []
    if not out.strip():
        return ["empty"]
    foreign = foreign_letters(out, target)
    # Latin labels (like "A") copied from a non-Latin source are fine; English words left untranslated are not
    if foreign and _LATIN.search(src) and language(source).script != "Latin":
        foreign = [c for c in foreign if not _LATIN.match(c)]
    if foreign:
        probs.append(f"letters outside the {language(target).script} script: {''.join(foreign[:8])!r}")
    if _numbers(src) != _numbers(out):
        probs.append(f"numbers changed: {_numbers(src)} -> {_numbers(out)}")
    if sorted(_PLACEHOLDER.findall(src)) != sorted(_PLACEHOLDER.findall(out)):
        probs.append("placeholders changed")
    return probs


def _chunks(texts: list[str]) -> list[list[str]]:
    out, cur, size = [], [], 0
    for t in texts:
        if cur and (len(cur) >= CHUNK_ITEMS or size + len(t) > CHUNK_CHARS):
            out.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += len(t)
    if cur:
        out.append(cur)
    return out


def llm_translate(db: Session, texts: list[str], target: str, source: str = "hi", *,
                  school_id: int | None = None, model: str | None = None, context: str = "",
                  max_tokens: int = 12000) -> list[str]:
    """One Claude call translating `texts` (a single chunk). Raises on any failure or invalid output."""
    src_lang = language(source)
    payload = {
        "source_language": f"{src_lang.name_en} ({src_lang.script} script)",
        "target_language": prompt_instruction(target),
        "context": context or "Short texts from a primary-school learning app.",
        "texts": texts,
    }

    def _validate(d: dict) -> dict:
        tr = d.get("translations")
        if not isinstance(tr, list) or len(tr) != len(texts) or not all(isinstance(x, str) for x in tr):
            raise ValueError(f"need exactly {len(texts)} string translations, got "
                             f"{len(tr) if isinstance(tr, list) else type(tr).__name__}")
        bad = []
        for i, (s, o) in enumerate(zip(texts, tr)):
            p = text_problems(s, o, target, source)
            if p:
                bad.append(f"#{i}: {'; '.join(p)}")
        if bad:
            raise ValueError("fix these items and return the full list again: " + " | ".join(bad[:12]))
        return d

    res = llm.structured(db, feature="translate", prompt_version=PROMPT_VERSION,
                         model=model or get_settings().model_extract, system=SYSTEM,
                         user=json.dumps(payload, ensure_ascii=False), schema=SCHEMA,
                         tool_name="return_translations", max_tokens=max_tokens, school_id=school_id,
                         validate=_validate)
    return [t.strip() for t in res.data["translations"]]


def _cached(db: Session, source: str, target: str, hashes: set[str]) -> dict[str, str]:
    if not hashes:
        return {}
    rows = db.scalars(select(TranslationCache).where(
        TranslationCache.src_lang == source, TranslationCache.tgt_lang == target,
        TranslationCache.src_hash.in_(hashes)))
    return {r.src_hash: r.text for r in rows}


def _store(db: Session, source: str, target: str, pairs: list[tuple[str, str]]) -> None:
    for src, text in pairs:
        try:
            with db.begin_nested():
                db.add(TranslationCache(src_lang=source, tgt_lang=target, src_hash=src_hash(src),
                                        src=src, text=text))
        except IntegrityError:  # another request cached it first
            pass


def translate_texts(db: Session, texts: list[str], target: str, source: str = "hi",
                    school_id: int | None = None, *, model: str | None = None,
                    context: str = "") -> list[dict]:
    """Translate `texts` into `target`. Each result: `{text, machine_translated}`, plus
    `untranslated: True` when the source text had to be returned instead. Never raises.

    Identity when target == source; texts without letters (numbers, sums) are returned as they are.
    Cached by (source, target, sha256(text)); new translations are added to the caller's session
    (the request commits them, like `ai_calls`).
    """
    texts = [t if isinstance(t, str) else str(t) for t in (texts or [])]

    def same(t: str) -> dict:
        return {"text": t, "machine_translated": False}

    def untranslated(t: str) -> dict:
        return {"text": t, "machine_translated": False, "untranslated": True}

    if target == source:
        return [same(t) for t in texts]
    try:
        language(target), language(source)
    except KeyError:
        return [untranslated(t) if needs_translation(t) else same(t) for t in texts]

    done: dict[str, str] = {}
    try:
        wanted = {t for t in texts if needs_translation(t)}
        by_hash = _cached(db, source, target, {src_hash(t) for t in wanted})
        done = {t: by_hash[src_hash(t)] for t in wanted if src_hash(t) in by_hash}
        pending = [t for t in dict.fromkeys(texts) if t in wanted and t not in done]
        for chunk in _chunks(pending):
            try:
                out = llm_translate(db, chunk, target, source, school_id=school_id, model=model,
                                    context=context)
            except Exception:
                continue  # this chunk stays untranslated; later chunks may still work
            pairs = list(zip(chunk, out))
            done.update(pairs)
            _store(db, source, target, pairs)
        db.flush()
    except Exception:  # cache/DB trouble: keep whatever was translated, never fail the caller
        pass

    result = []
    for t in texts:
        if not needs_translation(t):
            result.append(same(t))
        elif t in done:
            result.append({"text": done[t], "machine_translated": True})
        else:
            result.append(untranslated(t))
    return result
