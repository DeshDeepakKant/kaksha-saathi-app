"""Deterministic judging of one spoken answer in the 30-minute voice session.

Code decides, Claude talks: every verdict here is computed from the speech recogniser's
transcript against a known target, with no model and no network. "Pronunciation" therefore means
what the recogniser heard, not acoustics.

Hindi is compared at the akshara (grapheme-cluster) level after Unicode NFC, so an error can be
pinpointed as a consonant substitution (श → स in शेर), a vowel-sign slip (ी read as ि in मीना), a
left-out or added akshara, or swapped order (कमल → कलम). Spelling noise the recogniser produces
for the same sound (ज़/ज, फ़/फ, chandrabindu/anusvara, पन्द्रह/पंद्रह, गये/गए) counts as the
same word; ड़/ड and ढ़/ढ are different sounds, so they are close, not correct. English is compared
letter by letter, case- and punctuation-insensitive, and words that sound identical (to/two/too,
write/right) count as read correctly because the recogniser cannot tell them apart.

See docs/voice_session_contract.md; shapes come from app/services/voice_types.py.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from app.services.voice_types import Assessment
from app.speech.scorer import _DEV_DIGITS, _PUNCT, _diff_note_hi

CORRECT = 0.9        # word / item score at or above this is correct
CLOSE = 0.6          # at or above this is close ("almost")
ALIGN_MIN = 0.45     # a heard word must be at least this similar to align with a target word
MATCH_USED = 0.75    # sentence/answer: a heard word this similar counts as "the word was used"

# --------------------------------------------------------------------------- tokens

_BRACKETED = re.compile(r"[\[<{][^\]>}]*[\]>}]")      # ASR tags: [noise], <unk>, {laugh}
_ZERO_WIDTH = re.compile("[​‌‍﻿]")
_APOSTROPHES = re.compile(r"['’‘`]")
_FILLERS = {
    # Hindi hesitations (a filler that is also the target, e.g. the vowel ओ, is kept)
    "हम्म", "हम", "ह्म्म", "हां", "हाँ", "अं", "उं", "उम्म", "अम्म", "अजी", "ओ", "आं",
    # English hesitations
    "um", "umm", "uh", "uhh", "hmm", "hm", "mm", "mmm", "erm", "er", "ah", "eh", "oh",
}


MAX_PLAUSIBLE_WCPM = 250

def _tokens(text: str, lang: str, keep: frozenset[str] = frozenset()) -> list[str]:
    """Clean transcript tokens: NFC, ASR tags and punctuation removed, lower case, fillers dropped
    unless they are themselves an acceptable answer (`keep`)."""
    t = unicodedata.normalize("NFC", text or "")
    t = _BRACKETED.sub(" ", t)
    t = _ZERO_WIDTH.sub("", t)
    t = t.translate(_DEV_DIGITS).lower()
    if lang == "en":
        t = _APOSTROPHES.sub("", t)
    t = _PUNCT.sub(" ", t)
    out = []
    for w in t.split():
        w = "".join(ch for ch in w if unicodedata.category(ch)[0] in "LMN")
        if not w or (w in _FILLERS and w not in keep):
            continue
        out.append(w)
    return out


# --------------------------------------------------------------------------- aksharas

_NUKTA = "़"
_VIRAMA = "्"
_ANUSVARA = "ं"
_CHANDRABINDU = "ँ"
_URDU_NUKTA_BASES = set("कखगजफ")       # क़ ख़ ग़ ज़ फ़: spelled either way by ASR and speakers
_NASALS = "ङञणनम"


def _is_consonant(c: str) -> bool:
    o = ord(c)
    return 0x915 <= o <= 0x939 or 0x958 <= o <= 0x95F or 0x978 <= o <= 0x97F


def _is_vowel_letter(c: str) -> bool:
    o = ord(c)
    return 0x904 <= o <= 0x914 or o in (0x960, 0x961) or 0x972 <= o <= 0x977


def _is_matra(c: str) -> bool:
    o = ord(c)
    return ((0x93A <= o <= 0x94C and o not in (0x93C, 0x93D)) or o in (0x94E, 0x94F)
            or 0x955 <= o <= 0x957 or o in (0x962, 0x963))


def _is_modifier(c: str) -> bool:      # chandrabindu, anusvara, visarga
    return 0x900 <= ord(c) <= 0x903


def _is_mark(c: str) -> bool:
    return c in (_NUKTA, _VIRAMA) or _is_matra(c) or _is_modifier(c)


def aksharas(word: str) -> list[str]:
    """Split a word into grapheme clusters: क्षे, त्र, ज़ि, ...; Latin words split into letters."""
    out: list[str] = []
    prev_virama = False
    for ch in word:
        if out and (_is_mark(ch) or (prev_virama and _is_consonant(ch))):
            out[-1] += ch
        else:
            out.append(ch)
        prev_virama = ch == _VIRAMA
    return out


def _split(cluster: str) -> tuple[str, str]:
    """(base consonant/vowel letter incl. conjunct and nukta, vowel sign + nasal/visarga)."""
    base = "".join(c for c in cluster if not (_is_matra(c) or _is_modifier(c)))
    vowel = "".join(c for c in cluster if _is_matra(c) or _is_modifier(c))
    return base, vowel


_MATRA_AFTER = re.compile("(?<=[\u0901-\u094c\u0950-\u097f])य([\u0940\u0947])")  # गयी→गई, गये→गए
_NASAL_CLUSTER = re.compile(f"[{_NASALS}]{_VIRAMA}(?=[क-ह])")  # पन्द्रह→पंद्रह


def _fold_soft(word: str) -> str:
    """Spelling-only variants the recogniser produces for the same sound -> one form."""
    w = unicodedata.normalize("NFC", word)      # NFC keeps nukta as a separate mark
    w = "".join(c for i, c in enumerate(w)
                if not (c == _NUKTA and i and w[i - 1] in _URDU_NUKTA_BASES))
    w = w.replace(_CHANDRABINDU, _ANUSVARA)
    w = _NASAL_CLUSTER.sub(_ANUSVARA, w)
    w = _MATRA_AFTER.sub(lambda m: {"ी": "ई", "े": "ए"}[m.group(1)], w)
    return w


def _fold_hard(word: str) -> str:
    """Also drop the nukta of ड़/ढ़ (a real sound difference: close, not correct)."""
    return _fold_soft(word).replace(_NUKTA, "")


# Pairs a child (or the recogniser) easily mixes up: a substitution among them is "closer".
_CONFUSABLE = [set(aksharas(unicodedata.normalize("NFC", s))) for s in (
    "शसष", "बव", "नण", "डड़र", "ढढ़", "कख", "गघ", "चछ", "जझ", "टठ", "तथ", "दध", "पफ", "बभ",
    "टत", "डद", "यज", "लर", "अआ", "इई", "उऊ", "एऐ", "ओऔ", "bdpq", "mn", "uv", "ck", "sz", "fv", "ie", "ae", "ou",
)]


def _confusable(a: str, b: str) -> bool:
    return (a.replace(_NUKTA, "") == b.replace(_NUKTA, "")
            or any(a in s and b in s for s in _CONFUSABLE))


# --------------------------------------------------------------------------- English helpers

_HOMOPHONES = [set(s.split()) for s in (
    "to two too", "write right rite", "there their theyre", "no know", "see sea", "sun son",
    "be bee", "for four", "hear here", "one won", "by buy bye", "blue blew", "ate eight",
    "flower flour", "meet meat", "night knight", "pair pear", "tail tale", "wait weight",
    "week weak", "whole hole", "your youre", "road rode", "made maid", "mail male", "its its",
    "i eye", "dear deer", "new knew", "not knot", "red read", "sail sale", "so sew sow",
    "wear where", "would wood", "which witch", "won one", "our hour", "ant aunt", "cell sell",
)]

# Letter names and simple sounds an English letter is read as ("bee", "buh").
_EN_LETTER_NAMES = {
    "a": "ay eh ae aa ah", "b": "bee be bi buh bah", "c": "see sea si cee kuh", "d": "dee di duh",
    "e": "ee eh", "f": "ef eff fuh ff fff", "g": "gee jee ji guh", "h": "aitch etch haitch huh",
    "i": "eye aye ih", "j": "jay jae juh", "k": "kay kae kuh", "l": "el ell luh",
    "m": "em mm mmm muh", "n": "en nn nuh", "o": "oh owe aw", "p": "pee pea puh",
    "q": "queue cue kyu kwuh", "r": "are ar ruh", "s": "es ess ss sss suh", "t": "tee tea tuh",
    "u": "you yu uh", "v": "vee vuh", "w": "doubleu doubleyou wuh", "x": "ex eks ks",
    "y": "why wai yuh", "z": "zee zed zz zuh",
}
_EN_NAME_TO_LETTER = {n: l for l, names in _EN_LETTER_NAMES.items() for n in names.split()}


def _homophones(a: str, b: str) -> bool:
    return any(a in s and b in s for s in _HOMOPHONES)


def _is_latin(w: str) -> bool:
    return w.isascii()


# --------------------------------------------------------------------------- word comparison

def _cluster_pair(tc: str, hc: str) -> tuple[float, list[tuple[str, str, str]]]:
    """Credit (0..1) and errors for one target akshara heard as another."""
    tb, tv = _split(tc)
    hb, hv = _split(hc)
    if tb == hb:                                   # same consonant, different vowel sign
        return 0.6, [("matra", tv, hv)]
    if tv == hv:                                   # same vowel sign, different consonant
        if tb.replace(_NUKTA, "") == hb.replace(_NUKTA, ""):
            return 0.85, [("substitution", tb, hb)]
        return (0.5 if _confusable(tb, hb) else 0.35), [("substitution", tb, hb)]
    return 0.2, [("substitution", tb, hb), ("matra", tv, hv)]


@lru_cache(maxsize=8192)
def _cmp(target: str, heard: str) -> tuple[float, tuple[tuple[str, str, str], ...]]:
    """Similarity of one target word to one heard word (0..1) and the akshara-level errors.

    Errors are (type, target_part, heard_part) with type substitution|matra|omission|insertion|order.
    """
    if target == heard:
        return 1.0, ()
    ft, fh = _fold_soft(target), _fold_soft(heard)
    if ft == fh or (_is_latin(ft) and _homophones(ft, fh)):
        return 1.0, ()
    at, ah = aksharas(ft), aksharas(fh)
    if len(at) > 1 and sorted(at) == sorted(ah):
        return 0.7, (("order", target, heard),)
    credit = 0.0
    errs: list[tuple[str, str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, at, ah, autojunk=False).get_opcodes():
        if op == "equal":
            credit += i2 - i1
        elif op == "delete":
            errs += [("omission", c, "") for c in at[i1:i2]]
        elif op == "insert":
            errs += [("insertion", "", c) for c in ah[j1:j2]]
        else:
            ts, hs = at[i1:i2], ah[j1:j2]
            for k in range(max(len(ts), len(hs))):
                if k < len(ts) and k < len(hs):
                    c, e = _cluster_pair(ts[k], hs[k])
                    credit += c
                    errs += e
                elif k < len(ts):
                    errs.append(("omission", ts[k], ""))
                else:
                    errs.append(("insertion", "", hs[k]))
    score = credit / max(len(at), len(ah), 1)
    if _fold_hard(target) == _fold_hard(heard):    # only ड़/ड, ढ़/ढ differ: a real but small slip
        score = min(score, 0.85)
    return round(score, 3), tuple(errs)


def _status(score: float) -> str:
    return "correct" if score >= CORRECT else "close" if score >= CLOSE else "wrong"


def _err(kind: str, target: str, heard: str, word: str) -> dict:
    return {"type": kind, "target": target, "heard": heard, "word": word}


def _word_errors(target: str, heard: str) -> list[dict]:
    return [_err(k, t, h, target) for k, t, h in _cmp(target, heard)[1]]


def _silent(heard_tokens: list[str]) -> bool:
    return not heard_tokens


def _keep(*groups) -> frozenset[str]:
    out: set[str] = set()
    for g in groups:
        for s in g or ():
            out.update(_tokens(s, "hi"))
            out.update(_tokens(s, "en"))
    return frozenset(out)


def _silent_assessment(notes: str = "nothing heard") -> Assessment:
    return Assessment(verdict="silent", score=0.0, heard="", notes=notes)


# --------------------------------------------------------------------------- alignment

def _align(targets: list[str], heard: list[str]) -> list[tuple[int | None, int | None]]:
    """Monotonic alignment maximising total similarity (tolerates skipped and repeated words).

    Returns (target_index, heard_index) pairs in reading order; None on one side means a missed
    target word or an extra heard word.
    """
    n, m = len(targets), len(heard)
    sim = [[_cmp(t, h)[0] for h in heard] for t in targets]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            v = max(best[i + 1][j], best[i][j + 1])
            if sim[i][j] >= ALIGN_MIN:
                v = max(v, sim[i][j] + best[i + 1][j + 1])
            best[i][j] = v
    pairs: list[tuple[int | None, int | None]] = []
    i = j = 0
    while i < n and j < m:
        if sim[i][j] >= ALIGN_MIN and abs(best[i][j] - (sim[i][j] + best[i + 1][j + 1])) < 1e-9:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif abs(best[i][j] - best[i][j + 1]) < 1e-9:
            pairs.append((None, j))
            j += 1
        else:
            pairs.append((i, None))
            i += 1
    pairs += [(k, None) for k in range(i, n)] + [(None, k) for k in range(j, m)]
    # Inside each gap between aligned words, a missed target and an extra heard word that sit
    # in the same place mean the child said *something else* there: pair them as "wrong".
    out: list[tuple[int | None, int | None]] = []
    k = 0
    while k < len(pairs):
        if pairs[k][0] is not None and pairs[k][1] is not None:
            out.append(pairs[k])
            k += 1
            continue
        gap_t, gap_h, repeats = [], [], []
        while k < len(pairs) and (pairs[k][0] is None or pairs[k][1] is None):
            ti, hj = pairs[k]
            if ti is not None:
                gap_t.append(ti)
            elif _is_repeat(heard, hj):
                repeats.append(hj)               # "गया गया": a re-read is extra, not a wrong word
            else:
                gap_h.append(hj)
            k += 1
        for x in range(max(len(gap_t), len(gap_h))):
            out.append((gap_t[x] if x < len(gap_t) else None, gap_h[x] if x < len(gap_h) else None))
        out += [(None, r) for r in repeats]
    return out


def _is_repeat(heard: list[str], j: int) -> bool:
    return ((j > 0 and _cmp(heard[j - 1], heard[j])[0] >= CORRECT)
            or (j + 1 < len(heard) and _cmp(heard[j + 1], heard[j])[0] >= CORRECT))


# --------------------------------------------------------------------------- letters

def _is_bare_letter(target: str, lang: str) -> bool:
    t = unicodedata.normalize("NFC", target.strip())
    if lang == "en" or _is_latin(t):
        return len(t) == 1 and t.isalpha()
    cl = aksharas(t)
    if len(cl) != 1:
        return False
    base, vowel = _split(cl[0])
    return not vowel.strip(_ANUSVARA + _CHANDRABINDU + "ः") or _is_vowel_letter(base[0])


def _letter_variants(letter: str, lang: str) -> set[str]:
    """Ways a recogniser writes a child saying this letter (its name or sound)."""
    if lang == "en" or _is_latin(letter):
        names = _EN_LETTER_NAMES.get(letter, "").split()
        return {letter, *names, letter + "uh", letter + "ah"}
    out = {letter, letter + "ः"}                        # कः
    base, vowel = _split(letter)
    if _is_consonant(letter[0]) and not vowel:
        out |= {letter + "ा", letter + "े", letter + _VIRAMA,   # का, के, क्
                letter + "अ", letter + "कार"}                             # ककार
    return {_fold_soft(v) for v in out}


def _first_base(tok: str, lang: str) -> str:
    if lang == "en" or _is_latin(tok):
        return _EN_NAME_TO_LETTER.get(tok, tok[:1])
    cl = aksharas(_fold_soft(tok))
    return _split(cl[0])[0] if cl else ""


def _assess_letter(target: str, raw: str, lang: str, accept=()) -> Assessment:
    letter = unicodedata.normalize("NFC", target.strip()).lower()
    variants = _letter_variants(letter, lang) | {_fold_soft(a) for a in _keep(accept)}
    toks = _tokens(raw, lang, keep=frozenset(variants) | _keep([letter]))
    if _silent(toks):
        return _silent_assessment()
    heard = " ".join(toks)
    t_base = _split(_fold_soft(letter))[0]
    for tok in toks:                                   # "क", "का", "क से कमल", "bee", "b for ball"
        if _fold_soft(tok) in variants:
            return Assessment("correct", 1.0, heard,
                              words=[{"target": target, "heard": tok, "status": "correct"}])
    for tok in toks:
        if _fold_hard(tok) == _fold_hard(letter):      # ड for ड़
            return Assessment("close", 0.8, heard,
                              words=[{"target": target, "heard": tok, "status": "close"}],
                              errors=[_err("substitution", t_base, _first_base(tok, lang), target)],
                              notes="nukta missing")
    for tok in toks:                                   # a word that starts with the right sound
        if len(tok) > 1 and _first_base(tok, lang) in (t_base, letter):
            return Assessment("close", 0.7, heard,
                              words=[{"target": target, "heard": tok, "status": "close"}],
                              notes=f"said a word starting with {target}")
    got = _first_base(toks[0], lang)
    return Assessment("wrong", 0.3 if _confusable(t_base, got) else 0.0, heard,
                      words=[{"target": target, "heard": toks[0], "status": "wrong"}],
                      errors=[_err("substitution", t_base, got, target)],
                      notes=f"{target} → {got}")


# --------------------------------------------------------------------------- separate sounds

def _sounds_said_separately(target: str, toks: list[str], lang: str) -> bool:
    """True when the child produced the word's sounds one by one ("क म ल", "c a t") but not
    the blended word."""
    if len(toks) < 2:
        return False
    if lang == "en" or _is_latin(target):
        parts = [_EN_NAME_TO_LETTER.get(t, t) for t in toks]
        if any(len(p) != 1 for p in parts):
            return False
        return _cmp(target, "".join(parts))[0] >= CLOSE
    if any(len(aksharas(t)) != 1 for t in toks):
        return False
    t_bases = [_split(c)[0] for c in aksharas(_fold_hard(target))]
    h_bases = [_split(aksharas(_fold_hard(t))[0])[0] for t in toks]
    return t_bases == h_bases or _cmp(target, "".join(toks))[0] >= CLOSE


def _not_blended(target: str, toks: list[str], heard: str, score: float = 0.7) -> Assessment:
    return Assessment("close", score, heard,
                      words=[{"target": target, "heard": heard, "status": "close"}],
                      errors=[_err("not_blended", target, heard, target)],
                      notes="said the sounds separately, not blended into one word")


# --------------------------------------------------------------------------- public API

def assess_reading(target: str, transcript: str, lang: str, duration_s: float | None = None,
                   accept=(), *, letter: bool | None = None) -> Assessment:
    """Judge reading a letter, word, sentence or paragraph aloud.

    `accept` (optional) lists extra readings that count as correct. `letter` forces / disables
    letter mode (auto: a bare letter target such as "क" or "b").
    """
    lang = lang or "hi"
    target = target or ""
    if letter is None:
        letter = _is_bare_letter(target, lang)
    if letter and target.strip():
        return _assess_letter(target, transcript, lang, accept)
    targets = _tokens(target, lang, keep=_keep([target]))
    toks = _tokens(transcript, lang, keep=_keep([target], accept))
    if _silent(toks):
        return _silent_assessment()
    heard = " ".join(toks)
    if not targets:
        return Assessment("close", 0.5, heard, notes="no target to compare with")
    for a in accept or ():                             # a whole accepted reading
        if _tokens(a, lang) == toks:
            return Assessment("correct", 1.0, heard,
                              words=[{"target": t, "heard": t, "status": "correct"} for t in targets])
    if len(targets) == 1:
        return _assess_single_word(targets[0], toks, heard, lang, accept)
    return _assess_passage(targets, toks, heard, lang, duration_s)


def _assess_single_word(target: str, toks: list[str], heard: str, lang: str, accept=()) -> Assessment:
    options = [target] + [w for a in accept or () for w in [" ".join(_tokens(a, lang))] if w]
    best_score, best_tok, best_target = -1.0, toks[0], target
    for opt in options:
        for tok in toks:
            s = _cmp(opt, tok)[0]
            if s > best_score:
                best_score, best_tok, best_target = s, tok, opt
    if best_score >= CORRECT:
        return Assessment("correct", best_score, heard,
                          words=[{"target": target, "heard": best_tok, "status": "correct"}])
    if _sounds_said_separately(target, toks, lang):
        return _not_blended(target, toks, heard)
    joined = "".join(toks)                             # recogniser split one word: "कम ल"
    if len(toks) > 1 and _cmp(target, joined)[0] > best_score:
        best_score, best_tok, best_target = _cmp(target, joined)[0], joined, target
    status = _status(best_score)
    note = ""
    if status != "correct":
        note = (_diff_note_hi([target], [best_tok]) if lang == "hi"
                else f"heard '{best_tok}' for '{target}'")
    return Assessment(status, round(best_score, 3), heard,
                      words=[{"target": target, "heard": best_tok, "status": status}],
                      errors=_word_errors(best_target, best_tok), notes=note)


def _assess_passage(targets: list[str], toks: list[str], heard: str, lang: str,
                    duration_s: float | None) -> Assessment:
    words: list[dict] = []
    errors: list[dict] = []
    n_correct = n_close = 0
    for ti, hi in _align(targets, toks):
        if ti is not None and hi is not None:
            t, h = targets[ti], toks[hi]
            score = _cmp(t, h)[0]
            status = _status(score)
            words.append({"target": t, "heard": h, "status": status})
            if status == "correct":
                n_correct += 1
            elif status == "close":
                n_close += 1
                errors += _word_errors(t, h)
            else:
                errors.append(_err("substitution", t, h, t))
        elif ti is not None:
            words.append({"target": targets[ti], "heard": "", "status": "missed"})
            errors.append(_err("missing_word", targets[ti], "", targets[ti]))
        else:
            words.append({"target": "", "heard": toks[hi], "status": "extra"})
    accuracy = (n_correct + 0.5 * n_close) / len(targets)
    fluency = None
    if duration_s and duration_s > 0:
        wcpm = n_correct * 60.0 / duration_s
        # a child reading aloud manages well under 250 words a minute; faster means the recording was cut
        # short or its duration is wrong, so report no fluency rather than a false number
        if wcpm <= MAX_PLAUSIBLE_WCPM:
            fluency = {"wcpm": round(wcpm, 1), "duration_s": round(float(duration_s), 1)}
    n_missed = sum(1 for w in words if w["status"] == "missed")
    notes = (f"{n_correct}/{len(targets)} words correct, {n_close} close, {n_missed} missed")
    return Assessment(_status(accuracy), round(accuracy, 3), heard, words=words,
                      errors=errors[:20], fluency=fluency, notes=notes)


def assess_word_build(target_word: str, transcript: str, lang: str, accept=()) -> Assessment:
    """Blend tiles into one word: correct only for the blended word (or an accepted one); the
    sounds said one by one is close, with a `not_blended` error."""
    lang = lang or "hi"
    target_word = (target_word or "").strip()
    keep = _keep([target_word], accept)
    toks = _tokens(transcript, lang, keep=keep)
    if _silent(toks):
        return _silent_assessment()
    heard = " ".join(toks)
    target = " ".join(_tokens(target_word, lang)) or target_word
    if not target:
        return Assessment("close", 0.5, heard, notes="no target to compare with")
    return _assess_single_word(target, toks, heard, lang, accept)


def _hi_stem(w: str) -> str:
    for suf in ("ियाँ", "ियां", "ाएँ", "ाएं", "ाओं", "ओं", "ों", "ें", "ाँ", "ां", "ता", "ती", "ते", "ना",
                "नी", "ने", "कर", "या", "यी", "ये", "ई", "ए", "ा", "ी", "े", "ो"):
        if w.endswith(suf) and len(aksharas(w[: -len(suf)])) >= 1 and len(w) > len(suf):
            return w[: -len(suf)]
    return w


def _en_stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            w = w[: -len(suf)]
            if len(w) >= 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
                w = w[:-1]                        # running -> run, stopped -> stop
            return w
    return w[:-1] if len(w) > 3 and w.endswith("e") else w   # make ~ making


def _match_word(word: str, toks: list[str], lang: str, used: set[int]) -> tuple[int | None, str]:
    """Find a heard token that uses `word` (exact, inflection/matra variant or close match).
    Returns (token index, "correct"|"close") or (None, "missed")."""
    stem = _en_stem if (lang == "en" or _is_latin(word)) else _hi_stem
    best: tuple[float, int | None] = (0.0, None)
    for i, tok in enumerate(toks):
        if i in used:
            continue
        s = _cmp(word, tok)[0]
        if s < CORRECT and stem(_fold_hard(word)) == stem(_fold_hard(tok)):
            s = max(s, CORRECT)                      # खाना ~ खाती ~ खाया, run ~ running
        if s > best[0]:
            best = (s, i)
    s, i = best
    if i is None or s < MATCH_USED:
        return None, "missed"
    return i, "correct" if s >= CORRECT else "close"


def _uses_all(words: list[str], toks: list[str], lang: str) -> bool:
    used: set[int] = set()
    for w in words:
        i, _ = _match_word(w, toks, lang, used)
        if i is None:
            return False
        used.add(i)
    return True


def assess_sentence_build(required_words, transcript: str, lang: str) -> Assessment:
    """Code check of a spoken sentence: uses every required word (inflections and close matches
    allowed), at least 3 words, and more than the word list read back."""
    lang = lang or "hi"
    required = [w for r in required_words or () for w in [" ".join(_tokens(r, lang))] if w]
    toks = _tokens(transcript, lang, keep=_keep(required))
    if _silent(toks):
        return _silent_assessment()
    heard = " ".join(toks)
    used: set[int] = set()
    words, errors = [], []
    for r in required:
        i, status = _match_word(r, toks, lang, used)
        if i is None:
            words.append({"target": r, "heard": "", "status": "missed"})
            errors.append(_err("missing_word", r, "", r))
        else:
            used.add(i)
            words.append({"target": r, "heard": toks[i], "status": status})
    words += [{"target": "", "heard": t, "status": "extra"} for i, t in enumerate(toks) if i not in used]
    found = sum(1 for w in words if w["target"] and w["status"] != "missed")
    is_sentence = len(toks) >= 3 and len(toks) > len(used)
    if required and found == len(required) and is_sentence:
        n_close = sum(1 for w in words if w["status"] == "close")
        return Assessment("correct", round(1.0 - 0.05 * n_close, 3), heard, words=words,
                          notes="all words used in a sentence")
    if not is_sentence:
        errors.append(_err("not_a_sentence", " ".join(required), heard, ""))
    if found:
        score = 0.4 + 0.4 * found / max(1, len(required)) + (0.1 if is_sentence else 0.0)
        return Assessment("close", round(min(score, 0.85), 3), heard, words=words, errors=errors,
                          notes=f"{found}/{len(required)} words used")
    if not required and is_sentence:
        return Assessment("close", 0.6, heard, words=words, notes="no required words to check")
    return Assessment("wrong", 0.2 if is_sentence else 0.0, heard, words=words, errors=errors,
                      notes="required words not used")


def assess_answer(keywords, transcript: str, lang: str, accept=()) -> Assessment:
    """Fallback check of a comprehension answer: any accepted answer, or at least half the
    keywords -> correct; some keywords -> close."""
    lang = lang or "hi"
    kws = [w for k in keywords or () for w in [" ".join(_tokens(k, lang))] if w]
    accepts = [_tokens(a, lang) for a in accept or ()]
    toks = _tokens(transcript, lang, keep=_keep(kws, accept))
    if _silent(toks):
        return _silent_assessment()
    heard = " ".join(toks)
    for a in accepts:
        if a and _uses_all(a, toks, lang):
            return Assessment("correct", 1.0, heard,
                              words=[{"target": " ".join(a), "heard": heard, "status": "correct"}],
                              notes="accepted answer")
    if not kws:
        return Assessment("close", 0.5, heard, notes="no answer key; needs a human or AI check")
    used = set()
    words, errors = [], []
    for k in kws:
        parts = k.split()
        idx = [_match_word(p, toks, lang, used) for p in parts]
        ok = all(i is not None for i, _ in idx)
        if ok:
            used.update(i for i, _ in idx)
        words.append({"target": k, "heard": " ".join(toks[i] for i, _ in idx if i is not None) if ok else "",
                      "status": "correct" if ok else "missed"})
        if not ok:
            errors.append(_err("missing_word", k, "", k))
    found = sum(1 for w in words if w["status"] == "correct")
    score = round(found / len(kws), 3)
    if found and found * 2 >= len(kws):
        return Assessment("correct", max(score, CORRECT), heard, words=words, errors=errors,
                          notes=f"{found}/{len(kws)} key words")
    if found:
        return Assessment("close", max(score, CLOSE), heard, words=words, errors=errors,
                          notes=f"{found}/{len(kws)} key words")
    return Assessment("wrong", 0.0, heard, words=words, errors=errors, notes="no key words")


_READING_KINDS = {"read_letter", "say_sound", "read_word", "read_sentence", "read_paragraph"}


def assess_item(item: dict, transcript: str, duration_s: float | None = None) -> Assessment:
    """Judge a transcript against a session item (dispatch by item["kind"])."""
    kind = item.get("kind") or ""
    lang = item.get("lang") or "hi"
    display = item.get("display") or {}
    accept = list(item.get("accept") or [])
    target = item.get("target") or display.get("text") or ""
    if kind in _READING_KINDS:
        return assess_reading(target, transcript, lang, duration_s, accept=accept,
                              letter=True if kind in ("read_letter", "say_sound") else None)
    if kind == "build_word":
        return assess_word_build(target or "".join(display.get("tiles") or []), transcript, lang, accept)
    if kind == "make_sentence":
        return assess_sentence_build(item.get("required_words") or display.get("words") or [],
                                     transcript, lang)
    if kind == "answer_question":
        if item.get("target"):
            accept.append(item["target"])
        return assess_answer(item.get("keywords") or [], transcript, lang, accept)
    if target:
        return assess_reading(target, transcript, lang, duration_s, accept=accept)
    return assess_answer(item.get("keywords") or [], transcript, lang, accept)


# --------------------------------------------------------------------------- describing errors

def describe_error(err: dict) -> tuple[str, str]:
    """(English, Hindi) one-line description of an error dict, e.g. ("श → स", "श → स")."""
    k, t, h, w = err.get("type"), err.get("target") or "", err.get("heard") or "", err.get("word") or ""
    in_w = f" in {w}" if w and w not in (t, h) else ""
    in_w_hi = f" ({w} में)" if w and w not in (t, h) else ""
    if k == "substitution":
        return f"{t} → {h}{in_w}", f"{t} → {h}{in_w_hi}"
    if k == "matra":
        if not h:
            return f"missing {t} matra{in_w}", f"{t} की मात्रा छूटी{in_w_hi}"
        if not t:
            return f"extra {h} matra{in_w}", f"{h} की मात्रा ज़्यादा लगी{in_w_hi}"
        return f"{t} matra read as {h}{in_w}", f"{t} की मात्रा को {h} पढ़ा{in_w_hi}"
    if k == "omission":
        return f"left out {t}{in_w}", f"{t} छूट गया{in_w_hi}"
    if k == "insertion":
        return f"added {h}{in_w}", f"{h} ज़्यादा जोड़ा{in_w_hi}"
    if k == "order":
        return f"order mixed up: {t} → {h}", f"क्रम बदला: {t} → {h}"
    if k == "missing_word":
        return f"missed word: {t}", f"शब्द छूटा: {t}"
    if k == "not_blended":
        return (f"said the sounds separately ({h}) instead of {t}",
                f"आवाज़ें अलग-अलग बोलीं ({h}), {t} जोड़कर नहीं बोला")
    if k == "not_a_sentence":
        return "only said the words, not a full sentence", "पूरा वाक्य नहीं बोला, सिर्फ़ शब्द बोले"
    return f"{k}: {t} → {h}".strip(), f"{k}: {t} → {h}".strip()
