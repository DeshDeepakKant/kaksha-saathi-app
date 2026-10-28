"""Reviewed fallback item bank for the 30-minute voice session (content/voice_bank.json).

When Claude is unavailable or its items fail validation, `voice_tutor.generate_items` fills the
batch from here. Only items marked `"reviewed": true` are ever served. Picks are deterministic for a
given seed so a session (and a test) is reproducible.
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

    pool = [r for r in _load(str(bank_path()))
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
    return [to_item(r) for r in chosen]
