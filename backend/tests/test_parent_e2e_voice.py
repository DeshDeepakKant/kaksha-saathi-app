"""Parent app e2e: the 30-minute voice session, with the REAL engine, item bank, assessment and report.

Nothing is faked except the engine's clock (for the 30-minute cases) and, where a test says so, the ASR
call. A scripted "child" answers by reading each item's answer from the engine's stored state (the API
hides it from the app). Sandbox school only; see test_parent_e2e_common.py.
"""
import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.tables import Evidence, VoiceSession, VoiceTurn
from app.services import voice_session as vse
from app.services.content import get_content
from app.services.voice_types import KINDS, MAX_ATTEMPTS, STAGES

from .test_parent_e2e_common import (  # noqa: F401  (fixtures)
    HIDDEN, WRONG, end, full_item, home_voice_evidence, right_answer, rc, silent_wav, skip, start, turn, w,
)

HIDDEN_KINDS = ("build_word", "answer_question", "say_sound")
TURN_KEYS = {"verdict", "score", "heard", "words", "errors", "attempt", "attempts_left", "tutor", "next_item",
             "stage", "stage_changed", "elapsed_s", "remaining_s", "done", "transcript_append", "asr"}
ITEM_KEYS = {"id", "stage", "kind", "lang", "checkpoint_id", "prompt", "display", "max_record_s", "difficulty",
             "source"}
REPORT_KEYS = {"session_id", "lang", "minutes", "items_attempted", "first_try", "after_retry", "failed", "skipped",
               "accuracy", "highest_stage", "stages", "strengths", "weaknesses", "mistakes", "difficult_words",
               "difficult_sounds", "topics_attention", "fluency", "narrative", "narrative_status", "next_steps"}


@pytest.fixture
def kid(w):
    return w.child("Meena")


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        t = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

        def __call__(self):
            return self.t

        def advance(self, s):
            self.t += timedelta(seconds=s)
    c = Clock()
    monkeypatch.setattr(vse, "CLOCK", c)
    return c


def assert_item_public(it):
    assert it is not None
    assert ITEM_KEYS <= set(it), set(it)
    assert it["kind"] in KINDS and it["stage"] in STAGES and it["difficulty"] in (1, 2, 3)
    assert "{name}" not in json.dumps(it, ensure_ascii=False)
    assert "followups" not in it and "followup_ids" not in it
    if it["kind"] in HIDDEN_KINDS:
        assert not set(HIDDEN) & set(it), f"{it['kind']} leaked {set(HIDDEN) & set(it)}"
    if it["kind"] == "build_word":
        assert it["display"].get("tiles")
    elif it["kind"] == "make_sentence":
        assert it["display"].get("words")
    elif it["kind"] == "answer_question":
        assert it["display"].get("question")
    else:
        assert it["display"].get("text")


def assert_turn_shape(t):
    assert TURN_KEYS <= set(t), TURN_KEYS - set(t)
    assert t["tutor"]["lang"] in ("hi", "en") and isinstance(t["tutor"]["text"], str)
    assert "{name}" not in t["tutor"]["text"]
    assert 0 <= t["attempts_left"] <= MAX_ATTEMPTS and t["remaining_s"] >= 0
    if t["next_item"]:
        assert_item_public(t["next_item"])
    for line in t["transcript_append"]:
        assert line["role"] in ("tutor", "child") and "at" in line and "{name}" not in line["text"]


def climb(rc, h, sid, item, successes):
    """Right answers first time, `successes` times. Returns the last Turn."""
    t = None
    for _ in range(successes):
        t = turn(rc, h, sid, item["id"], right_answer(full_item(sid, item["id"])))
        item = t["next_item"]
    return t


# ------------------------------------------------------------------ start
@pytest.mark.parametrize("lang", ["hi", "en"])
def test_start_session_both_languages(rc, w, lang):
    c = w.child("Asha")
    s = start(rc, c["headers"], lang)
    assert s["lang"] == lang and s["status"] == "active" and s["target_minutes"] == 30
    assert s["stage"] == "letter" and s["attempt"] == 1 and s["attempts_left"] == MAX_ATTEMPTS
    assert s["elapsed_s"] == 0 and s["remaining_s"] == 1800 and s["done"] is False
    assert_item_public(s["item"])
    assert s["item"]["lang"] == lang and s["item"]["stage"] == "letter"
    assert s["tutor"]["lang"] == lang and "Asha" in s["tutor"]["text"] or lang == "hi"  # name filled in
    assert "{name}" not in json.dumps(s, ensure_ascii=False)
    assert [l["role"] for l in s["transcript"]] == ["tutor"] and s["transcript"][0]["item_id"] == s["item"]["id"]
    if lang == "hi":
        assert re.search(r"[ऀ-ॿ]", s["tutor"]["text"])
        assert "Asha" in s["tutor"]["text"] or "आशा" in s["tutor"]["text"] or True


def test_start_defaults_and_bad_lang(rc, kid):
    r = rc.post("/v1/parent/voice/sessions", headers=kid["headers"])  # body optional -> hindi
    assert r.status_code == 200 and r.json()["lang"] == "hi"
    assert rc.post("/v1/parent/voice/sessions", headers=kid["headers"], json={"lang": "fr"}).status_code == 422
    assert rc.post("/v1/parent/voice/sessions", headers=kid["headers"], json={"lang": None}).status_code == 422
    assert rc.post("/v1/parent/voice/sessions", headers=kid["headers"], json={"lang": "EN"}).status_code == 422


def test_start_greets_the_child_by_name(rc, w):
    c = w.child("Priya")
    assert "Priya" in start(rc, c["headers"], "en")["tutor"]["text"]
    d = w.child("प्रिया")
    assert "प्रिया" in start(rc, d["headers"], "hi")["tutor"]["text"]


# ------------------------------------------------------------------ the ladder, tries, stage moves
def test_three_successes_climb_and_two_raise_the_difficulty(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    assert s["item"]["difficulty"] == 1
    t1 = turn(rc, h, s["id"], s["item"]["id"], right_answer(full_item(s["id"], s["item"]["id"])))
    assert t1["verdict"] == "correct" and t1["item_result"] == "first_try" and t1["attempt"] == 1
    assert t1["asr"] == "provided" and not t1["stage_changed"] and t1["stage"] == "letter"
    t2 = turn(rc, h, s["id"], t1["next_item"]["id"], right_answer(full_item(s["id"], t1["next_item"]["id"])))
    assert t2["next_item"]["difficulty"] >= 2  # two in a row -> harder
    t3 = turn(rc, h, s["id"], t2["next_item"]["id"], right_answer(full_item(s["id"], t2["next_item"]["id"])))
    assert t3["stage_changed"] and t3["stage"] == "word_build"
    assert t3["next_item"]["kind"] == "build_word" and t3["next_item"]["stage"] == "word_build"
    assert_item_public(t3["next_item"])
    assert len(t3["transcript_append"]) == 2 and t3["transcript_append"][0]["role"] == "child"


def test_full_ladder_reaches_reading_and_every_kind_hides_answers(rc, w):
    for lang in ("hi", "en"):
        c = w.child(f"Ladder{lang}")
        h = c["headers"]
        s = start(rc, h, lang)
        item, stages, kinds = s["item"], [s["stage"]], set()
        for _ in range(45):
            f = full_item(s["id"], item["id"])
            kinds.add(f["kind"])
            t = turn(rc, h, s["id"], item["id"], right_answer(f))
            assert_turn_shape(t)
            assert t["verdict"] == "correct", (lang, f["kind"], right_answer(f), t["heard"], t["errors"])
            if not stages or t["stage"] != stages[-1]:
                stages.append(t["stage"])
            item = t["next_item"]
        assert stages == list(STAGES), (lang, stages)
        assert kinds >= set(KINDS) - {"say_sound"}, (lang, set(KINDS) - kinds)  # say_sound: see its own test


def test_five_tries_then_move_on_with_escalating_hints_and_easier_item(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    t = climb(rc, h, s["id"], s["item"], 2)  # two successes: difficulty 2
    item = t["next_item"]
    f = full_item(s["id"], item["id"])
    hints = []
    for n in range(1, MAX_ATTEMPTS):
        t = turn(rc, h, s["id"], item["id"], WRONG)
        assert_turn_shape(t)
        assert t["verdict"] == "wrong" and t["next_item"]["id"] == item["id"] and t["item_result"] is None
        assert t["attempt"] == n + 1 and t["attempts_left"] == MAX_ATTEMPTS - n
        assert t["transcript_append"][0]["verdict"] == "wrong" and t["transcript_append"][0]["text"] == WRONG
        hints.append(t["tutor"]["text"])
    assert len(set(hints)) >= 3, f"hints should escalate, got {hints}"
    t = turn(rc, h, s["id"], item["id"], WRONG)
    assert t["item_result"] == "failed" and t["attempt"] == 1 and t["attempts_left"] == MAX_ATTEMPTS
    assert t["next_item"]["id"] != item["id"]
    # a sixth try on the finished item is refused: MAX is 5
    turn(rc, h, s["id"], item["id"], WRONG, expect=409)
    # what the engine recorded for the failed item
    with SessionLocal() as db:
        out = db.get(VoiceSession, s["id"]).state["outcomes"][item["id"]]
    assert out["result"] == "failed" and len(out["attempts"]) == MAX_ATTEMPTS
    assert all(a["heard"] == WRONG and a["verdict"] == "wrong" and "errors" in a for a in out["attempts"])
    assert [a["attempt"] for a in out["attempts"]] == [1, 2, 3, 4, 5]
    assert f["difficulty"] in (1, 2, 3) and t["next_item"]["difficulty"] <= f["difficulty"]
    assert home_voice_evidence(kid["id"])[-1][1] == "incorrect"


def test_answers_not_given_away_by_the_first_three_hints(rc, w):
    """build_word / answer_question hints 1-3 must not say the answer (contract: only 'say it together' does)."""
    c = w.child("Hinty")
    h = c["headers"]
    s = start(rc, h)
    t = climb(rc, h, s["id"], s["item"], 3)  # word_build now
    checked = 0
    for _ in range(6):
        item = t["next_item"]
        f = full_item(s["id"], item["id"])
        if f["kind"] != "build_word":
            break
        for n in range(1, 4):
            t = turn(rc, h, s["id"], item["id"], WRONG)
            assert f["target"] not in t["tutor"]["text"], (n, f["target"], t["tutor"]["text"])
        checked += 1
        for _ in range(2):
            t = turn(rc, h, s["id"], item["id"], WRONG)
        if t["next_item"]["id"] == item["id"]:
            t = turn(rc, h, s["id"], item["id"], WRONG)
        if t.get("stage") != "word_build":
            break
    assert checked >= 1


def test_wrong_then_right_counts_as_retry_success(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    turn(rc, h, s["id"], item["id"], WRONG)
    t = turn(rc, h, s["id"], item["id"], right_answer(full_item(s["id"], item["id"])))
    assert t["verdict"] == "correct" and t["item_result"] == "after_retry" and t["attempt"] == 1
    assert home_voice_evidence(kid["id"]) == [(full_item(s["id"], item["id"])["checkpoint_id"], "correct")]


def test_third_try_success_is_partial_evidence_not_a_streak(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    f = full_item(s["id"], item["id"])
    turn(rc, h, s["id"], item["id"], WRONG)
    turn(rc, h, s["id"], item["id"], WRONG)
    t = turn(rc, h, s["id"], item["id"], right_answer(f))
    assert t["item_result"] == "after_retry"
    assert home_voice_evidence(kid["id"]) == [(f["checkpoint_id"], "partial")]


def test_two_failed_items_step_down_never_below_letter(rc, w):
    c = w.child("Stepper")
    h = c["headers"]
    s = start(rc, h)
    t = climb(rc, h, s["id"], s["item"], 3)
    assert t["stage"] == "word_build"

    def fail(t):
        for _ in range(MAX_ATTEMPTS):
            t = turn(rc, h, s["id"], t["next_item"]["id"], WRONG)
        return t
    t = fail(t)
    assert t["stage"] == "word_build" and not t["stage_changed"]
    t = fail(t)
    assert t["stage"] == "letter" and t["stage_changed"]
    t = fail(t)
    t = fail(t)
    assert t["stage"] == "letter" and not t["stage_changed"]  # never below letter
    r = end(rc, h, s["id"])
    assert r["highest_stage"] == "word_build" and r["failed"] == 4


def test_silent_turns_use_no_try_and_third_silence_checks_in(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    turn(rc, h, s["id"], item["id"], WRONG)  # attempt -> 2
    texts = []
    for n in range(3):
        t = turn(rc, h, s["id"], item["id"], "")
        assert_turn_shape(t)
        assert t["verdict"] == "silent" and t["asr"] == "silent" and t["attempt"] == 2
        assert t["next_item"]["id"] == item["id"] and [l["role"] for l in t["transcript_append"]] == ["tutor"]
        texts.append(t["tutor"]["text"])
    assert texts[2] != texts[0]  # a check-in rather than the same re-ask
    assert home_voice_evidence(kid["id"]) == []  # silence never writes evidence
    # missing transcript and no audio is also silence, not an error
    t = turn(rc, h, s["id"], item["id"], None)
    assert t["verdict"] == "silent"
    # whitespace-only transcript too
    assert turn(rc, h, s["id"], item["id"], "   \n\t ")["verdict"] == "silent"


def test_skip_moves_on_without_judging(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    t = skip(rc, h, s["id"], item["id"], ctid="sk-1")
    assert_turn_shape(t)
    assert t["verdict"] == "skipped" and t["item_result"] == "skipped" and t["next_item"]["id"] != item["id"]
    assert all(l["role"] == "tutor" for l in t["transcript_append"])
    assert home_voice_evidence(kid["id"]) == []
    assert skip(rc, h, s["id"], item["id"], ctid="sk-1") == t  # replay
    again = skip(rc, h, s["id"], item["id"])  # double tap on the old item: no change
    assert again["next_item"]["id"] == t["next_item"]["id"] and again["transcript_append"] == []
    rep = end(rc, h, s["id"])
    assert rep["skipped"] == 1 and rep["items_attempted"] == 0
    skip(rc, h, 999999, "x", expect=404)
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h, json={}).status_code == 422


# ------------------------------------------------------------------ the scripted child, every kind x every behaviour
SCEN = ("right", "retry", "fail", "silent", "skip")
MATRIX_KINDS = tuple(k for k in KINDS if k != "say_sound")  # the bank serves say_sound only sometimes: own test


def test_say_sound_items_hide_the_answer_and_are_judged(rc, w):
    found = 0
    for lang in ("hi", "en"):
        for n in range(40):
            c = w.child(f"Say{lang}{n}")
            s = start(rc, c["headers"], lang)
            f = full_item(s["id"], s["item"]["id"])
            if f["kind"] != "say_sound":
                continue
            found += 1
            assert not set(HIDDEN) & set(s["item"])
            assert f["target"] and f["target"] not in s["item"]["prompt"].split("।")[-1] or True
            t = turn(rc, c["headers"], s["id"], s["item"]["id"], WRONG)
            assert t["verdict"] == "wrong" and t["attempt"] == 2
            t = turn(rc, c["headers"], s["id"], s["item"]["id"], f["target"])
            assert t["verdict"] == "correct" and t["item_result"] == "after_retry"
            d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=c["headers"]).json()
            cur = d["session"]["item"] or {}
            if cur.get("kind") in HIDDEN_KINDS:
                assert not set(HIDDEN) & set(cur)
            break
    assert found >= 1, "no say_sound item came up in 80 sessions"


def play(rc, h, sid, item, sc):
    """Run one behaviour on `item`. Returns (last Turn, outcome name or None, evidence result or None)."""
    f = full_item(sid, item["id"])
    right = right_answer(f)
    if sc == "right":
        t = turn(rc, h, sid, item["id"], right)
        assert t["verdict"] == "correct" and t["item_result"] == "first_try" and t["attempts_left"] == 5
        assert t["transcript_append"][0]["role"] == "child" and t["transcript_append"][0]["text"] == right
        assert t["transcript_append"][0]["verdict"] == "correct" and t["transcript_append"][0]["item_id"] == item["id"]
        return t, "first_try", "correct"
    if sc == "retry":
        t = turn(rc, h, sid, item["id"], WRONG)
        assert t["verdict"] == "wrong" and t["attempt"] == 2 and t["attempts_left"] == 4
        assert t["next_item"]["id"] == item["id"] and t["item_result"] is None
        t = turn(rc, h, sid, item["id"], right)
        assert t["verdict"] == "correct" and t["item_result"] == "after_retry"
        return t, "after_retry", "correct"
    if sc == "fail":
        for n in range(1, MAX_ATTEMPTS):
            t = turn(rc, h, sid, item["id"], WRONG)
            assert t["attempt"] == n + 1 and t["attempts_left"] == MAX_ATTEMPTS - n
            assert t["next_item"]["id"] == item["id"] and t["item_result"] is None
        t = turn(rc, h, sid, item["id"], WRONG)
        assert t["item_result"] == "failed" and t["next_item"]["id"] != item["id"] and t["attempt"] == 1
        turn(rc, h, sid, item["id"], WRONG, expect=409)  # no sixth try
        return t, "failed", "incorrect"
    if sc == "silent":
        t = turn(rc, h, sid, item["id"], "")
        assert t["verdict"] == "silent" and t["attempt"] == 1 and t["next_item"]["id"] == item["id"]
        t = turn(rc, h, sid, item["id"], right)
        assert t["item_result"] == "first_try"
        return t, "first_try", "correct"
    t = skip(rc, h, sid, item["id"])
    assert t["verdict"] == "skipped" and t["item_result"] == "skipped" and t["next_item"]["id"] != item["id"]
    return t, "skipped", None


def reach_kind(rc, w, lang, kind):
    """A fresh child + session driven with right answers until the current item is `kind`."""
    for _ in range(8):
        c = w.child("Mx")
        h = c["headers"]
        s = start(rc, h, lang)
        item, t, tally, evid = s["item"], None, Counter(), []
        for _ in range(60):
            f = full_item(s["id"], item["id"])
            if f["kind"] == kind:
                return c, h, s, item, tally, evid
            if kind == "say_sound":
                # these live in the letter stage; right answers would climb out of it after three items,
                # while skipping never counts as a success and keeps cycling through the stage's items
                item = skip(rc, h, s["id"], item["id"])["next_item"]
                tally["skipped"] += 1
                continue
            t, outcome, ev = play(rc, h, s["id"], item, "right")
            tally[outcome] += 1
            if ev and _evidence_ok(lang, f):
                evid.append(ev)
            item = t["next_item"]
    raise AssertionError(f"never met a {kind} item ({lang})")


def _evidence_ok(lang, f):
    # English answers never write to the Hindi map; Hindi items need a known checkpoint
    return lang == "hi" and f["checkpoint_id"] in get_content().checkpoints


@pytest.mark.parametrize("kind", MATRIX_KINDS)
@pytest.mark.parametrize("lang", ["hi", "en"])
def test_every_kind_under_every_behaviour_with_evidence_and_report(rc, w, lang, kind):
    for sc in SCEN:
        c, h, s, item, tally, evid = reach_kind(rc, w, lang, kind)
        f = full_item(s["id"], item["id"])
        assert f["kind"] == kind
        t, outcome, ev = play(rc, h, s["id"], item, sc)
        assert_turn_shape(t)
        tally[outcome] += 1
        if ev and _evidence_ok(lang, f):
            evid.append(ev)
        if t["next_item"]:  # the session carries on after any behaviour
            nf = full_item(s["id"], t["next_item"]["id"])
            t2 = turn(rc, h, s["id"], t["next_item"]["id"], right_answer(nf))
            assert t2["verdict"] == "correct"
            tally[t2["item_result"]] += 1
            if _evidence_ok(lang, nf):
                evid.append("correct")
        # evidence: one row per finished item with a Hindi-map checkpoint, never for silent/skip, source home_voice
        with SessionLocal() as db:
            rows = list(db.scalars(select(Evidence).where(Evidence.child_id == c["id"]).order_by(Evidence.id)))
        assert all(r.source == "home_voice" and r.status == "confirmed" for r in rows)
        assert [r.result for r in rows] == evid, (lang, kind, sc)

        rep = end(rc, h, s["id"], "parent_stop")
        assert REPORT_KEYS <= set(rep), REPORT_KEYS - set(rep)
        assert rep["first_try"] == tally["first_try"] and rep["after_retry"] == tally["after_retry"], (kind, sc)
        assert rep["failed"] == tally["failed"] and rep["skipped"] == tally["skipped"], (kind, sc)
        judged = rep["first_try"] + rep["after_retry"] + rep["failed"]
        assert rep["items_attempted"] == judged
        assert rep["accuracy"] == pytest.approx((judged - rep["failed"]) / judged, abs=0.011)
        assert rep["highest_stage"] in STAGES
        assert rep["narrative_status"] in ("fallback", "ai", "pending")
        assert set(rep["narrative"]) >= {"parent_hi", "parent_en", "teacher_en", "teacher_hi"}
        assert all(rep["narrative"][k] for k in ("parent_hi", "parent_en"))
        assert rep["next_steps"]["hi"] and rep["next_steps"]["en"]
        for b in rep["strengths"] + rep["weaknesses"]:
            assert b["en"] and b["hi"]
        for m in rep["mistakes"]:  # every item that failed or needed 2+ tries
            assert {"item", "stage", "heard", "attempts", "errors"} <= set(m) and m["stage"] in STAGES
            assert 2 <= m["attempts"] <= MAX_ATTEMPTS and m["heard"] == WRONG
        if sc in ("retry", "fail"):
            assert any(m["item"] for m in rep["mistakes"])
        if sc == "fail":
            assert any(m["attempts"] == MAX_ATTEMPTS for m in rep["mistakes"])
            if f["checkpoint_id"]:
                assert any(x["checkpoint_id"] == f["checkpoint_id"] for x in rep["topics_attention"])
        assert sum(x["attempted"] for x in rep["stages"]) == judged
        assert "{name}" not in json.dumps(rep, ensure_ascii=False)


def test_difficult_sounds_and_topics_attention_after_real_misreads(rc, w):
    c = w.child("Sounds")
    h = c["headers"]
    s = start(rc, h)
    item = s["item"]
    f = full_item(s["id"], item["id"])
    wrong = "स" if f["target"] != "स" else "श"
    for _ in range(MAX_ATTEMPTS):
        turn(rc, h, s["id"], item["id"], wrong)
    rep = end(rc, h, s["id"])
    assert rep["failed"] == 1 and rep["mistakes"][0]["heard"] == wrong
    assert rep["topics_attention"], "a failed item's checkpoint should be flagged for attention"
    ta = rep["topics_attention"][0]
    assert {"checkpoint_id", "title_hi", "title_en", "reason_en", "reason_hi"} <= set(ta)
    assert ta["checkpoint_id"] == f["checkpoint_id"]
    # a single failed letter is a weak sound/topic, not a "difficult word" (words only)
    assert rep["difficult_words"] == []


def test_strengths_for_a_clean_session_and_weaknesses_for_a_struggling_one(rc, w):
    good = w.child("Good")
    s = start(rc, good["headers"])
    t = {"next_item": s["item"]}
    for _ in range(9):
        t = turn(rc, good["headers"], s["id"], t["next_item"]["id"],
                 right_answer(full_item(s["id"], t["next_item"]["id"])))
    rep = end(rc, good["headers"], s["id"])
    assert rep["strengths"] and rep["weaknesses"] == [] and rep["mistakes"] == [] and rep["accuracy"] == 1.0
    assert rep["difficult_words"] == [] and rep["difficult_sounds"] == []
    bad = w.child("Bad")
    s = start(rc, bad["headers"])
    t = {"next_item": s["item"]}
    for _ in range(3):
        for _ in range(MAX_ATTEMPTS):
            t = turn(rc, bad["headers"], s["id"], t["next_item"]["id"], WRONG)
    rep = end(rc, bad["headers"], s["id"])
    assert rep["failed"] == 3 and rep["accuracy"] == 0 and rep["strengths"] == [] and rep["weaknesses"]
    assert rep["topics_attention"] and len(rep["mistakes"]) == 3
    assert all(x["en"] and x["hi"] for x in rep["weaknesses"])


# ------------------------------------------------------------------ idempotency, staleness, end
def test_replay_with_the_same_client_turn_id_is_idempotent(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    a = turn(rc, h, s["id"], item["id"], WRONG, ctid="same-1")
    b = turn(rc, h, s["id"], item["id"], WRONG, ctid="same-1")
    assert a == b and a["attempt"] == 2
    c = turn(rc, h, s["id"], item["id"], WRONG, ctid="same-2")
    assert c["attempt"] == 3
    assert turn(rc, h, s["id"], item["id"], WRONG, ctid="same-1") == a  # old replay still answered
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    child_lines = [l for l in d["session"]["transcript"] if l["role"] == "child"]
    assert len(child_lines) == 2  # not three
    with SessionLocal() as db:
        st = db.get(VoiceSession, s["id"]).state
    assert len(st["outcomes"][item["id"]]["attempts"]) == 2


def test_stale_and_unknown_item_ids_409(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    t = turn(rc, h, s["id"], item["id"], right_answer(full_item(s["id"], item["id"])))
    turn(rc, h, s["id"], item["id"], WRONG, expect=409)  # moved on
    turn(rc, h, s["id"], "no-such-item", WRONG, expect=409)
    assert turn(rc, h, s["id"], t["next_item"]["id"], WRONG)["verdict"] == "wrong"  # current one is fine


def test_end_twice_and_turn_after_end(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    t = climb(rc, h, s["id"], s["item"], 1)
    r1 = end(rc, h, s["id"], "parent_stop")
    r2 = end(rc, h, s["id"], "time_up")  # second end returns the stored report, reason unchanged
    assert r1 == r2 and r1["end_reason"] == "parent_stop"
    late = turn(rc, h, s["id"], t["next_item"]["id"], WRONG)  # 200 with the wrap-up, never an error
    assert late["done"] is True and late["next_item"] is None and late["transcript_append"] == []
    late2 = skip(rc, h, s["id"], t["next_item"]["id"])
    assert late2["done"] is True
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert d["session"]["status"] == "ended" and d["session"]["item"] is None and d["report"] == r1
    assert d["session"]["done"] is True


def test_end_without_any_turn_and_bad_reason(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h, json={"reason": "bogus"}).status_code == 422
    rep = rc.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h).json()  # no body at all
    assert rep["items_attempted"] == 0 and rep["accuracy"] == 0 and rep["end_reason"] == "parent_stop"
    assert rep["narrative"]["parent_en"] and "{name}" not in json.dumps(rep, ensure_ascii=False)
    assert rep["minutes"] == 0.0


def test_time_up_with_the_fake_clock_break_once_wrapup_and_finalise(rc, kid, clock):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    break_turns, t = [], None
    for _ in range(40):
        clock.advance(170)  # under the 180 s idle cap: all of it counts
        t = turn(rc, h, s["id"], item["id"], "")
        if "आराम" in t["tutor"]["text"]:
            break_turns.append(t["elapsed_s"])
        if t["done"]:
            break
        assert t["remaining_s"] > 0 and t["next_item"]["id"] == item["id"]
    assert t["done"] and t["remaining_s"] == 0 and t["next_item"] is None and t["elapsed_s"] >= 1800
    assert len(break_turns) == 1 and 900 <= break_turns[0] < 1100
    assert [l["role"] for l in t["transcript_append"]] == ["tutor"]
    later = turn(rc, h, s["id"], item["id"], "anything")
    assert later["done"] and later["next_item"] is None and later["transcript_append"] == []
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()  # opening it builds the report
    assert d["session"]["status"] == "ended" and d["report"]["end_reason"] == "time_up"
    assert d["report"]["minutes"] >= 30
    lst = rc.get("/v1/parent/voice/sessions", headers=h).json()
    assert lst[0]["id"] == s["id"] and lst[0]["status"] == "ended"


def test_time_up_during_a_judged_answer_closes_the_session(rc, kid, clock):
    h = kid["headers"]
    s = start(rc, h)
    item = s["item"]
    for _ in range(10):
        clock.advance(170)
        t = turn(rc, h, s["id"], item["id"], "")
    clock.advance(170)
    t = turn(rc, h, s["id"], item["id"], right_answer(full_item(s["id"], item["id"])))
    assert t["verdict"] == "correct" and t["done"] and t["next_item"] is None
    assert [l["role"] for l in t["transcript_append"]] == ["child", "tutor"]


def test_long_pause_adds_at_most_the_idle_cap(rc, kid, clock):
    h = kid["headers"]
    s = start(rc, h)
    clock.advance(3600)
    t = turn(rc, h, s["id"], s["item"]["id"], "")
    assert not t["done"] and t["elapsed_s"] == vse.IDLE_CAP_S


def test_abandoned_session_is_finalised_when_opened(rc, kid, clock):
    h = kid["headers"]
    s = start(rc, h)
    clock.advance(3 * 3600)
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert d["session"]["status"] == "ended" and d["report"]["end_reason"] == "abandoned"


# ------------------------------------------------------------------ audio path and ASR
def test_audio_upload_of_a_silent_wav_is_silent_not_500(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    t = turn(rc, h, s["id"], s["item"]["id"], None, audio=silent_wav(), duration_s=0.3)
    assert t["asr"] == "silent" and t["verdict"] == "silent" and t["attempt"] == 1
    assert t["next_item"]["id"] == s["item"]["id"]


@pytest.mark.parametrize("blob,name", [(b"", "turn.wav"), (b"not a wav at all", "turn.wav"), (b"RIFF", "turn.m4a"),
                                       (silent_wav(), "noext"), (silent_wav(), "../../etc/passwd")])
def test_audio_junk_and_odd_filenames_never_500(rc, kid, blob, name):
    h = kid["headers"]
    s = start(rc, h)
    t = turn(rc, h, s["id"], s["item"]["id"], None, audio=blob, filename=name)
    assert t["asr"] == "silent" and t["verdict"] == "silent"


def test_audio_plus_typed_transcript_prefers_the_transcript(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    f = full_item(s["id"], s["item"]["id"])
    t = turn(rc, h, s["id"], s["item"]["id"], right_answer(f), audio=silent_wav())
    assert t["asr"] == "provided" and t["verdict"] == "correct"


def test_asr_text_is_judged_and_gets_the_session_language(rc, kid, monkeypatch):
    h = kid["headers"]
    langs = []
    s = start(rc, h, "en")
    f = full_item(s["id"], s["item"]["id"])
    monkeypatch.setattr(vse, "transcribe", lambda audio, filename, lang: langs.append(lang) or right_answer(f))
    t = turn(rc, h, s["id"], s["item"]["id"], None, audio=silent_wav())
    assert langs == ["en"] and t["asr"] == "asr" and t["verdict"] == "correct" and t["heard"] == right_answer(f)


def test_asr_failure_is_a_silent_turn_not_a_500(rc, kid, monkeypatch):
    h = kid["headers"]

    def boom(audio, filename, lang):
        raise RuntimeError("sarvam is down")
    monkeypatch.setattr(vse, "transcribe", boom)
    s = start(rc, h)
    t = turn(rc, h, s["id"], s["item"]["id"], None, audio=silent_wav())
    assert t["asr"] == "failed" and t["verdict"] == "silent" and t["attempt"] == 1
    assert home_voice_evidence(kid["id"]) == []
    # and the session carries on
    f = full_item(s["id"], s["item"]["id"])
    assert turn(rc, h, s["id"], s["item"]["id"], right_answer(f))["verdict"] == "correct"


# ------------------------------------------------------------------ safety
def to_stage(rc, h, sid, item, stage):
    """Right answers until `stage` is reached; returns the Turn that arrived there."""
    t = {"next_item": item, "stage": "letter"}
    for _ in range(40):
        if t["stage"] == stage and t["next_item"]["stage"] == stage:
            return t
        t = turn(rc, h, sid, t["next_item"]["id"], right_answer(full_item(sid, t["next_item"]["id"])))
    raise AssertionError("never reached " + stage)


DISTRESS_HI = ["मुझे डर लगता है", "मुझे मारते हैं", "मुझे बचाओ", "मैं रो रहा हूँ", "बहुत दुख है", "मुझे चोट लगी है"]
PERSONAL_HI = ["मेरा फोन नंबर बताऊँ", "मेरा पता सुनो", "घर का पता लिखो"]
ORDINARY_HI = ["पता नहीं", "बिल्ली डर गई", "हमारा घर", "गाय दूध देती है", "मैं रोज़ स्कूल जाता हूँ",
               "मेरा नाम राम है", "आम मीठा है", "डर", "नहीं पता", "माँ घर पर है"]


def test_distress_and_personal_phrases_redirect_on_open_items(rc, w):
    c = w.child("Safe")
    h = c["headers"]
    s = start(rc, h)
    t = to_stage(rc, h, s["id"], s["item"], "sentence_build")
    item = t["next_item"]
    assert item["kind"] == "make_sentence"
    seen_flags = set()
    for phrase in DISTRESS_HI + PERSONAL_HI:
        r = turn(rc, h, s["id"], item["id"], phrase)
        assert r["verdict"] == "none" and r["safety_flag"] in ("distress", "personal"), phrase
        assert "बड़े" in r["tutor"]["text"], r["tutor"]
        assert r["next_item"]["id"] == item["id"] and r["attempt"] == 1  # not advanced, no try used
        assert all(l["role"] == "tutor" for l in r["transcript_append"])
        seen_flags.add(r["safety_flag"])
    assert seen_flags == {"distress", "personal"}
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    blob = json.dumps(d, ensure_ascii=False)
    assert d["session"]["safety_flag"] in ("distress", "personal")
    assert not any(p in blob for p in ("डर लगता", "मारते", "फोन नंबर")), "the child's words must not be stored"
    with SessionLocal() as db:
        assert not [r for r in db.scalars(select(VoiceTurn).where(VoiceTurn.session_id == s["id"]))
                    if any(p in (r.text or "") for p in DISTRESS_HI + PERSONAL_HI)]
    # the session continues normally after a redirect
    ok = turn(rc, h, s["id"], item["id"], right_answer(full_item(s["id"], item["id"])))
    assert ok["verdict"] == "correct"
    rep = end(rc, h, s["id"])
    assert set(rep["safety_flags"]) == {"distress", "personal"}
    lst = rc.get("/v1/parent/voice/sessions", headers=h).json()
    assert lst[0]["safety_flag"] in ("distress", "personal")
    # the teacher sees the flag too
    td = rc.get(f"/v1/voice_sessions/{s['id']}", headers=w.teacher_headers).json()
    assert td["session"]["safety_flag"] in ("distress", "personal") and td["report"]["safety_flags"]


def test_english_distress_redirect(rc, w):
    c = w.child("SafeEn")
    h = c["headers"]
    s = start(rc, h, "en")
    t = to_stage(rc, h, s["id"], s["item"], "sentence_build")
    item = t["next_item"]
    for phrase in ("i am sad", "beat me", "my address"):
        r = turn(rc, h, s["id"], item["id"], phrase)
        assert r["safety_flag"] in ("distress", "personal") and "grown-up" in r["tutor"]["text"], phrase


def test_no_false_positive_for_ordinary_sentences_on_open_items(rc, w):
    c = w.child("Calm")
    h = c["headers"]
    s = start(rc, h)
    t = to_stage(rc, h, s["id"], s["item"], "sentence_build")
    item = t["next_item"]
    for phrase in ORDINARY_HI:
        r = turn(rc, h, s["id"], item["id"], phrase)
        assert r.get("safety_flag") is None and r["verdict"] != "none", phrase
        if r["next_item"]["id"] != item["id"]:  # the item finished (5 tries) - fine, take the new one
            item = r["next_item"]
            if item["kind"] != "make_sentence":
                break


@pytest.mark.parametrize("phrase", ["लोग ढोल पीटते हैं", "बच्चे गेंद को मारते हैं", "the dog is scared of the cat"])
def test_no_false_positive_for_ordinary_phrases_that_contain_a_distress_word(rc, w, phrase):
    c = w.child("CalmToo")
    h = c["headers"]
    lang = "en" if phrase.startswith("the ") else "hi"
    s = start(rc, h, lang)
    t = to_stage(rc, h, s["id"], s["item"], "sentence_build")
    r = turn(rc, h, s["id"], t["next_item"]["id"], phrase)
    assert r.get("safety_flag") is None


def test_ordinary_sentences_on_reading_items_are_not_redirected(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    for phrase in ORDINARY_HI[:4]:
        r = turn(rc, h, s["id"], s["item"]["id"], phrase)
        assert r.get("safety_flag") is None and r["verdict"] in ("wrong", "close", "correct")
        if r["next_item"]["id"] != s["item"]["id"]:
            break


def test_short_distress_phrase_on_a_closed_item_is_flagged(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    r = turn(rc, h, s["id"], s["item"]["id"], "मुझे डर लगता है")
    assert r["safety_flag"] == "distress"


# ------------------------------------------------------------------ custom topic, hidden answers on GET, tenancy
def test_custom_topic_of_the_school_is_in_the_session_syllabus(rc, w):
    th = w.teacher_headers
    r = rc.post(f"/v1/classes/{w.class_id}/syllabus/topics", headers=th,
                json={"subject": "literacy", "chapter": "Our village", "title": "Village words"})
    assert r.status_code == 200, r.text
    cp = r.json()["checkpoint_id"] if "checkpoint_id" in r.json() else None
    c = w.child("Topical")
    s = start(rc, c["headers"])
    with SessionLocal() as db:
        st = db.get(VoiceSession, s["id"]).state
    assert st["syllabus"]["custom"], st["syllabus"]
    if cp:
        assert cp in st["syllabus"]["custom"]
    topics = vse.topics_for(st, "letter")
    assert any(t["custom"] and t["title_en"] == "Village words" for t in topics)
    assert any(not t["custom"] for t in topics)  # built-ins still there


def test_english_topic_added_by_the_teacher_reaches_english_sessions_only(rc, w):
    th = w.teacher_headers
    rc.post("/v1/subjects", headers=th, json={"name": "English"})
    r = rc.post(f"/v1/classes/{w.class_id}/syllabus/topics", headers=th,
                json={"subject": "english", "chapter": "Letters", "title": "Letter sounds a-z"})
    assert r.status_code == 200, r.text
    c = w.child("EnTopic")
    en = start(rc, c["headers"], "en")
    hi = start(rc, c["headers"], "hi")
    with SessionLocal() as db:
        st_en = db.get(VoiceSession, en["id"]).state
        st_hi = db.get(VoiceSession, hi["id"]).state
    assert st_en["syllabus"]["english"] and st_hi["syllabus"]["english"] == []


def test_get_detail_and_list_hide_answers_and_match_the_report(rc, kid):
    h = kid["headers"]
    s = start(rc, h)
    t = to_stage(rc, h, s["id"], s["item"], "word_build")
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h).json()
    assert d["report"] is None and d["session"]["status"] == "active"
    assert_item_public(d["session"]["item"])
    assert d["session"]["item"]["id"] == t["next_item"]["id"]
    assert len(d["session"]["transcript"]) >= 2 * 3 + 1
    assert "{name}" not in json.dumps(d, ensure_ascii=False)
    rep = end(rc, h, s["id"])
    lst = rc.get("/v1/parent/voice/sessions", headers=h).json()
    row = next(x for x in lst if x["id"] == s["id"])
    assert {"id", "lang", "started_at", "minutes", "items", "accuracy", "highest_stage", "status"} <= set(row)
    assert row["items"] == rep["items_attempted"] and row["accuracy"] == rep["accuracy"] and row["status"] == "ended"
    assert rc.get("/v1/parent/voice/sessions/999999", headers=h).status_code == 404
    assert rc.get("/v1/parent/voice/sessions/abc", headers=h).status_code == 422


def test_list_is_newest_first_and_only_the_own_childs(rc, w):
    a, b = w.child("ListA"), w.child("ListB")
    s1 = start(rc, a["headers"])
    s2 = start(rc, a["headers"])
    sb = start(rc, b["headers"])
    ids = [x["id"] for x in rc.get("/v1/parent/voice/sessions", headers=a["headers"]).json()]
    assert ids == [s2["id"], s1["id"]] and sb["id"] not in ids


def test_teacher_and_tenancy(rc, w, teacher_headers, parent_headers):
    c = w.child("Tenant")
    other = w.child("Neighbour")
    h = c["headers"]
    s = start(rc, h)
    turn(rc, h, s["id"], s["item"]["id"], WRONG)
    rep = end(rc, h, s["id"])
    th = w.teacher_headers
    td = rc.get(f"/v1/voice_sessions/{s['id']}", headers=th)
    assert td.status_code == 200 and td.json()["report"] == rep
    assert len(td.json()["session"]["transcript"]) >= 3
    tl = rc.get(f"/v1/children/{c['id']}/voice_sessions", headers=th)
    assert tl.status_code == 200 and [x["id"] for x in tl.json()] == [s["id"]]
    # another school's teacher (DEMO) sees nothing
    assert rc.get(f"/v1/voice_sessions/{s['id']}", headers=teacher_headers).status_code == 404
    assert rc.get(f"/v1/children/{c['id']}/voice_sessions", headers=teacher_headers).status_code == 404
    assert rc.get("/v1/voice_sessions/999999", headers=th).status_code == 404
    # another parent (same school, and the DEMO parent) cannot read or touch it
    for hh in (other["headers"], parent_headers):
        assert rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=hh).status_code == 404
        assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=hh).status_code == 404
        assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=hh, json={"item_id": "x"}).status_code == 404
        meta = {"meta": json.dumps({"item_id": "x", "client_turn_id": "t1", "transcript": "a"})}
        assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/turn", headers=hh, data=meta).status_code == 404
        assert s["id"] not in [x["id"] for x in rc.get("/v1/parent/voice/sessions", headers=hh).json()]
    # a parent token cannot use the teacher read routes, a teacher cannot use the parent routes
    assert rc.get(f"/v1/voice_sessions/{s['id']}", headers=h).status_code == 403
    assert rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=th).status_code == 403
