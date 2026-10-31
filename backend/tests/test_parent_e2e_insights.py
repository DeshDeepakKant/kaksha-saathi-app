"""Parent app e2e: the school -> home insight routes (docs/parent_insights_contract.md).

DEMO child 12 is read-only. Everything that needs particular evidence uses a sandbox school.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.tables import Attendance, Evidence, Plan, VoiceSession
from app.seed import NAMES_2A, NAMES_3A
from app.services import ledger, parent_insights as insights, tips

from .test_parent_e2e_common import (  # noqa: F401  (fixtures)
    full_item, rc, right_answer, start, turn, w,
)

BORROW = "N.G2.sub_2digit_borrow"
CARRY = "N.G2.add_2digit_carry"
PV = "N.G2.place_value_99"
LIT = "L.G1.vyanjan"
STATES = {"learned", "working", "next", "later"}
ROUTES = ["/v1/parent/school_week", "/v1/parent/journey", "/v1/parent/journey?subject=literacy",
          "/v1/parent/tips", "/v1/parent/moments", "/v1/parent/weekly"]
FORBIDDEN = re.compile(r"group|समूह|score|rank|%|percent|प्रतिशत|रैंक", re.I)


def _ago(**kw) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**kw)


def add_ev(w, child, cp, result, at, source="teacher_tap", misc=None):
    with SessionLocal() as db:
        db.add(Evidence(school_id=w.school_id, class_id=child["class_id"], child_id=child["id"], checkpoint_id=cp,
                        result=result, source=source, confidence=1.0, at=at, status="confirmed", misconception=misc))
        db.commit()


def get_all(rc, h):
    out = {}
    for path in ROUTES:
        r = rc.get(path, headers=h)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        out[path] = r.json()
    return out


def texts(obj) -> list[str]:
    """Every string value in a JSON body, except machine ids and dates."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("checkpoint_id", "misconception", "id", "nipun_ref", "kind", "move", "state", "subject", "day",
                     "at", "seen_at", "as_of", "week_start", "week_end"):
                continue
            out += texts(v)
    elif isinstance(obj, list):
        for v in obj:
            out += texts(v)
    elif isinstance(obj, str):
        out.append(obj)
    return out


def name_tokens(names):
    return {t for n in names for t in re.findall(r"[ऀ-ॿ]+", n)}


# ------------------------------------------------------------------ shapes, for the seeded child and a brand-new one
def check_shapes(d):
    sw = d["/v1/parent/school_week"]
    assert set(sw) >= {"class_topic", "child_focus", "line_hi", "line_en", "as_of"} and sw["line_hi"] and sw["line_en"]
    datetime.fromisoformat(sw["as_of"])
    if sw["class_topic"]:
        assert set(sw["class_topic"]) >= {"checkpoint_id", "chapter", "title_hi", "title_en", "subject"}
    if sw["child_focus"]:
        assert set(sw["child_focus"]) >= {"checkpoint_id", "title_hi", "title_en", "subject", "state"}
        assert sw["child_focus"]["state"] in STATES

    for path, subject in (("/v1/parent/journey", "numeracy"), ("/v1/parent/journey?subject=literacy", "literacy")):
        j = d[path]
        assert j["subject"] == subject and j["grade"] == 2 and j["milestones"]
        assert set(j) >= {"milestones", "counts", "celebrations", "growth"}
        for m in j["milestones"]:
            assert set(m) >= {"checkpoint_id", "chapter", "title_hi", "title_en", "nipun_ref", "state"}
            assert m["state"] in STATES and m["title_hi"] and m["title_en"]
        states = [m["state"] for m in j["milestones"]]
        assert j["counts"] == {"learned": states.count("learned"), "working": states.count("working"),
                               "total": len(states)}
        assert states.count("next") <= 2
        assert len(j["growth"]) == 6
        weeks = [datetime.fromisoformat(g["week_end"]).date() for g in j["growth"]]
        assert weeks == sorted(weeks) and weeks[-1] == ledger.school_today()
        assert all(isinstance(g["learned"], int) and 0 <= g["learned"] <= len(states) for g in j["growth"])
        for c in j["celebrations"]:
            assert set(c) >= {"checkpoint_id", "title_hi", "title_en", "at", "line_hi", "line_en"}

    t = d["/v1/parent/tips"]["tips"]
    assert len(t) <= 3 and len({x["misconception"] for x in t}) == len(t)
    for x in t:
        assert set(x) >= {"misconception", "checkpoint_id", "title_hi", "title_en", "explain_hi", "explain_en",
                          "game_hi", "game_en", "example", "seen_at"}
        assert x["explain_hi"] and x["explain_en"] and x["game_hi"] and x["game_en"]
        assert tips.get_tip(x["misconception"]) is not None  # reviewed text only

    for m in d["/v1/parent/moments"]["moments"]:
        assert m["kind"] in ("celebration", "catch_up") and m["line_hi"] and m["line_en"]
        if m["kind"] == "celebration":
            assert m["move"] in ("learned", "getting_better") and m["checkpoint_id"] and m["at"]
        else:
            assert set(m) >= {"day", "class_did_hi", "class_did_en", "activity"}
            if m["activity"]:
                assert set(m["activity"]) >= {"id", "title_hi", "title_en", "materials_hi", "materials_en",
                                               "steps_hi", "steps_en", "minutes"}
                assert len(m["activity"]["steps_hi"]) <= 3 and len(m["activity"]["steps_en"]) <= 3

    wk = d["/v1/parent/weekly"]
    assert set(wk) >= {"week_start", "week_end", "practice_days", "voice_sessions", "voice_minutes", "learned",
                       "working_on", "next", "tip", "line_hi", "line_en"}
    ws, we = datetime.fromisoformat(wk["week_start"]).date(), datetime.fromisoformat(wk["week_end"]).date()
    assert ws.weekday() == 0 and we == ws + timedelta(days=6) and ws <= ledger.school_today() <= we
    assert len(wk["learned"]) <= 3 and len(wk["working_on"]) <= 3 and len(wk["next"]) <= 2
    assert wk["practice_days"] >= 0 and wk["voice_sessions"] >= 0 and wk["voice_minutes"] >= 0
    assert wk["line_hi"] and wk["line_en"]


def test_all_routes_for_the_seeded_child(rc, parent_headers):
    d = get_all(rc, parent_headers)
    check_shapes(d)
    assert d["/v1/parent/school_week"]["class_topic"] and d["/v1/parent/school_week"]["child_focus"]
    assert d["/v1/parent/journey"]["counts"]["learned"] >= 1
    assert d["/v1/parent/tips"]["tips"], "seeded child 12 has school misconceptions with reviewed tips"
    assert d["/v1/parent/moments"]["moments"]


def test_all_routes_for_a_brand_new_child(rc, w):
    c = w.child("Nayi")
    d = get_all(rc, c["headers"])
    check_shapes(d)
    for path in ("/v1/parent/journey", "/v1/parent/journey?subject=literacy"):
        j = d[path]
        assert j["counts"]["learned"] == 0 and j["counts"]["working"] == 0 and j["celebrations"] == []
        assert [m["state"] for m in j["milestones"]][:2] == ["next", "next"]
        assert all(g["learned"] == 0 for g in j["growth"])
    assert d["/v1/parent/tips"] == {"tips": []} and d["/v1/parent/moments"] == {"moments": []}
    wk = d["/v1/parent/weekly"]
    assert wk["practice_days"] == 0 and wk["voice_sessions"] == 0 and wk["learned"] == [] and wk["tip"] is None
    assert "Nayi" in wk["line_en"] and "Nayi" in d["/v1/parent/school_week"]["line_en"]


def test_a_brand_new_child_in_a_class_with_no_evidence_gets_a_gentle_week_line(rc, w):
    c = w.child("Khaali")
    sw = rc.get("/v1/parent/school_week", headers=c["headers"]).json()
    assert sw["class_topic"] is None and "Khaali" in sw["line_en"]


# ------------------------------------------------------------------ nothing comparative or numeric
def test_no_group_labels_classmates_or_scores_in_any_text_seeded_child(rc, parent_headers):
    d = get_all(rc, parent_headers)
    body = "\n".join(texts(d))
    assert not FORBIDDEN.search(body), FORBIDDEN.search(body).group(0)
    others = name_tokens([n for n in NAMES_2A + NAMES_3A if n != "कविता"])
    found = others & set(re.findall(r"[ऀ-ॿ]+", body))
    assert not found, f"classmate names in parent text: {found}"
    # the child's own name is used, in Hindi and English lines
    assert "कविता" in body


def test_no_group_labels_or_classmates_when_the_plan_has_groups_and_other_kids(rc, w):
    c = w.child("Kiran")
    mates = [w.child(n) for n in ("Sunita", "Gopal", "Rashmi")]
    today = ledger.school_today()
    groups = [{"key": "weak", "label": "Weak group / कमज़ोर समूह", "label_hi": "कमज़ोर समूह", "checkpoint_id": BORROW,
               "members": [c["id"], mates[0]["id"]], "member_names": ["Kiran", "Sunita"], "activity_id": "act_borrow_sticks"},
              {"key": "strong", "label": "Strong group", "checkpoint_id": CARRY,
               "members": [mates[1]["id"], mates[2]["id"]], "member_names": ["Gopal", "Rashmi"]}]
    with SessionLocal() as db:
        db.add(Plan(school_id=w.school_id, class_id=c["class_id"], subject="numeracy", for_date=today,
                    generated_by="fallback", payload={"groups": groups}))
        db.commit()
    for m in mates:
        add_ev(w, m, BORROW, "incorrect", _ago(days=1))
    add_ev(w, c, BORROW, "incorrect", _ago(days=2), misc="smaller_minus_larger")
    d = get_all(rc, c["headers"])
    body = "\n".join(texts(d))
    assert not FORBIDDEN.search(body), FORBIDDEN.search(body).group(0)
    for n in ("Sunita", "Gopal", "Rashmi", "weak", "strong"):
        assert n.lower() not in body.lower(), n
    sw = d["/v1/parent/school_week"]
    assert sw["child_focus"]["checkpoint_id"] == BORROW  # the plan's topic for the child, shown as a topic only


def test_no_digits_that_look_like_a_score_in_status_lines(rc, parent_headers):
    d = get_all(rc, parent_headers)
    for line in (d["/v1/parent/school_week"]["line_en"], d["/v1/parent/weekly"]["line_en"],
                 *[m["line_en"] for m in d["/v1/parent/moments"]["moments"]]):
        assert not re.search(r"\d+\s*(/|out of|%)", line), line


# ------------------------------------------------------------------ learned comes only from school evidence
def test_home_only_correct_answers_never_make_learned(rc, w):
    c = w.child("HomeOnly")
    for d in range(1, 7):  # six days of perfect home answers on a numeracy topic
        add_ev(w, c, BORROW, "correct", _ago(days=d, hours=2), source="home_voice")
        add_ev(w, c, BORROW, "correct", _ago(days=d, hours=1), source="home_tap")
    d = get_all(rc, c["headers"])
    j = d["/v1/parent/journey"]
    state = next(m["state"] for m in j["milestones"] if m["checkpoint_id"] == BORROW)
    assert state == "working" and j["counts"]["learned"] == 0 and j["celebrations"] == []
    assert not [m for m in d["/v1/parent/moments"]["moments"] if m["kind"] == "celebration"]
    assert d["/v1/parent/weekly"]["learned"] == []
    assert all(g["learned"] == 0 for g in j["growth"])
    assert d["/v1/parent/school_week"]["child_focus"] is None or \
        d["/v1/parent/school_week"]["child_focus"]["state"] != "learned"


def test_a_real_voice_session_of_perfect_answers_never_makes_learned(rc, w):
    c = w.child("VoiceOnly")
    h = c["headers"]
    s = start(rc, h)
    t = {"next_item": s["item"]}
    for _ in range(30):
        t = turn(rc, h, s["id"], t["next_item"]["id"], right_answer(full_item(s["id"], t["next_item"]["id"])))
    with SessionLocal() as db:
        n = len(list(db.scalars(select(Evidence).where(Evidence.child_id == c["id"], Evidence.source == "home_voice"))))
    assert n >= 25  # plenty of home evidence was written
    d = get_all(rc, h)
    for path in ("/v1/parent/journey", "/v1/parent/journey?subject=literacy"):
        j = d[path]
        assert j["counts"]["learned"] == 0 and j["celebrations"] == [] and "learned" not in {
            m["state"] for m in j["milestones"]}
    assert not [m for m in d["/v1/parent/moments"]["moments"] if m["kind"] == "celebration"]
    assert d["/v1/parent/weekly"]["learned"] == [] and d["/v1/parent/weekly"]["voice_sessions"] == 1
    assert d["/v1/parent/weekly"]["practice_days"] == 1
    # ...and the home practice does show as "working" on the literacy path
    lit = d["/v1/parent/journey?subject=literacy"]
    assert lit["counts"]["working"] >= 1


def test_school_evidence_does_make_learned_and_celebrates(rc, w):
    c = w.child("SchoolLearns")
    for d in (3, 2, 1):
        add_ev(w, c, BORROW, "correct", _ago(days=d))
    d = get_all(rc, c["headers"])
    j = d["/v1/parent/journey"]
    assert next(m["state"] for m in j["milestones"] if m["checkpoint_id"] == BORROW) == "learned"
    assert j["counts"]["learned"] == 1
    assert [x["checkpoint_id"] for x in j["celebrations"]] == [BORROW]
    assert "SchoolLearns" in j["celebrations"][0]["line_en"] and "⭐" in j["celebrations"][0]["line_en"]
    cel = [m for m in d["/v1/parent/moments"]["moments"] if m["kind"] == "celebration"]
    assert [m["checkpoint_id"] for m in cel] == [BORROW] and cel[0]["move"] == "learned"
    assert [x["title_en"] for x in d["/v1/parent/weekly"]["learned"]] and j["growth"][-1]["learned"] == 1
    assert j["growth"][0]["learned"] == 0
    # home evidence on top does not undo or double it
    add_ev(w, c, BORROW, "correct", _ago(hours=1), source="home_voice")
    j2 = rc.get("/v1/parent/journey", headers=c["headers"]).json()
    assert j2["counts"]["learned"] == 1


def test_learned_long_ago_is_no_celebration(rc, w):
    c = w.child("OldNews")
    for d in (20, 19, 18):
        add_ev(w, c, BORROW, "correct", _ago(days=d))
    # stays on track (the evidence is old but the decay keeps it above the bar) or fades; either way no celebration
    d = get_all(rc, c["headers"])
    assert d["/v1/parent/journey"]["celebrations"] == []


def test_getting_better_moment(rc, w):
    c = w.child("Better")
    add_ev(w, c, BORROW, "incorrect", _ago(days=9))
    add_ev(w, c, BORROW, "incorrect", _ago(days=8))
    add_ev(w, c, BORROW, "correct", _ago(days=2))
    moments = rc.get("/v1/parent/moments", headers=c["headers"]).json()["moments"]
    gb = [m for m in moments if m.get("move") == "getting_better"]
    assert len(gb) == 1 and gb[0]["kind"] == "celebration" and gb[0]["checkpoint_id"] == BORROW
    assert "Better" in gb[0]["line_en"] and "🌱" in gb[0]["line_en"]


def test_catch_up_moment_after_an_absent_day(rc, w):
    c = w.child("Absent")
    mate = w.child("Present")
    today = ledger.school_today()
    yesterday = today - timedelta(days=1)
    with SessionLocal() as db:
        db.add(Attendance(school_id=w.school_id, class_id=c["class_id"], child_id=c["id"], day=yesterday,
                          present=False))
        db.add(Plan(school_id=w.school_id, class_id=c["class_id"], subject="numeracy", for_date=yesterday,
                    generated_by="fallback", payload={"groups": [
                        {"key": "g1", "checkpoint_id": BORROW, "members": [mate["id"]], "activity_id": "act_borrow_sticks"}]}))
        db.commit()
    moments = rc.get("/v1/parent/moments", headers=c["headers"]).json()["moments"]
    cu = [m for m in moments if m["kind"] == "catch_up"]
    assert len(cu) == 1 and cu[0]["day"] == yesterday.isoformat()
    assert "Absent" in cu[0]["line_en"] and cu[0]["class_did_en"] and "yesterday" in cu[0]["class_did_en"]
    assert cu[0]["activity"] is None or cu[0]["activity"]["minutes"] == 5
    assert "Present" not in json.dumps(moments)
    # a child who was present gets no catch-up
    assert not [m for m in rc.get("/v1/parent/moments", headers=mate["headers"]).json()["moments"]
                if m["kind"] == "catch_up"]


def test_absent_four_days_ago_is_too_old_for_catch_up(rc, w):
    c = w.child("LongAgo")
    with SessionLocal() as db:
        db.add(Attendance(school_id=w.school_id, class_id=c["class_id"], child_id=c["id"],
                          day=ledger.school_today() - timedelta(days=4), present=False))
        db.commit()
    assert rc.get("/v1/parent/moments", headers=c["headers"]).json() == {"moments": []}


# ------------------------------------------------------------------ tips
def test_tips_reviewed_only_max_three_one_per_mistake_school_evidence_only(rc, w, monkeypatch):
    def tip(mid, reviewed=True):
        return {"id": mid, "checkpoint_ids": [], "explain_hi": f"हि {mid}", "explain_en": f"en {mid}",
                "game_hi": "खेल", "game_en": "game", "example": "52 − 17", "reviewed": reviewed}
    fake = {m: tip(m) for m in ("m1", "m2", "m3", "m4", "m_home", "m_old", "m_done")}
    fake["m_unrev"] = tip("m_unrev", reviewed=False)
    monkeypatch.setattr(tips, "_tips", lambda: fake)
    c = w.child("Tippy")
    add_ev(w, c, BORROW, "incorrect", _ago(days=1), misc="m1")
    add_ev(w, c, BORROW, "incorrect", _ago(days=2), misc="m1")  # a repeat: still one tip
    add_ev(w, c, BORROW, "incorrect", _ago(days=3), misc="m2")
    add_ev(w, c, CARRY, "incorrect", _ago(days=4), misc="m3")
    add_ev(w, c, CARRY, "incorrect", _ago(days=5), misc="m4")
    add_ev(w, c, PV, "incorrect", _ago(hours=5), misc="m_unrev")        # newest, but unreviewed
    add_ev(w, c, PV, "incorrect", _ago(hours=4), misc="no_such_tip")    # unknown id
    add_ev(w, c, PV, "incorrect", _ago(hours=3), misc="m_home", source="home_tap")  # home evidence is not school
    add_ev(w, c, BORROW, "incorrect", _ago(days=40), misc="m_old")      # older than 30 days
    got = rc.get("/v1/parent/tips", headers=c["headers"]).json()["tips"]
    assert [t["misconception"] for t in got] == ["m1", "m2", "m3"]  # newest first, max 3, one each
    assert got[0]["seen_at"] > got[1]["seen_at"] > got[2]["seen_at"]
    assert {"m_unrev", "no_such_tip", "m_home", "m_old", "m4"}.isdisjoint(t["misconception"] for t in got)
    # the weekly summary shows at most the first tip
    assert rc.get("/v1/parent/weekly", headers=c["headers"]).json()["tip"]["misconception"] == "m1"
    # once the topic is learned at school its tips go away
    for d in range(1, 16):
        add_ev(w, c, BORROW, "correct", _ago(hours=d))
    again = [t["misconception"] for t in rc.get("/v1/parent/tips", headers=c["headers"]).json()["tips"]]
    assert "m1" not in again and "m2" not in again


def test_tips_never_include_other_childs_mistakes(rc, w, monkeypatch):
    monkeypatch.setattr(tips, "_tips", lambda: {"only_other": {"id": "only_other", "explain_hi": "x", "explain_en": "x",
                                                               "game_hi": "g", "game_en": "g", "example": "",
                                                               "reviewed": True}})
    a, b = w.child("TipA"), w.child("TipB")
    add_ev(w, b, BORROW, "incorrect", _ago(days=1), misc="only_other")
    assert rc.get("/v1/parent/tips", headers=a["headers"]).json() == {"tips": []}


# ------------------------------------------------------------------ route inputs
def test_unknown_subject_is_422(rc, parent_headers):
    assert rc.get("/v1/parent/journey?subject=" + "x" * 17, headers=parent_headers).status_code == 422
    assert rc.get("/v1/parent/journey?subject=", headers=parent_headers).status_code in (200, 422)


@pytest.mark.parametrize("subject", ["nonsense", "drop table", "🙂"])
def test_unknown_subject_param_is_rejected(rc, parent_headers, subject):
    r = rc.get("/v1/parent/journey", params={"subject": subject}, headers=parent_headers)
    assert r.status_code == 422, (r.status_code, r.text[:120])


@pytest.mark.parametrize("subject", ["maths", "NUMERACY", "hindi", "english", " English "])
def test_subject_aliases_and_case_are_accepted(rc, parent_headers, subject):
    """The same names and aliases the teacher routes take (services/subjects.py)."""
    r = rc.get("/v1/parent/journey", params={"subject": subject}, headers=parent_headers)
    assert r.status_code == 200, (r.status_code, r.text[:120])


def test_journey_never_500_for_odd_subjects(rc, parent_headers):
    for subject in ("nonsense", "drop table;--", "🙂", "%", "a b", "\x00"):
        assert rc.get("/v1/parent/journey", params={"subject": subject}, headers=parent_headers).status_code in (
            200, 422)


# ------------------------------------------------------------------ weekly: IST week boundaries
def _voice_at(w, child_id, utc_naive):
    with SessionLocal() as db:
        db.add(VoiceSession(school_id=w.school_id, child_id=child_id, lang="hi", status="ended",
                            started_at=utc_naive, state={"elapsed_s": 600.0}, report={"minutes": 10.0}))
        db.commit()


def test_weekly_week_boundaries_are_in_ist(w):
    c = w.child("Borders")
    # IST week of Mon 26 Oct 2026 = Sun 25 Oct 18:30 UTC (incl) .. Sun 1 Nov 18:30 UTC (excl)
    _voice_at(w, c["id"], datetime(2026, 10, 25, 18, 29))   # Sun 23:59 IST -> previous week
    _voice_at(w, c["id"], datetime(2026, 10, 25, 18, 31))   # Mon 00:01 IST -> this week
    _voice_at(w, c["id"], datetime(2026, 10, 29, 3, 0))     # Thu 08:30 IST
    _voice_at(w, c["id"], datetime(2026, 11, 1, 18, 29))    # Sun 23:59 IST -> this week
    _voice_at(w, c["id"], datetime(2026, 11, 1, 18, 31))    # Mon 00:01 IST (2 Nov) -> next week
    with SessionLocal() as db:
        mid = insights.weekly(db, c["id"], now=datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc))
        assert (mid["week_start"], mid["week_end"]) == ("2026-10-26", "2026-11-01")
        assert mid["voice_sessions"] == 3 and mid["voice_minutes"] == 30
        assert mid["practice_days"] == 3  # Mon 26th, Thu 29th, Sun 1st (IST days)
        # Sunday 23:45 IST is still the same week; 00:15 IST on Monday is the next
        sun = insights.weekly(db, c["id"], now=datetime(2026, 11, 1, 18, 15, tzinfo=timezone.utc))
        mon = insights.weekly(db, c["id"], now=datetime(2026, 11, 1, 18, 45, tzinfo=timezone.utc))
        assert sun["week_start"] == "2026-10-26" and sun["voice_sessions"] == 3
        assert mon["week_start"] == "2026-11-02" and mon["week_end"] == "2026-11-08"
        assert mon["voice_sessions"] == 1 and mon["practice_days"] == 1
        prev = insights.weekly(db, c["id"], now=datetime(2026, 10, 25, 18, 15, tzinfo=timezone.utc))
        assert prev["week_start"] == "2026-10-19" and prev["voice_sessions"] == 1


def test_weekly_counts_voice_minutes_from_the_report(rc, w):
    c = w.child("Minutes")
    s = start(rc, c["headers"])
    d = rc.get("/v1/parent/weekly", headers=c["headers"]).json()
    assert d["voice_sessions"] == 1 and d["practice_days"] == 1 and d["voice_minutes"] == 0
    assert "1 day" in d["line_en"]
    # another child's sessions never count
    other = w.child("NotMinutes")
    assert rc.get("/v1/parent/weekly", headers=other["headers"]).json()["voice_sessions"] == 0
    assert s["id"]


def test_journey_growth_week_ends_are_ist_days(rc, parent_headers):
    j = rc.get("/v1/parent/journey", headers=parent_headers).json()
    assert j["growth"][-1]["week_end"] == ledger.school_today().isoformat()
    ends = [datetime.fromisoformat(g["week_end"]).date() for g in j["growth"]]
    assert all((b - a).days == 7 for a, b in zip(ends, ends[1:]))
