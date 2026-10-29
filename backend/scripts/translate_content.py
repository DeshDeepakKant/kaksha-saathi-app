"""Pre-translate the content library into the non-Hindi content languages.

Writes content/i18n/<code>/:
  activities.json            title / materials / steps / blackboard / reassessment_ask   (from Hindi)
  probes.json                title / tell / pass_rule / items                            (from Hindi)
  checkpoint_titles.json     every checkpoint title                                      (from title_en)
  level_check_asks.json      level-check titles and teacher instructions                 (from *_en)
  level_check_literacy.json  a reading ladder written natively in the language (not translated)

Everything is labelled machine_translated: true, reviewed: false. Every string is checked by code
(target script, same digits, same counts as the source) before it is written; `--check` re-runs those
checks on the files already on disk. Translations are cached per language in --cache-dir, so a rerun
only pays for what changed.

Run from backend/:  .venv/bin/python scripts/translate_content.py [--langs mr ta] [--check]
Needs ANTHROPIC_API_KEY in the environment (never printed).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.ai import llm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.i18n import translate as tr  # noqa: E402
from app.i18n.languages import language, prompt_instruction  # noqa: E402
from app.i18n.script import foreign_letters, graphemes, in_script  # noqa: E402
from app.models.tables import AiCall  # noqa: E402

TARGETS = ("en", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te")
CONTENT = get_settings().content_dir
OUT = CONTENT / "i18n"
LADDER_VERSION = "ladder.v1"
_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


def load(name: str) -> dict:
    with (CONTENT / name).open(encoding="utf-8") as f:
        return json.load(f)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def header(lang: str, source_lang: str, model: str) -> dict:
    return {"lang": lang, "source_lang": source_lang, "machine_translated": True, "reviewed": False,
            "model": model, "generated_at": now(),
            "note": "Machine translated by scripts/translate_content.py; not reviewed by an educator."}


def write(lang: str, name: str, data: dict) -> None:
    d = OUT / lang
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ translation with cache + split-retry
class Translator:
    def __init__(self, lang: str, cache_dir: Path, model: str):
        self.lang, self.model = lang, model
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{cache_dir / f'ks_i18n_{lang}.db'}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.failed: list[str] = []

    def translate(self, texts: list[str], source: str, context: str) -> dict[str, str]:
        """Map source text -> translation for every text that needs one (cached or new)."""
        if self.lang == source:
            return {t: t for t in texts}
        wanted = [t for t in dict.fromkeys(texts) if tr.needs_translation(t)]
        hashes = {tr.src_hash(t): t for t in wanted}
        done = {hashes[h]: v for h, v in tr._cached(self.db, source, self.lang, set(hashes)).items()}
        pending = [t for t in wanted if t not in done]
        for chunk in tr._chunks(pending):
            done.update(self._chunk(chunk, source, context))
        for t in texts:  # no letters (sums, numbers): unchanged
            if not tr.needs_translation(t):
                done[t] = t
        return done

    def _chunk(self, chunk: list[str], source: str, context: str) -> dict[str, str]:
        try:
            out = tr.llm_translate(self.db, chunk, self.lang, source, model=self.model, context=context,
                                   max_tokens=14000)
        except Exception as e:
            self.db.commit()  # keep the ai_calls rows for the cost report
            if len(chunk) == 1:
                log(f"  [{self.lang}] FAILED {chunk[0][:60]!r}: {type(e).__name__}: {str(e)[:160]}")
                self.failed.append(chunk[0])
                return {}
            mid = len(chunk) // 2
            log(f"  [{self.lang}] chunk of {len(chunk)} failed ({type(e).__name__}); splitting")
            return {**self._chunk(chunk[:mid], source, context), **self._chunk(chunk[mid:], source, context)}
        pairs = list(zip(chunk, out))
        tr._store(self.db, source, self.lang, pairs)
        self.db.commit()
        return dict(pairs)

    def usage(self) -> tuple[int, int, int]:
        row = self.db.execute(select(func.count(), func.coalesce(func.sum(AiCall.input_tokens), 0),
                                     func.coalesce(func.sum(AiCall.output_tokens), 0))).one()
        return int(row[0]), int(row[1]), int(row[2])


# ------------------------------------------------------------------ per-file builders
# The built-in English subject is what the children learn: its activities (`language: "en"`), probes and level
# check are never translated, and its lesson titles fall back to `title_en` (app/i18n/library.py).
def english_nodes() -> set[str]:
    return {n["id"] for n in load("competency_graph.json")["nodes"] if n.get("subject") == "english"}


def build_activities(t: Translator) -> dict:
    acts = [a for a in load("activities.json")["activities"] if a.get("language") != "en"]
    texts = []
    for a in acts:
        texts += [a["title_hi"], a.get("materials_hi", ""), a.get("blackboard_hi", ""),
                  (a.get("reassessment") or {}).get("ask_hi", "")] + list(a["steps_hi"])
    m = t.translate([x for x in texts if x], "hi",
                    "Small-group activities a grade 1-3 teacher runs (title, materials, numbered steps, "
                    "what to write on the blackboard, one check question).")
    out = {}
    for a in acts:
        def g(s):
            return m.get(s) if s else ""
        entry = {"title": g(a["title_hi"]), "materials": g(a.get("materials_hi", "")),
                 "steps": [g(s) for s in a["steps_hi"]], "blackboard": g(a.get("blackboard_hi", "")),
                 "reassessment_ask": g((a.get("reassessment") or {}).get("ask_hi", "")),
                 "machine_translated": True}
        if any(v is None for v in entry.values()) or any(s is None for s in entry["steps"]):
            continue  # a failed string: leave the whole activity out; library falls back to Hindi
        out[a["id"]] = entry
    return {**header(t.lang, "hi", t.model), "activities": out}


def build_probes(t: Translator) -> dict:
    skip = english_nodes()
    probes = [p for p in load("probes.json")["probes"] if p["checkpoint_id"] not in skip]
    texts = []
    for p in probes:
        texts += [p["title_hi"], p.get("tell_hi", ""), p.get("pass_rule", "")]
        texts += [it.get("ask_hi", "") for it in p["items"]]
    m = t.translate([x for x in texts if x], "hi",
                    "A teacher's quick oral check with one child: title, questions to ask the child, the pass "
                    "rule, and what the result tells the teacher.")
    out = {}
    for p in probes:
        def g(s):
            return m.get(s) if s else ""
        entry = {"title": g(p["title_hi"]), "tell": g(p.get("tell_hi", "")), "pass_rule": g(p.get("pass_rule", "")),
                 "items": [g(it.get("ask_hi", "")) for it in p["items"]], "machine_translated": True}
        if any(v is None for v in entry.values()) or any(s is None for s in entry["items"]):
            continue
        out[p["checkpoint_id"]] = entry
    return {**header(t.lang, "hi", t.model), "probes": out}


def build_titles(t: Translator) -> dict:
    nodes = [n for n in load("competency_graph.json")["nodes"] if n.get("subject") != "english"]
    m = t.translate([n["title_en"] for n in nodes], "en",
                    "Names of learning checkpoints (skills) in a grade 1-3 maths and reading map, shown as short "
                    "labels. Reading skills about Hindi letters/matras may be named generally (letters, vowel "
                    "signs) in the target language.")
    titles = {n["id"]: m[n["title_en"]] for n in nodes if m.get(n["title_en"])}
    return {**header(t.lang, "en", t.model), "machine_translated": t.lang != "en", "titles": titles}


def _level_sources(lang: str) -> dict:
    """{subject: {"title": en, "beginner": en, "levels": {key: {"title": en, "ask": en}}}} in English."""
    subjects = load("level_check.json")["subjects"]
    out = {}
    for name, s in subjects.items():
        if name == "english":
            continue
        title = f"{language(lang).name_en} reading level" if name == "literacy" else s["title_en"]
        out[name] = {"title": title, "beginner": s["beginner"]["title_en"],
                     "levels": {lv["key"]: {"title": lv["title_en"], "ask": lv["ask_en"]} for lv in s["levels"]}}
    return out


def build_asks(t: Translator) -> dict:
    src = _level_sources(t.lang)
    texts = []
    for s in src.values():
        texts += [s["title"], s["beginner"]] + [x for lv in s["levels"].values() for x in lv.values()]
    m = t.translate(texts, "en", "A one-to-one reading/maths level check: level names and the instruction "
                                 "the teacher follows at each level.")
    out = {}
    for name, s in src.items():
        out[name] = {"title": m.get(s["title"]), "beginner": m.get(s["beginner"]),
                     "levels": {k: {"title": m.get(lv["title"]), "ask": m.get(lv["ask"])}
                                for k, lv in s["levels"].items()}}
    return {**header(t.lang, "en", t.model), "machine_translated": t.lang != "en", "subjects": out}


# ------------------------------------------------------------------ native reading ladder
LADDER_COUNTS = {"letters": 10, "words": 10, "sentences": 6, "story": 3, "story_practice": 3}
LADDER_SCHEMA = {
    "type": "object",
    "properties": {
        "letters": {"type": "array", "items": {"type": "string"}, "description": "10 single letters"},
        "words": {"type": "array", "items": {"type": "string"}, "description": "10 simple words"},
        "sentences": {"type": "array", "items": {"type": "string"}, "description": "6 short sentences"},
        "story": {"type": "array", "items": {"type": "string"}, "description": "3 lines of one tiny story"},
        "story_practice": {"type": "array", "items": {"type": "string"},
                           "description": "3 lines of a second tiny story"},
        "level_titles": {"type": "object", "properties": {k: {"type": "string"} for k in
                                                          ("letter", "word", "sentence", "story", "beginner")},
                         "required": ["letter", "word", "sentence", "story", "beginner"]},
    },
    "required": list(LADDER_COUNTS) + ["level_titles"],
}
LADDER_SYSTEM = """You write early-reading assessment material for grade 1-2 children in Indian government \
schools, natively in the requested language (not translated from Hindi), in the style of ASER / TaRL \
reading tests.

Write, all in the language's own script:
- letters: 10 different common single letters children learn first (consonants first; for alphabetic \
scripts lowercase letters). One letter per item, no vowel signs attached.
- words: 10 different very common 2-3 syllable words a 6-year-old knows (home, food, animals, family), \
mostly with the simplest vowel signs. One word per item, no spaces.
- sentences: 6 simple sentences of 3-5 words about everyday village or home life, ending with the \
language's normal full stop.
- story: 3 lines that together make one tiny story; each line one sentence of 6-10 words.
- story_practice: 3 lines of a different tiny story, same length.
- level_titles: short names for the levels: letter ("Letters"), word ("Words"), sentence ("Sentences"), \
story ("Short passage"), beginner ("Beginner (not yet letters)"), in the language.
No digits, no English words (unless the language is English), no names of real people, nothing scary."""


def ladder_problems(d: dict, lang: str) -> list[str]:
    probs = []
    for k, n in LADDER_COUNTS.items():
        v = d.get(k)
        if not isinstance(v, list) or len(v) != n or not all(isinstance(x, str) and x.strip() for x in v):
            probs.append(f"{k}: need exactly {n} non-empty strings")
            continue
        if len(set(v)) != len(v):
            probs.append(f"{k}: items must all be different")
        for x in v:
            if not in_script(x, lang):
                probs.append(f"{k}: {x!r} has letters outside the script: {''.join(foreign_letters(x, lang)[:6])!r}")
            if any(ch.isdigit() for ch in x):
                probs.append(f"{k}: {x!r} has digits")
    if not probs:
        for x in d["letters"]:
            if len([g for g in graphemes(x.strip()) if not g.isspace()]) != 1:
                probs.append(f"letters: {x!r} is not one letter")
        for x in d["words"]:
            if " " in x.strip():
                probs.append(f"words: {x!r} has a space")
        for x in d["sentences"]:
            if not 2 <= len(x.split()) <= 7:
                probs.append(f"sentences: {x!r} should be 3-5 words")
        for x in d["story"] + d["story_practice"]:
            if not 3 <= len(x.split()) <= 14:
                probs.append(f"story: {x!r} should be 6-10 words")
    titles = d.get("level_titles") or {}
    for k in ("letter", "word", "sentence", "story", "beginner"):
        if not isinstance(titles.get(k), str) or not titles[k].strip() or not in_script(titles[k], lang):
            probs.append(f"level_titles.{k}: missing or not in the script")
    return probs


def build_ladder(t: Translator, asks: dict) -> dict | None:
    lang = language(t.lang)

    def _validate(d):
        p = ladder_problems(d, t.lang)
        if p:
            raise ValueError("; ".join(p[:12]))
        return d

    user = json.dumps({"language": prompt_instruction(t.lang),
                       "for_reference_only_hindi_ladder_shape": {
                           "letters": ["क", "म", "ल", "र", "स"], "words": ["माला", "दाल", "नाक", "बादल", "गाजर"],
                           "sentences": ["गाय घास खाती है।", "माँ रोटी बना रही है।"],
                           "story": ["गर्मी की छुट्टियों में हम नानी के गाँव जाते हैं।"]}}, ensure_ascii=False)
    data = None
    for attempt in range(2):
        try:
            res = llm.structured(t.db, feature="ladder", prompt_version=LADDER_VERSION, model=t.model,
                                 system=LADDER_SYSTEM, user=user, schema=LADDER_SCHEMA, tool_name="return_ladder",
                                 max_tokens=6000, validate=_validate)
            data = res.data
            break
        except Exception as e:
            log(f"  [{t.lang}] ladder attempt {attempt + 1} failed: {type(e).__name__}: {str(e)[:200]}")
        finally:
            t.db.commit()
    if data is None:
        return None
    hindi = load("level_check.json")["subjects"]["literacy"]
    lit_asks = (asks.get("subjects") or {}).get("literacy") or {}
    picks = {"letter": ("letters", None), "word": ("words", None), "sentence": ("sentences", None),
             "story": ("story", "story_practice")}
    levels = []
    for lv in hindi["levels"]:
        key = lv["key"]
        field, extra = picks[key]
        n = lv["of"]
        pool = [x.strip() for x in data[field]]
        items = pool[:n]
        practice = pool[n:] + ([x.strip() for x in data[extra]] if extra else [])
        levels.append({
            "key": key, "title_en": lv["title_en"], "title": data["level_titles"][key].strip(),
            "checkpoint_id": lv["checkpoint_id"], "ask_en": lv["ask_en"],
            "ask": ((lit_asks.get("levels") or {}).get(key) or {}).get("ask") or lv["ask_en"],
            "items": [{"show": x} for x in items], "pass_min": lv["pass_min"], "of": n,
            "practice": [{"show": x} for x in practice],
        })
    return {**header(t.lang, t.lang, t.model), "generated_natively": True,
            "title_en": f"{lang.name_en} reading level",
            "title": lit_asks.get("title") or f"{lang.name_en} reading level",
            "beginner": {"key": "beginner", "title_en": hindi["beginner"]["title_en"],
                         "title": data["level_titles"]["beginner"].strip()},
            "levels": levels}


# ------------------------------------------------------------------ checks on files on disk
def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, list):
        for x in o:
            yield from _strings(x)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k not in ("lang", "source_lang", "model", "generated_at", "note", "key", "checkpoint_id",
                         "title_en", "ask_en"):
                yield from _strings(v)


def check_lang(lang: str) -> list[str]:
    """Problems with content/i18n/<lang>/*: missing entries, counts, script, digits."""
    probs = []
    d = OUT / lang

    def get(name):
        p = d / name
        if not p.exists():
            probs.append(f"{name}: missing")
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    skip = english_nodes()
    acts = [a for a in load("activities.json")["activities"] if a.get("language") != "en"]
    probes = [p for p in load("probes.json")["probes"] if p["checkpoint_id"] not in skip]
    a = get("activities.json")
    if a:
        for src in acts:
            e = a["activities"].get(src["id"])
            if e is None:
                probs.append(f"activities: {src['id']} missing")
                continue
            if len(e["steps"]) != len(src["steps_hi"]):
                probs.append(f"activities: {src['id']} step count {len(e['steps'])} != {len(src['steps_hi'])}")
            pairs = [(src["title_hi"], e["title"]), (src.get("materials_hi", ""), e["materials"]),
                     (src.get("blackboard_hi", ""), e["blackboard"]),
                     ((src.get("reassessment") or {}).get("ask_hi", ""), e["reassessment_ask"])]
            pairs += list(zip(src["steps_hi"], e["steps"]))
            for s, o in pairs:
                if s and tr.needs_translation(s):
                    probs += [f"activities: {src['id']}: {p}" for p in tr.text_problems(s, o, lang)]
    p = get("probes.json")
    if p:
        for src in probes:
            e = p["probes"].get(src["checkpoint_id"])
            if e is None:
                probs.append(f"probes: {src['checkpoint_id']} missing")
                continue
            if len(e["items"]) != len(src["items"]):
                probs.append(f"probes: {src['checkpoint_id']} item count differs")
            pairs = [(src["title_hi"], e["title"]), (src.get("tell_hi", ""), e["tell"]),
                     (src.get("pass_rule", ""), e["pass_rule"])]
            pairs += list(zip([it.get("ask_hi", "") for it in src["items"]], e["items"]))
            for s, o in pairs:
                if s and tr.needs_translation(s):
                    probs += [f"probes: {src['checkpoint_id']}: {x}" for x in tr.text_problems(s, o, lang)]
    t = get("checkpoint_titles.json")
    if t:
        nodes = load("competency_graph.json")["nodes"]
        missing = [n["id"] for n in nodes if n["id"] not in t["titles"] and n["id"] not in skip]
        if missing:
            probs.append(f"checkpoint_titles: {len(missing)} missing")
        probs += [f"checkpoint_titles: {k}: not in script" for k, v in t["titles"].items() if not in_script(v, lang)]
    k = get("level_check_asks.json")
    if k:
        src = _level_sources(lang)
        for name, s in src.items():
            node = k["subjects"].get(name) or {}
            if set((node.get("levels") or {})) != set(s["levels"]):
                probs.append(f"level_check_asks: {name} levels differ")
        probs += [f"level_check_asks: not in script: {x!r}" for x in _strings(k["subjects"])
                  if x and not in_script(x, lang)]
    lad = get("level_check_literacy.json")
    if lad:
        hindi = load("level_check.json")["subjects"]["literacy"]["levels"]
        if [lv["key"] for lv in lad["levels"]] != [lv["key"] for lv in hindi]:
            probs.append("level_check_literacy: level keys differ from content/level_check.json")
        for lv, hv in zip(lad["levels"], hindi):
            if len(lv["items"]) != hv["of"] or lv["of"] != hv["of"] or lv["pass_min"] != hv["pass_min"]:
                probs.append(f"level_check_literacy: {lv['key']} counts differ")
        probs += [f"level_check_literacy: not in script: {x!r}" for x in _strings(
            {"t": lad["title"], "b": lad["beginner"]["title"], "l": lad["levels"]})
            if x and not in_script(x, lang)]
    return probs


# ------------------------------------------------------------------ main
def run_lang(lang: str, cache_dir: Path, model: str, parts: set[str]) -> dict:
    t = Translator(lang, cache_dir, model)
    log(f"[{lang}] start")
    asks = None
    if "activities" in parts:
        write(lang, "activities.json", build_activities(t))
        log(f"[{lang}] activities done")
    if "probes" in parts:
        write(lang, "probes.json", build_probes(t))
        log(f"[{lang}] probes done")
    if "titles" in parts:
        write(lang, "checkpoint_titles.json", build_titles(t))
        log(f"[{lang}] checkpoint titles done")
    if "asks" in parts or "ladder" in parts:
        asks = build_asks(t)
        write(lang, "level_check_asks.json", asks)
        log(f"[{lang}] level-check asks done")
    if "ladder" in parts:
        lad = build_ladder(t, asks)
        if lad is not None:
            write(lang, "level_check_literacy.json", lad)
            log(f"[{lang}] literacy ladder done")
    calls, tin, tout = t.usage()
    return {"lang": lang, "failed": t.failed, "calls": calls, "in": tin, "out": tout}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--langs", nargs="*", default=list(TARGETS))
    ap.add_argument("--parts", default="activities,probes,titles,asks,ladder")
    ap.add_argument("--cache-dir", type=Path, default=Path("/tmp/ks_i18n_cache"))
    ap.add_argument("--model", default=None, help="default: config model_plan")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--check", action="store_true", help="only check the files on disk")
    args = ap.parse_args()
    bad = [c for c in args.langs if c not in TARGETS]
    if bad:
        ap.error(f"not a pre-translated content language: {bad} (choose from {TARGETS})")

    if not args.check:
        if not get_settings().anthropic_api_key:
            print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        model = args.model or get_settings().model_plan
        parts = set(args.parts.split(","))
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda c: run_lang(c, args.cache_dir, model, parts), args.langs))
        tin = sum(r["in"] for r in results)
        tout = sum(r["out"] for r in results)
        print("\nusage (all runs, from the per-language cache DBs):")
        for r in results:
            print(f"  {r['lang']}: calls={r['calls']} in={r['in']} out={r['out']} failed_strings={len(r['failed'])}")
        print(f"  total in={tin} out={tout}")

    status = 0
    print("\nchecks:")
    for c in args.langs:
        probs = check_lang(c)
        print(f"  {c}: {'OK' if not probs else f'{len(probs)} problem(s)'}")
        for p in probs[:20]:
            print(f"     - {p}")
        status |= bool(probs)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
