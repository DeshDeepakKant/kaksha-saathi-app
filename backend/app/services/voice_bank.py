"""Reviewed fallback item bank for the 30-minute voice session (content/voice_bank.json).

When Claude is unavailable or its items fail validation, `voice_tutor.generate_items` fills the
batch from here. Only items marked `"reviewed": true` are ever served. Picks are deterministic for a
given seed so a session (and a test) is reproducible.

Other content languages (not hi/en) have no reviewed bank. Their bank is built from the per-language
files under content/i18n/<code>/ when present: `voice_bank.json` / `voice_items.json` (same item shape,
written natively in that language, `reviewed: false`) and the reading ladder
`level_check_literacy.json` (letters, words, sentences). Because nobody reviewed them, every item
must pass the same code gate as Claude's items (`voice_schemas.item_problems`) before it is served.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

# Keys of the contract Item shape (docs/voice_session_contract.md); bank-only keys are stripped.
ITEM_KEYS = ("id", "stage", "kind", "lang", "checkpoint_id", "prompt", "display", "target", "accept",
             "required_words", "keywords", "max_record_s", "difficulty", "source", "followups")


@lru_cache
def _load(path: str) -> tuple[dict, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(i for i in data.get("items", []) if i.get("reviewed") is True)


def bank_path() -> Path:
    return Path(get_settings().content_dir) / "voice_bank.json"


def lang_dir(lang: str) -> Path:
    return Path(get_settings().content_dir) / "i18n" / lang


# Ladder level key -> (stage, kind) of the voice item it becomes.
_LADDER = {"letter": ("letter", "read_letter"), "word": ("word_read", "read_word"),
           "sentence": ("reading", "read_sentence"), "story": ("reading", "read_sentence")}
_LADDER_PROMPT_EN = {"read_letter": "{name}, read this letter.", "read_word": "{name}, read this word.",
                     "read_sentence": "{name}, read this sentence."}


def _ladder_items(lang: str, data: dict) -> list[dict]:
    """Reading-ladder levels -> raw voice items. The prompt is taken from the ladder (`prompt`,
    `ask_<lang>`) when it has one in the right script, else left empty for the engine to fill."""
    lit = ((data.get("subjects") or {}).get("literacy") if isinstance(data.get("subjects"), dict) else None) or data
    out = []
    for lv in lit.get("levels") or []:
        if not isinstance(lv, dict) or lv.get("key") not in _LADDER:
            continue
        stage, kind = _LADDER[lv["key"]]
        for n, it in enumerate(lv.get("items") or [], start=1):
            show = str((it or {}).get("show") or (it or {}).get("text") or "").strip() if isinstance(it, dict) else str(it)
            if not show:
                continue
            out.append({"id": f"lc-{lang}-{lv['key']}-{n:02d}", "stage": stage, "kind": kind, "lang": lang,
                        "checkpoint_id": lv.get("checkpoint_id"),
                        "prompt": str((it or {}).get("prompt") or lv.get("prompt") or lv.get(f"ask_{lang}") or ""),
                        "display": {"text": show}, "target": show, "accept": [], "required_words": [],
                        "keywords": [], "max_record_s": {"read_letter": 4, "read_word": 5}.get(kind, 8),
                        "difficulty": min(3, 1 + (n - 1) // 2), "grade": lv.get("grade") or 1,
                        "source": "bank", "followups": []})
    return out


@lru_cache(maxsize=32)
def _load_lang(folder_path: str, lang: str) -> tuple[dict, ...]:
    """Valid raw items for a language without a reviewed bank (see module docstring)."""
    from app.ai import voice_schemas as vs  # local import: services must not depend on app.ai at load
    folder = Path(folder_path)
    raws: list[dict] = []
    for name in ("voice_bank.json", "voice_items.json"):
        try:
            data = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("items") if isinstance(data, dict) else data
        raws += [dict(i, lang=i.get("lang") or lang) for i in items or [] if isinstance(i, dict)]
    try:
        raws += _ladder_items(lang, json.loads((folder / "level_check_literacy.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError):
        pass
    out, seen = [], set()
    for r in raws:
        if r.get("lang") != lang or r.get("rejected"):
            continue
        r = {**r, "difficulty": r.get("difficulty") or 1,  # generated files may leave these out
             "max_record_s": r.get("max_record_s") or vs.record_seconds(str(r.get("kind") or ""),
                                                                        str((r.get("display") or {}).get("text") or ""))}
        item = to_item(r)
        if not item["prompt"] and item["kind"] in _LADDER_PROMPT_EN:
            item["prompt"] = item["display"].get("text") or ""  # filled at pick time (see _fill_prompt)
        if vs.item_problems(item, lang=lang, stage=item["stage"], grade=r.get("grade") or 3):
            continue
        key = (item["kind"], vs.norm(item.get("target") or item["display"].get("text") or str(item["id"])))
        if item["id"] in seen or key in seen:
            continue
        seen |= {item["id"], key}
        out.append(r)
    return tuple(out)


def _pool(lang: str) -> tuple[dict, ...]:
    from app.services.voice_types import LANGS
    if lang in LANGS:
        return _load(str(bank_path()))
    return _load_lang(str(lang_dir(lang)), lang)


def has_items(lang: str, stage: str | None = None) -> bool:
    return any(r.get("lang") == lang and (stage is None or r.get("stage") == stage) for r in _pool(lang))


def all_items() -> list[dict]:
    """Every reviewed bank item (raw, including bank-only keys like grade/sounds/reviewed)."""
    return [copy.deepcopy(i) for i in _load(str(bank_path()))]


def to_item(raw: dict) -> dict:
    """Contract Item shape, source='bank' (followups converted too)."""
    item = {k: copy.deepcopy(raw.get(k)) for k in ITEM_KEYS}
    item["source"] = "bank"
    item["accept"] = item["accept"] or []
    item["required_words"] = item["required_words"] or []
    item["keywords"] = item["keywords"] or []
    item["followups"] = [to_item(f) for f in (raw.get("followups") or [])]
    if raw.get("kind") == "read_paragraph":
        for f in item["followups"]:
            f["context"] = (raw.get("display") or {}).get("text", "")  # for evaluate_open
    return item


def seed_for(*parts) -> int:
    """Stable seed (Python's hash() is salted per process)."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _clean_sound(s: str) -> str:
    s = str(s or "").strip()
    return s.split("→")[0].strip() if "→" in s else s


def matches_sound(raw: dict, sound: str) -> bool:
    s = _clean_sound(sound).lower()
    if not s:
        return False
    if s in [x.lower() for x in raw.get("sounds") or []]:
        return True
    disp = raw.get("display") or {}
    text = " ".join([raw.get("target") or "", disp.get("text") or "", *(disp.get("tiles") or []),
                     *(disp.get("words") or [])]).lower()
    if raw.get("lang") == "en":
        # Latin: single letters are everywhere, so only count a word that starts with the sound.
        return any(w.startswith(s) for w in text.split()) if len(s) == 1 else s in text
    return s in text


def pick(*, lang: str, stage: str, grade: int = 2, n: int = 6, weak_sounds=(), avoid=(),
         topics=(), seed: int = 0) -> list[dict]:
    """Choose `n` reviewed items for a stage: weak-sound items first, then grade-appropriate ones
    from the class topics, spread over difficulty; never anything in `avoid`. Deterministic per seed."""
    avoid_set = {str(a) for a in avoid}
    from app.ai.voice_schemas import norm  # local import: services must not depend on app.ai at load
    avoid_norm = {norm(a) for a in avoid_set}

    def avoided(raw: dict) -> bool:
        vals = [raw.get("id"), raw.get("target"), (raw.get("display") or {}).get("text")]
        return any(v and (v in avoid_set or norm(v) in avoid_norm) for v in vals)

    pool = [r for r in _pool(lang)
            if r.get("lang") == lang and r.get("stage") == stage and not avoided(r)]
    rng = random.Random(seed)
    rng.shuffle(pool)
    topic_ids = {t.get("checkpoint_id") for t in topics or () if isinstance(t, dict)}
    sounds = [s for s in (weak_sounds or ()) if _clean_sound(s)]

    def rank(r: dict) -> tuple:
        weak = any(matches_sound(r, s) for s in sounds)
        g = int(r.get("grade") or 1)
        too_hard = g > grade          # an item above the child's class comes last
        return (not weak, too_hard, r.get("checkpoint_id") not in topic_ids, abs(g - grade))

    ranked = sorted(pool, key=rank)  # stable: keeps the seeded shuffle inside each rank
    chosen = ranked[:n]
    # Gentle ramp inside the batch: easier first (the engine asks again for harder ones).
    chosen.sort(key=lambda r: r.get("difficulty", 1))
    return [_fill_prompt(to_item(r)) for r in chosen]


def _fill_prompt(item: dict) -> dict:
    """Ladder items carry no prompt: Saathi's standard ask, translated when known (else English)."""
    if not item.get("prompt") and item.get("kind") in _LADDER_PROMPT_EN:
        from app.ai import voice_tutor
        item["prompt"] = voice_tutor.local(item.get("lang") or "hi", _LADDER_PROMPT_EN[item["kind"]])
    return item
