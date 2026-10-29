#!/usr/bin/env python3
"""Find every tr()/trf() call in both Flutter apps; rewrite interpolated tr() to trf(); extract keys.

    python3 tool/l10n_strings.py rewrite    # tr('Hi $name', 'नमस्ते $name') -> trf('Hi {name}', 'नमस्ते {name}', {'name': name})
    python3 tool/l10n_strings.py extract    # writes tool/i18n/strings.json (keys = English text as passed at runtime)

The lookup key at runtime is the first argument of tr()/trf(), so an interpolated English string can
never match a table; `rewrite` turns those into placeholder templates. Only the call expression
changes (tr -> trf, `$x` -> `{x}`, an args map appended), so merges with other edits stay easy.
Files owned by other engineers (settings screens, tts.dart, api.dart) are never rewritten.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ("teacher", "parent")
# Not ours to edit (Flutter-Settings owns them). Their interpolated tr() calls stay English-only.
NO_REWRITE = ("screens/settings_screen.dart", "lib/tts.dart", "lib/api.dart", "lib/l10n.dart")
OUT = ROOT / "tool" / "i18n" / "strings.json"

# Strings passed to tr() through variables (month/day name arrays), not as literals.
_MONTHS = ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "जन फ़र मार्च अप्रै मई जून जुला अग सित अक्टू नव दिस".split(),
           "जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर".split())
EXTRA_KEYS = (
    [(en, hi, "short month name in a date like '12 Oct'") for en, hi in zip(_MONTHS[0], _MONTHS[1])]
    + [(en, hi, "month name in a date like '12 Oct'") for en, hi in zip(_MONTHS[0], _MONTHS[2])]
    + [(en, hi, f"one-letter weekday initial ({day}) above a practice-day dot")
       for en, hi, day in zip("M T W T F S S".split(), "सो मं बु गु शु श र".split(),
                              "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split())]
)

IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


@dataclass
class Interp:
    start: int  # span of `$x` / `${...}` in the source
    end: int
    expr: str


@dataclass
class Lit:
    start: int
    end: int
    raw: bool
    value_parts: list  # str pieces and Interp objects, in order


@dataclass
class Call:
    name: str  # 'tr' or 'trf'
    name_start: int
    lits: list = field(default_factory=list)  # [arg1 lits, arg2 lits]
    arg2_end: int = 0
    nested: list = field(default_factory=list)  # calls found inside interpolations of the args
    line: int = 0


class Scanner:
    def __init__(self, src: str):
        self.s = src
        self.calls: list[Call] = []
        self.bad: list[tuple[int, str]] = []  # tr( with non-literal args

    # --- low level -------------------------------------------------------------------------
    def skip_ws(self, i: int) -> int:
        s = self.s
        while i < len(s):
            if s[i].isspace():
                i += 1
            elif s.startswith("//", i):
                j = s.find("\n", i)
                i = len(s) if j < 0 else j + 1
            elif s.startswith("/*", i):
                i = self.skip_block_comment(i)
            else:
                break
        return i

    def skip_block_comment(self, i: int) -> int:
        s, depth = self.s, 0
        while i < len(s):
            if s.startswith("/*", i):
                depth += 1
                i += 2
            elif s.startswith("*/", i):
                depth -= 1
                i += 2
                if depth == 0:
                    return i
            else:
                i += 1
        return i

    def string_start(self, i: int):
        """(is_raw, quote, body_start) when a string literal starts at i, else None."""
        s = self.s
        raw = False
        j = i
        if s[j] == "r" and j + 1 < len(s) and s[j + 1] in "'\"":
            raw, j = True, j + 1
        if j < len(s) and s[j] in "'\"":
            q = s[j] * 3 if s.startswith(s[j] * 3, j) else s[j]
            return raw, q, j + len(q)
        return None

    # --- strings ---------------------------------------------------------------------------
    def parse_string(self, i: int, sink: list) -> Lit:
        raw, q, j = self.string_start(i)
        s = self.s
        parts: list = []
        buf: list[str] = []
        if len(q) == 3:  # a newline right after an opening triple quote is dropped
            if s.startswith("\r\n", j):
                j += 2
            elif j < len(s) and s[j] == "\n":
                j += 1
        while j < len(s):
            if s.startswith(q, j):
                if buf:
                    parts.append("".join(buf))
                return Lit(i, j + len(q), raw, parts)
            c = s[j]
            if not raw and c == "\\":
                j, ch = self.escape(j)
                buf.append(ch)
                continue
            if not raw and c == "$":
                if buf:
                    parts.append("".join(buf))
                    buf = []
                if j + 1 < len(s) and s[j + 1] == "{":
                    end = self.parse_code(j + 2, sink, until_brace=True)
                    parts.append(Interp(j, end + 1, s[j + 2 : end].strip()))
                    j = end + 1
                else:
                    m = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(s, j + 1)
                    parts.append(Interp(j, m.end(), m.group(0)))
                    j = m.end()
                continue
            buf.append(c)
            j += 1
        raise ValueError(f"unterminated string at {i}")

    def escape(self, j: int):
        s = self.s
        c = s[j + 1]
        simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}
        if c in simple:
            return j + 2, simple[c]
        if c == "x":
            return j + 4, chr(int(s[j + 2 : j + 4], 16))
        if c == "u":
            if s[j + 2] == "{":
                k = s.index("}", j)
                return k + 1, chr(int(s[j + 3 : k], 16))
            return j + 6, chr(int(s[j + 2 : j + 6], 16))
        return j + 2, c

    # --- code ------------------------------------------------------------------------------
    def parse_code(self, i: int, sink: list, until_brace: bool = False) -> int:
        """Scan code from i. With until_brace, stop at the matching `}` and return its index."""
        s = self.s
        depth = 0
        while i < len(s):
            c = s[i]
            if s.startswith("//", i) or s.startswith("/*", i):
                i = self.skip_ws(i)
                continue
            if c in "'\"" or (c == "r" and self.string_start(i) and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "_$"))):
                lit = self.parse_string(i, sink)
                i = lit.end
                continue
            if c.isalpha() or c in "_$":
                m = IDENT.match(s, i)
                word = m.group(0)
                k = i - 1
                while k >= 0 and s[k].isspace():
                    k -= 1
                prev = s[k] if k >= 0 else ""
                if word in ("tr", "trf") and prev != ".":
                    k = self.skip_ws(m.end())
                    if k < len(s) and s[k] == "(":
                        call = self.parse_call(word, i, k + 1)
                        if call is not None:
                            sink.append(call)
                            i = call.arg2_end
                            continue
                        if word == "tr":
                            self.bad.append((i, s[i : s.find("\n", i)].strip()))
                i = m.end()
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0 and until_brace:
                    return i
                depth -= 1
            i += 1
        return i

    def parse_lits(self, i: int, sink: list):
        lits = []
        i = self.skip_ws(i)
        while i < len(self.s) and self.string_start(i):
            lit = self.parse_string(i, sink)
            lits.append(lit)
            i = self.skip_ws(lit.end)
        return lits, i

    def parse_call(self, name: str, name_start: int, i: int):
        nested: list = []
        a1, i = self.parse_lits(i, nested)
        if not a1 or i >= len(self.s) or self.s[i] != ",":
            return None
        a2, j = self.parse_lits(i + 1, nested)
        if not a2:
            return None
        k = j
        if name == "tr":  # tr must end right after the two literals
            if self.s[k] == ",":
                k = self.skip_ws(k + 1)
            if self.s[k] != ")":
                return None
        elif self.s[k] != ",":  # trf needs its args map
            return None
        arg2_end = a2[-1].end
        return Call(name, name_start, [a1, a2], arg2_end, nested, self.s.count("\n", 0, name_start) + 1)


def all_calls(calls):
    for c in calls:
        yield c
        yield from all_calls(c.nested)


def value(lits, names=None) -> str:
    out = []
    for lit in lits:
        for p in lit.value_parts:
            if isinstance(p, str):
                out.append(p)
            else:
                out.append("{" + names[norm(p.expr)] + "}")
    return "".join(out)


def interps(lits):
    return [p for lit in lits for p in lit.value_parts if isinstance(p, Interp)]


def norm(expr: str) -> str:
    return re.sub(r"\s+", "", expr)


def placeholder_name(expr: str) -> str:
    e = norm(expr)
    e = re.sub(r"^widget\.", "", e)
    if re.fullmatch(r"[A-Za-z_][\w.]*", e):
        segs = [x.lstrip("_") for x in e.split(".") if x.lstrip("_")]
        if not segs:
            return "v"
        if segs[-1] == "length" and len(segs) > 1:  # items.length -> itemsCount
            return segs[-2] + "Count"
        return segs[-1]  # counts.onTrack -> onTrack
    keys = re.findall(r"\[['\"]([A-Za-z_]\w*)['\"]\]", e)
    if keys:
        return keys[-1]
    m = re.match(r"_?([A-Za-z]\w*)\(", e)
    if m:
        return {"cpTitle": "title", "_mmss": "time"}.get(m.group(1), m.group(1))
    m = re.match(r"_?([A-Za-z]\w*)", e)
    if m and not re.search(r"[?:]", e):
        return m.group(1)
    return "v"


def rewrite_file(path: Path) -> tuple[int, list[str]]:
    src = path.read_text()
    sc = Scanner(src)
    top: list[Call] = []
    sc.parse_code(0, top)
    edits: list[tuple[int, int, str]] = []
    skipped: list[str] = []
    count = 0
    for call in all_calls(top):
        if call.name != "tr":
            continue
        a1, a2 = call.lits
        ins = interps(a1) + interps(a2)
        if not ins:
            continue
        if call.nested:
            skipped.append(f"{path}:{call.line} nested tr() inside interpolation")
            continue
        if any("{" in p or "}" in p for lit in a1 + a2 for p in lit.value_parts if isinstance(p, str)):
            skipped.append(f"{path}:{call.line} literal braces")
            continue
        names: dict[str, str] = {}
        used: set[str] = set()
        exprs: dict[str, str] = {}
        for p in ins:
            k = norm(p.expr)
            if k in names:
                continue
            base = placeholder_name(p.expr)
            n, i = base, 2
            while n in used:
                n, i = f"{base}{i}", i + 1
            names[k], exprs[n] = n, p.expr
            used.add(n)
        edits.append((call.name_start, call.name_start + 2, "trf"))
        for p in ins:
            edits.append((p.start, p.end, "{" + names[norm(p.expr)] + "}"))
        args = ", ".join(f"'{n}': {e}" for n, e in exprs.items())
        edits.append((call.arg2_end, call.arg2_end, f", {{{args}}}"))
        count += 1
    for a, b, text in sorted(edits, key=lambda e: e[0], reverse=True):
        src = src[:a] + text + src[b:]
    if count:
        path.write_text(src)
    return count, skipped


def dart_files(app: str):
    return sorted((ROOT / "apps" / app / "lib").rglob("*.dart"))


def owned(path: Path) -> bool:
    p = path.as_posix()
    return not any(p.endswith(x) for x in NO_REWRITE)


def cmd_rewrite():
    total = 0
    for app in APPS:
        for f in dart_files(app):
            if not owned(f):
                continue
            n, skipped = rewrite_file(f)
            total += n
            if n:
                print(f"{n:4d}  {f.relative_to(ROOT)}")
            for s in skipped:
                print("  skipped:", s)
    print("rewritten:", total)


def cmd_extract():
    entries: dict[str, dict] = {}
    untranslatable: list[str] = []
    nonliteral: list[str] = []
    for app in APPS:
        for f in dart_files(app):
            if f.name == "l10n.dart":
                continue
            src = f.read_text()
            sc = Scanner(src)
            top: list[Call] = []
            sc.parse_code(0, top)
            rel = f.relative_to(ROOT).as_posix()
            for pos, text in sc.bad:
                nonliteral.append(f"{rel}:{src.count(chr(10), 0, pos) + 1}: {text}")
            for call in all_calls(top):
                a1, a2 = call.lits
                if call.name == "tr" and (interps(a1) or interps(a2)):
                    untranslatable.append(f"{rel}:{call.line}")
                    continue
                if call.name == "trf":
                    en = "".join(p if isinstance(p, str) else "$" + p.expr for lit in a1 for p in lit.value_parts)
                    hi = "".join(p if isinstance(p, str) else "$" + p.expr for lit in a2 for p in lit.value_parts)
                else:
                    en, hi = value(a1), value(a2)
                e = entries.setdefault(en, {"en": en, "hi": {}, "apps": set(), "where": []})
                e["hi"].setdefault(hi, []).append(f"{rel}:{call.line}")
                e["apps"].add(app)
                e["where"].append(f"{rel}:{call.line}")
    for en, hi, note in EXTRA_KEYS:
        e = entries.setdefault(en, {"en": en, "hi": {}, "apps": set(), "where": []})
        e["hi"].setdefault(hi, []).append(note)
        e["apps"].update(APPS)
    out = []
    for en in sorted(entries):
        e = entries[en]
        out.append({
            "en": en,
            "hi": [{"text": h, "where": w} for h, w in e["hi"].items()],
            "apps": sorted(e["apps"]),
            "placeholders": sorted(set(re.findall(r"\{(\w+)\}", en))),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"strings": out, "untranslatable_tr": untranslatable, "nonliteral_tr": nonliteral},
                              ensure_ascii=False, indent=1))
    per_app = {a: sum(1 for x in out if a in x["apps"]) for a in APPS}
    print(f"keys: {len(out)}  per app: {per_app}  with placeholders: {sum(1 for x in out if x['placeholders'])}")
    print(f"collisions (one English, several Hindi): {sum(1 for x in out if len(x['hi']) > 1)}")
    print(f"interpolated tr() left (not translatable): {len(untranslatable)}")
    for u in untranslatable:
        print("   ", u)
    print(f"tr() with non-literal args: {len(nonliteral)}")
    for u in nonliteral:
        print("   ", u)


if __name__ == "__main__":
    {"rewrite": cmd_rewrite, "extract": cmd_extract}[sys.argv[1] if len(sys.argv) > 1 else "extract"]()
