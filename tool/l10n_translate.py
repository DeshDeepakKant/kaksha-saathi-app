#!/usr/bin/env python3
"""Machine-translate the UI strings into the 21 app languages beyond English and Hindi.

    python3 tool/l10n_strings.py extract          # first: tool/i18n/strings.json
    python3 tool/l10n_translate.py [codes...]     # all 21 when no codes are given

Needs ANTHROPIC_API_KEY in the environment (never printed). Results are cached per language in
tool/i18n/cache/<code>.json, so a re-run only asks for new or failed strings. Every translation is
checked: same {placeholders}, same ASCII digits, no native digits, same line breaks, and mostly
the language's own script. A failing string is sent back once with the reason; if it still fails
it is left out and the app shows English for it. Writes apps/<app>/assets/i18n/<code>.json with
only the keys that app uses, and tool/i18n/report.json with the counts.

Strings are machine translated and NOT reviewed by native speakers.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "tool" / "i18n"
CACHE = I18N / "cache"
MODEL = os.environ.get("L10N_MODEL", "claude-sonnet-5")
BATCH = 50
# Ol Chiki and Meetei Mayek take many tokens per letter; smaller batches stay under max_tokens.
SMALL_BATCH = {"mni": 12, "sat": 12}
WORKERS = 20
SEP = "␟"  # collision keys: English␟Hindi (see tr() in lib/l10n.dart)

DEVANAGARI = [(0x0900, 0x097F), (0xA8E0, 0xA8FF)]
ARABIC = [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]
BENGALI = [(0x0980, 0x09FF)]
# code: (English name, native name, script name, ranges)
LANGS = {
    "bn": ("Bengali", "বাংলা", "Bengali", BENGALI),
    "mr": ("Marathi", "मराठी", "Devanagari", DEVANAGARI),
    "te": ("Telugu", "తెలుగు", "Telugu", [(0x0C00, 0x0C7F)]),
    "ta": ("Tamil", "தமிழ்", "Tamil", [(0x0B80, 0x0BFF)]),
    "gu": ("Gujarati", "ગુજરાતી", "Gujarati", [(0x0A80, 0x0AFF)]),
    "kn": ("Kannada", "ಕನ್ನಡ", "Kannada", [(0x0C80, 0x0CFF)]),
    "ml": ("Malayalam", "മലയാളം", "Malayalam", [(0x0D00, 0x0D7F)]),
    "or": ("Odia", "ଓଡ଼ିଆ", "Odia", [(0x0B00, 0x0B7F)]),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "Gurmukhi", [(0x0A00, 0x0A7F)]),
    "as": ("Assamese", "অসমীয়া", "Bengali-Assamese (with ৰ and ৱ)", BENGALI),
    "ur": ("Urdu", "اردو", "Perso-Arabic (Nastaliq)", ARABIC),
    "sa": ("Sanskrit", "संस्कृतम्", "Devanagari", DEVANAGARI),
    "ne": ("Nepali", "नेपाली", "Devanagari", DEVANAGARI),
    "kok": ("Konkani", "कोंकणी", "Devanagari", DEVANAGARI),
    "mai": ("Maithili", "मैथिली", "Devanagari", DEVANAGARI),
    "doi": ("Dogri", "डोगरी", "Devanagari", DEVANAGARI),
    "sd": ("Sindhi", "سنڌي", "Perso-Arabic (Sindhi alphabet)", ARABIC),
    "ks": ("Kashmiri", "کٲشُر", "Perso-Arabic (Kashmiri alphabet)", ARABIC),
    "brx": ("Bodo", "बड़ो", "Devanagari", DEVANAGARI),
    "mni": ("Manipuri (Meitei)", "ꯃꯤꯇꯩꯂꯣꯟ", "Meetei Mayek", [(0xABC0, 0xABFF), (0xAAE0, 0xAAFF)]),
    "sat": ("Santali", "ᱥᱟᱱᱛᱟᱲᱤ", "Ol Chiki", [(0x1C50, 0x1C7F)]),
}

PLACEHOLDER = re.compile(r"\{(\w+)\}")

SYSTEM = """You translate the user interface of Kaksha Saathi, a free app for government primary-school \
teachers and parents in India (class board, group plans, learning evidence, home practice with a \
voice tutor called Saathi). Readers are busy teachers and parents, many with little schooling, on phones.

Translate each English UI string into {lang} ({native}), written in the {script} script.
Rules:
- Plain, warm, everyday words a parent in a village understands; short, because buttons are small.
  Polite imperative for buttons. Keep the register consistent across strings.
- Keep every {{placeholder}} exactly as written (same name, same braces); never translate or drop one.
  Reorder them freely to fit the grammar. Placeholders hold numbers, names or other text.
- Keep digits as ASCII 0-9 (never native numerals). Keep symbols and punctuation such as · — → … % / ( ) " \
and emoji. Keep leading/trailing spaces and line breaks (\\n) exactly.
- "Kaksha Saathi" (the app) and "Saathi" (the tutor) are names: transliterate them into the {script} \
script, do not translate. Keep WhatsApp and PIN as they are, or in the usual local spelling.
- The Hindi given with a string shows the intended meaning; when it looks wrong for a UI (for example \
'Close' meaning 'near'), follow the English and the context. A one-letter string is a weekday initial: use \
the usual one-letter abbreviation of that weekday in {lang}.
- Write the whole string in {lang}; use English words only for technical terms with no common local word.

Reply with one flat JSON object mapping each id to its translated string, like {{"0": "...", "1": "..."}}, \
and nothing else."""


def in_ranges(ch: str, ranges) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in ranges)


def check(en: str, out: str, code: str) -> str | None:
    """Reason the translation is unusable, or None."""
    if not isinstance(out, str) or not out.strip():
        return "empty"
    if sorted(PLACEHOLDER.findall(en)) != sorted(PLACEHOLDER.findall(out)):
        return f"placeholders must be exactly {sorted(set(PLACEHOLDER.findall(en)))}"
    if out.count("{") != en.count("{") or out.count("}") != en.count("}"):
        return "stray braces"
    bare_en, bare_out = PLACEHOLDER.sub("", en), PLACEHOLDER.sub("", out)
    # Names that may stay in Latin letters do not count against the script check.
    bare_en, bare_out = (re.sub(r"\b(WhatsApp|PIN|AI|OK|SMS)\b", "", x) for x in (bare_en, bare_out))
    if sorted(re.findall(r"[0-9]+", bare_en)) != sorted(re.findall(r"[0-9]+", bare_out)):
        return "digits must match the English, as ASCII 0-9"
    if any(unicodedata.category(c) == "Nd" and not c.isascii() for c in bare_out):
        return "use ASCII digits 0-9, not native numerals"
    if en.count("\n") != out.count("\n"):
        return "keep the same line breaks"
    ranges = LANGS[code][3]
    letters = [c for c in bare_out if unicodedata.category(c)[0] in "LM"]
    own = sum(1 for c in letters if in_ranges(c, ranges))
    latin_en = sum(1 for c in bare_en if c.isascii() and c.isalpha())
    if latin_en >= 4 and (own == 0 or own / max(1, len(letters)) < 0.5):
        return f"write it in the {LANGS[code][2]} script"
    if latin_en >= 1 and own == 0 and not re.fullmatch(r"[A-Z ]+", bare_en.strip()):
        return f"write it in the {LANGS[code][2]} script"
    return None


def fix_spaces(en: str, out: str) -> str:
    lead = en[: len(en) - len(en.lstrip(" "))]
    trail = en[len(en.rstrip(" ")) :]
    return lead + out.strip(" ") + trail


def call_claude(system: str, user: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 32000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = json.load(r)
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < 5:
                time.sleep(5 * 2**attempt)
                continue
            raise RuntimeError(f"API error {e.code}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < 5:
                time.sleep(5 * 2**attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def parse_json(text: str) -> dict:
    """First JSON object in the reply; several objects (one per batch slice) are merged."""
    out: dict = {}
    dec = json.JSONDecoder()
    i = text.find("{")
    while i >= 0:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            out.update(obj)
        i = text.find("{", end)
    return out


def items_for(strings: list[dict]) -> list[dict]:
    """One request item per lookup key. Collisions get one item per Hindi meaning."""
    out = []
    for s in strings:
        variants = s["hi"]
        if len(variants) == 1:
            out.append({"key": s["en"], "en": s["en"], "hi": variants[0]["text"],
                        "where": _where(variants[0]["where"])})
        else:
            for v in variants:
                out.append({"key": s["en"] + SEP + v["text"], "en": s["en"], "hi": v["text"],
                            "where": _where(v["where"])})
    return out


def _where(ws: list[str]) -> str:
    names = []
    for w in ws:
        n = w.split("/lib/")[-1].split(":")[0] if "/lib/" in w else w
        if n not in names:
            names.append(n)
    return ", ".join(names[:3])


def translate_batch(code: str, batch: list[dict], feedback: dict[str, str] | None = None) -> dict:
    name, native, script, _ = LANGS[code]
    system = SYSTEM.format(lang=name, native=native, script=script)
    payload = {}
    for i, it in enumerate(batch):
        entry = {"en": it["en"], "hi": it["hi"], "screen": it["where"]}
        if feedback and it["key"] in feedback:
            entry["previous_attempt_rejected_because"] = feedback[it["key"]]
        payload[str(i)] = entry
    text = call_claude(system, json.dumps(payload, ensure_ascii=False, indent=1))
    got = parse_json(text)
    return {it["key"]: _text(got.get(str(i)), code) for i, it in enumerate(batch)}


def _text(v, code: str):
    """The translation, also when the model wraps it as {"en": ..., "<code>": ...}."""
    if isinstance(v, dict):
        v = v.get(code) or v.get("translation") or next(
            (x for k, x in v.items() if k not in ("en", "hi", "screen") and isinstance(x, str)), None)
    return v


def _apply(code, by_key, res, cache, failed, retried):
    ok = 0
    for k, out in res.items():
        out = fix_spaces(by_key[k]["en"], out) if isinstance(out, str) else out
        why = check(by_key[k]["en"], out, code)
        if why:
            failed[k] = why
        else:
            cache[k] = {"text": out, "retried": retried}
            ok += 1
    return ok


def _pass(ex, jobs, feedback=None):
    """jobs: [(code, batch)] -> [(code, result)], all batches of all languages in parallel."""
    futs = [(code, ex.submit(translate_batch, code, batch, feedback.get(code) if feedback else None))
            for code, batch in jobs]
    out = []
    for code, f in futs:
        try:
            out.append((code, f.result()))
        except Exception as e:  # a lost batch stays untranslated; a re-run picks it up
            print(f"  {code}: batch failed: {e}", file=sys.stderr)
    return out


def _bs(code: str) -> int:
    return SMALL_BATCH.get(code, BATCH)


def run_all(codes: list[str], items: list[dict]) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    by_key = {it["key"]: it for it in items}
    caches, todo = {}, {}
    for code in codes:
        cpath = CACHE / f"{code}.json"
        caches[code] = json.loads(cpath.read_text()) if cpath.exists() else {}
        todo[code] = [it for it in items
                      if it["key"] not in caches[code] or check(it["en"], caches[code][it["key"]]["text"], code)]
    first_fail = {c: {} for c in codes}
    still = {c: {} for c in codes}
    fixed = {c: 0 for c in codes}
    with ThreadPoolExecutor(WORKERS) as ex:
        jobs = [(c, todo[c][i : i + _bs(c)]) for c in codes for i in range(0, len(todo[c]), _bs(c))]
        for code, res in _pass(ex, jobs):
            _apply(code, by_key, res, caches[code], first_fail[code], False)
        jobs = [(c, [by_key[k] for k in list(first_fail[c])[i : i + _bs(c)]])
                for c in codes for i in range(0, len(first_fail[c]), _bs(c))]
        for code, res in _pass(ex, jobs, first_fail):
            fixed[code] += _apply(code, by_key, res, caches[code], still[code], True)
    results = []
    for code in codes:
        (CACHE / f"{code}.json").write_text(json.dumps(caches[code], ensure_ascii=False, indent=1, sort_keys=True))
        ff = first_fail[code]
        results.append({"code": code, "requested": len(todo[code]), "first_pass_failures": len(ff),
                        "placeholder_failures_first_pass": sum(1 for w in ff.values() if "placeholder" in w or "braces" in w),
                        "fixed_on_retry": fixed[code],
                        "still_failing": {k: w for k, w in still[code].items()},
                        "missing": [it["key"] for it in items if it["key"] not in caches[code]]})
    return results


def write_tables(code: str, strings: list[dict], items: list[dict]) -> dict:
    cache = json.loads((CACHE / f"{code}.json").read_text())
    counts = {}
    for app in ("teacher", "parent"):
        table = {}
        total = 0
        for s in strings:
            if app not in s["apps"]:
                continue
            total += 1
            variants = s["hi"]
            if len(variants) == 1:
                if s["en"] in cache:
                    table[s["en"]] = cache[s["en"]]["text"]
                continue
            # Plain key = the most used meaning; each meaning also under English␟Hindi.
            main = max(variants, key=lambda v: len(v["where"]))
            for v in variants:
                k = s["en"] + SEP + v["text"]
                if k in cache:
                    table[k] = cache[k]["text"]
                    if v is main:
                        table[s["en"]] = cache[k]["text"]
        path = ROOT / "apps" / app / "assets" / "i18n" / f"{code}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(table.items())), ensure_ascii=False, indent=0) + "\n")
        done = sum(1 for s in strings if app in s["apps"] and s["en"] in table)
        counts[app] = {"translated": done, "total": total, "bytes": path.stat().st_size}
    return counts


def main(codes: list[str]):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")
    data = json.loads((I18N / "strings.json").read_text())
    strings = data["strings"]
    items = items_for(strings)
    codes = codes or list(LANGS)
    results = run_all(codes, items)
    rpath = I18N / "report.json"
    report = json.loads(rpath.read_text()) if rpath.exists() else {}
    for r in results:
        r["tables"] = write_tables(r["code"], strings, items)
        report[r["code"]] = r
        t = r["tables"]
        print(f"{r['code']:4s} teacher {t['teacher']['translated']}/{t['teacher']['total']}  "
              f"parent {t['parent']['translated']}/{t['parent']['total']}  "
              f"first-pass fails {r['first_pass_failures']} (placeholders {r['placeholder_failures_first_pass']}), "
              f"fixed {r['fixed_on_retry']}, untranslated keys {len(r['missing'])}")
    rpath.write_text(json.dumps(dict(sorted(report.items())), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
