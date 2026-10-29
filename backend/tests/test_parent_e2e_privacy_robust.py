"""Parent app e2e: PRIVACY (data deletion, isolation, what is stored) and ROBUSTNESS (bad input, concurrency).

Sandbox school only. Every case that could crash the server is checked through a client that turns an
unhandled exception into a 500 response, and a 500 is always a failure.
"""
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models.tables import Evidence, HomeSession, ParentAccount, VoiceSession, VoiceTurn

from .test_parent_e2e_common import (  # noqa: F401  (fixtures)
    WRONG, end, full_item, rc, right_answer, silent_wav, skip, start, tok, turn, w,
)

BORROW = "N.G2.sub_2digit_borrow"


def add_ev(w, child, cp, result, source, days=1, misc=None):
    with SessionLocal() as db:
        db.add(Evidence(school_id=w.school_id, class_id=child["class_id"], child_id=child["id"], checkpoint_id=cp,
                        result=result, source=source, confidence=0.9, status="confirmed", misconception=misc,
                        at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)))
        db.commit()


def populate(rc, w, child):
    """Home evidence (both sources), school evidence, a legacy home session and two voice sessions with turns."""
    h = child["headers"]
    add_ev(w, child, BORROW, "correct", "home_voice")
    add_ev(w, child, BORROW, "incorrect", "home_tap")
    add_ev(w, child, BORROW, "correct", "teacher_tap", days=2)
    add_ev(w, child, "N.G2.add_2digit_carry", "incorrect", "photo_work", days=3)
    with SessionLocal() as db:
        db.add(HomeSession(school_id=w.school_id, child_id=child["id"], evidence_count=1, summary_hi="x"))
        db.commit()
    ids = []
    for lang in ("hi", "en"):
        s = start(rc, h, lang)
        t = turn(rc, h, s["id"], s["item"]["id"], right_answer(full_item(s["id"], s["item"]["id"])))
        turn(rc, h, s["id"], t["next_item"]["id"], WRONG)
        ids.append(s["id"])
    end(rc, h, ids[0])  # one ended with a report, one left active
    return ids


def counts(child_id):
    with SessionLocal() as db:
        vs = [v.id for v in db.scalars(select(VoiceSession).where(VoiceSession.child_id == child_id))]
        return {
            "home_ev": db.scalar(select(func.count()).select_from(Evidence).where(
                Evidence.child_id == child_id, Evidence.source.in_(("home_voice", "home_tap")))),
            "school_ev": db.scalar(select(func.count()).select_from(Evidence).where(
                Evidence.child_id == child_id, Evidence.source.not_in(("home_voice", "home_tap")))),
            "home_sessions": db.scalar(select(func.count()).select_from(HomeSession).where(
                HomeSession.child_id == child_id)),
            "voice_sessions": len(vs),
            "voice_turns": db.scalar(select(func.count()).select_from(VoiceTurn).where(
                VoiceTurn.session_id.in_(vs))) if vs else 0,
            "account": db.scalar(select(func.count()).select_from(ParentAccount).where(
                ParentAccount.child_id == child_id)),
        }


# ------------------------------------------------------------------ 6. privacy
def test_delete_removes_this_childs_home_data_only(rc, w):
    a, b = w.child("DelA"), w.child("DelB")
    ids_a = populate(rc, w, a)
    ids_b = populate(rc, w, b)
    before_a, before_b = counts(a["id"]), counts(b["id"])
    assert before_a["home_ev"] >= 3 and before_a["voice_sessions"] == 2 and before_a["voice_turns"] >= 8
    assert before_a["home_sessions"] == 1 and before_a["school_ev"] == 2
    r = rc.delete("/v1/parent/child/data", headers=a["headers"])
    assert r.status_code == 200 and r.json() == {"deleted": True}
    after_a = counts(a["id"])
    assert after_a["home_ev"] == 0 and after_a["home_sessions"] == 0
    assert after_a["voice_sessions"] == 0 and after_a["voice_turns"] == 0
    assert after_a["school_ev"] == before_a["school_ev"], "teacher-confirmed school evidence is the school's, not deleted"
    assert after_a["account"] == 1
    assert counts(b["id"]) == before_b, "another child's data must be untouched"
    # the API agrees: nothing left for A, everything left for B
    assert rc.get("/v1/parent/voice/sessions", headers=a["headers"]).json() == []
    assert rc.get("/v1/parent/history", headers=a["headers"]).json() == []
    for sid in ids_a:
        assert rc.get(f"/v1/parent/voice/sessions/{sid}", headers=a["headers"]).status_code == 404
        assert rc.get(f"/v1/voice_sessions/{sid}", headers=w.teacher_headers).status_code == 404
    assert rc.get("/v1/parent/child", headers=a["headers"]).json()["streak"] == 0
    assert {x["id"] for x in rc.get("/v1/parent/voice/sessions", headers=b["headers"]).json()} == set(ids_b)
    # still signed in, and can practise again afterwards
    assert start(rc, a["headers"])["item"]
    # deleting twice is harmless
    assert rc.delete("/v1/parent/child/data", headers=a["headers"]).json() == {"deleted": True}


def test_delete_leaves_no_home_trace_in_insights(rc, w):
    c = w.child("Trace")
    populate(rc, w, c)
    rc.delete("/v1/parent/child/data", headers=c["headers"])
    wk = rc.get("/v1/parent/weekly", headers=c["headers"]).json()
    assert wk["voice_sessions"] == 0 and wk["voice_minutes"] == 0 and wk["practice_days"] == 0


def test_delete_needs_a_parent_token(rc, teacher_headers):
    assert rc.delete("/v1/parent/child/data").status_code == 401
    assert rc.delete("/v1/parent/child/data", headers=teacher_headers).status_code == 403


def test_parent_sees_only_their_own_child_everywhere(rc, w):
    a, b = w.child("OwnA"), w.child("OwnB")
    s = start(rc, b["headers"])
    for path in ("/v1/parent/child", "/v1/parent/pack", "/v1/parent/teacher_note", "/v1/parent/school_week",
                 "/v1/parent/weekly", "/v1/parent/moments", "/v1/parent/tips", "/v1/parent/journey"):
        body = rc.get(path, headers=a["headers"], params={"child_id": b["id"], "child_roll": b["roll"]})
        assert body.status_code == 200, path
        assert "OwnB" not in body.text, path
    assert rc.get("/v1/parent/child", headers=a["headers"]).json()["child"]["id"] == a["id"]
    assert rc.get("/v1/parent/voice/sessions", headers=a["headers"]).json() == []
    assert rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=a["headers"]).status_code == 404
    # legacy session ids too
    hs = rc.post("/v1/parent/sessions", headers=b["headers"]).json()["session_id"]
    for path in (f"/v1/parent/sessions/{hs}/end",):
        assert rc.post(path, headers=a["headers"]).status_code == 404
    assert rc.post("/v1/parent/sessions/sync", headers=a["headers"],
                   json={"started_at": "2026-10-01T10:00:00Z", "session_id": hs}).status_code == 404
    # a parent token cannot read the teacher's view of any child
    assert rc.get(f"/v1/children/{b['id']}/voice_sessions", headers=a["headers"]).status_code == 403


def test_audio_is_never_stored(rc, w):
    c = w.child("NoAudio")
    s = start(rc, c["headers"])
    up = get_settings().upload_dir
    before = sorted(p.name for p in up.rglob("*"))
    turn(rc, c["headers"], s["id"], s["item"]["id"], None, audio=silent_wav(1.0))
    turn(rc, c["headers"], s["id"], s["item"]["id"], WRONG, audio=silent_wav(1.0))
    assert sorted(p.name for p in up.rglob("*")) == before
    cols = {col.name for col in VoiceTurn.__table__.columns}
    assert not {"audio", "audio_ref", "audio_path", "blob"} & cols


def test_stored_text_is_only_what_the_promise_allows(rc, w):
    """Observation: the consent text promises 'only first name, roll number and learning evidence'. Voice sessions also
    keep the child's recognised words (transcript lines); phone and PIN are stored hashed. Record what is there."""
    c = w.child("Stored", phone="9555555555")
    s = start(rc, c["headers"])
    turn(rc, c["headers"], s["id"], s["item"]["id"], "मेरा नाम कुछ भी")
    with SessionLocal() as db:
        p = db.get(ParentAccount, c["parent_id"])
        assert "9555555555" not in p.phone_hash and "0000" not in p.pin_hash
        texts = [t.text for t in db.scalars(select(VoiceTurn).where(VoiceTurn.session_id == s["id"]))]
    assert any("मेरा नाम कुछ भी" in t for t in texts)  # transcripts ARE stored: wording gap vs. the consent text


@pytest.mark.parametrize("kind", ["build_word", "say_sound", "answer_question"])
def test_first_wrong_try_does_not_reveal_the_answer_in_words_or_errors(rc, w, kind):
    from .test_parent_e2e_voice import reach_kind
    # say_sound is rare in the Hindi letter stage; English sessions always start at letters
    c, h, s, item, tally, evid = reach_kind(rc, w, "en" if kind == "say_sound" else "hi", kind)
    f = full_item(s["id"], item["id"])
    answers = [a for a in [f.get("target")] + list(f.get("keywords") or []) + list(f.get("accept") or []) if a]
    t = turn(rc, h, s["id"], item["id"], WRONG)
    assert t["attempt"] == 2
    shown = json.dumps([t["words"], t["errors"], [l.get("words") for l in t["transcript_append"]]], ensure_ascii=False)
    leaked = [a for a in answers if a in shown]
    assert not leaked, f"{kind}: answer {leaked} is in the first wrong-try response"


# ------------------------------------------------------------------ 7. robustness
def post_turn(rc, h, sid, meta, **kw):
    return rc.post(f"/v1/parent/voice/sessions/{sid}/turn", headers=h, data={"meta": meta}, **kw)


@pytest.fixture
def live(rc, w):
    c = w.child("Rob")
    s = start(rc, c["headers"])
    return c, s


@pytest.mark.parametrize("meta", ["", "{", "null", "[]", "42", '"x"', "{}", '{"item_id": ""}',
                                  '{"item_id": "a"}', '{"client_turn_id": "a"}', '{"item_id": 1, "client_turn_id": "a"}',
                                  '{"item_id": "a", "client_turn_id": ""}',
                                  '{"item_id": "a", "client_turn_id": "' + "z" * 65 + '"}',
                                  '{"item_id": "' + "z" * 81 + '", "client_turn_id": "a"}',
                                  '{"item_id": "a", "client_turn_id": "b", "transcript": 5}',
                                  '{"item_id": "a", "client_turn_id": "b", "duration_s": -1}',
                                  '{"item_id": "a", "client_turn_id": "b", "duration_s": 601}',
                                  '{"item_id": "a", "client_turn_id": "b", "duration_s": "fast"}',
                                  '{"item_id": "a", "client_turn_id": "b", "duration_s": NaN}',
                                  '\x00', "{'item_id': 'a'}"])
def test_malformed_meta_is_422(rc, live, meta):
    c, s = live
    r = post_turn(rc, c["headers"], s["id"], meta)
    assert r.status_code == 422, (r.status_code, r.text[:200])


def test_missing_meta_or_wrong_content_type_is_422(rc, live):
    c, s = live
    url = f"/v1/parent/voice/sessions/{s['id']}/turn"
    assert rc.post(url, headers=c["headers"]).status_code == 422
    assert rc.post(url, headers=c["headers"], data={}).status_code == 422
    assert rc.post(url, headers=c["headers"], json={"item_id": "a"}).status_code == 422
    assert rc.post(url, headers=c["headers"], files={"audio": ("a.wav", silent_wav(), "audio/wav")}).status_code == 422
    # audio sent as a plain text field instead of a file
    r = rc.post(url, headers=c["headers"], data={"meta": json.dumps({"item_id": "x", "client_turn_id": "y"}),
                                                 "audio": "not a file"})
    assert r.status_code in (409, 422)


def test_missing_fields_on_skip_start_end_are_422(rc, live):
    c, s = live
    h = c["headers"]
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h, json={}).status_code == 422
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h, json={"item_id": ""}).status_code == 422
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h, json={"item_id": "x" * 81}).status_code == 422
    assert rc.post(f"/v1/parent/voice/sessions/{s['id']}/skip", headers=h).status_code == 422
    r = rc.post("/v1/parent/voice/sessions", headers={**h, "Content-Type": "application/json"}, content=b"{bad")
    assert r.status_code == 422
    r = rc.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers={**h, "Content-Type": "application/json"},
                content=b"garbage")
    assert r.status_code == 422


def test_oversized_audio_is_413_and_does_not_burn_a_try(rc, live):
    c, s = live
    limit = get_settings().max_audio_bytes
    big = b"\x00" * (limit + 1)
    r = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": s["item"]["id"], "client_turn_id": "big1"}),
                  files={"audio": ("big.wav", big, "audio/wav")})
    assert r.status_code == 413, r.status_code
    again = turn(rc, c["headers"], s["id"], s["item"]["id"], WRONG)
    assert again["attempt"] == 2  # exactly one wrong try so far
    # at the limit it is accepted (silence)
    ok = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": s["item"]["id"], "client_turn_id": "big2"}),
                   files={"audio": ("ok.wav", b"\x00" * limit, "audio/wav")})
    assert ok.status_code == 200 and ok.json()["asr"] == "silent"


def test_legacy_turn_oversized_audio_is_413(rc, w):
    c = w.child("OldBig")
    h = c["headers"]
    j = rc.post("/v1/parent/sessions", headers=h).json()
    meta = json.dumps({"index": 0, "attempt": 0, "activity_ref": j["activity"]["ref"]})
    r = rc.post(f"/v1/parent/sessions/{j['session_id']}/turn", headers=h, data={"meta": meta},
                files={"audio": ("b.wav", b"\x00" * (get_settings().max_audio_bytes + 1), "audio/wav")})
    assert r.status_code == 413


def test_very_long_transcript(rc, live):
    c, s = live
    item = s["item"]["id"]
    ok = turn(rc, c["headers"], s["id"], item, "क" * 2000)  # exactly the limit
    assert ok["verdict"] in ("wrong", "close") and ok["attempt"] == 2
    over = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": item, "client_turn_id": "x", "transcript": "क" * 2001}))
    assert over.status_code == 422
    t = turn(rc, c["headers"], s["id"], item, "word " * 400)  # 2000 chars of ordinary words
    assert t["attempt"] == 3
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=c["headers"])
    assert d.status_code == 200


STRANGE = ["😀🙂👍🏽", "क्‍ष त्र ज्ञ", "‮‬ right-to-left", "​‌‍zero width", "ȩ̶͓́̈ combining", "𝔘𝔫𝔦𝔠𝔬𝔡𝔢",
           "' OR 1=1 --", "'; DROP TABLE voice_turns; --", "\" onerror=alert(1) <script>", "{{7*7}} ${7*7} %s %d {name}",
           "\\u0000 \\n \\\\", "a\x00b", "\n\n\n", "<>&\"'", "../../../../etc/passwd", "NULL", "None", "true"]


@pytest.mark.parametrize("text", STRANGE)
def test_unicode_emoji_and_sqlish_transcripts_never_500(rc, w, text):
    c = w.child("Odd")
    s = start(rc, c["headers"])
    t = turn(rc, c["headers"], s["id"], s["item"]["id"], text)
    assert t["verdict"] in ("wrong", "close", "silent", "none", "correct")
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=c["headers"])
    assert d.status_code == 200
    assert "{name}" not in json.dumps(d.json(), ensure_ascii=False).replace(text, "")  # only the child's own text may keep it
    assert end(rc, c["headers"], s["id"])["session_id"] == s["id"]
    assert rc.get("/v1/parent/voice/sessions", headers=c["headers"]).status_code == 200


@pytest.mark.parametrize("val", ["' OR 1=1 --", "\x00", "😀", "a" * 64, "../x", "{name}"])
def test_odd_item_ids_and_turn_ids(rc, live, val):
    c, s = live
    r = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": val, "client_turn_id": "ok-1"}))
    assert r.status_code == 409  # not the current item
    r = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": s["item"]["id"], "client_turn_id": val,
                                                         "transcript": WRONG}))
    assert r.status_code == 200, (r.status_code, r.text[:200])
    again = post_turn(rc, c["headers"], s["id"], json.dumps({"item_id": s["item"]["id"], "client_turn_id": val,
                                                             "transcript": WRONG}))
    assert again.json() == r.json()  # the odd id still replays


@pytest.mark.xfail(strict=True, reason="BUG (low): the API fills {name} over the whole payload, including the child's own "
                                       "recognised words, so a child (or the recogniser) saying '{name}' sees it replaced "
                                       "by their first name in the transcript (api/voice.py:_fill via _public/_detail)")
def test_user_text_is_never_interpreted_as_a_template(rc, w):
    c = w.child("Templ")
    s = start(rc, c["headers"])
    t = turn(rc, c["headers"], s["id"], s["item"]["id"], "{name} {0} %s {{x}}")
    assert "Templ" not in t["heard"]
    d = rc.get(f"/v1/parent/voice/sessions/{s['id']}", headers=c["headers"]).json()
    echoed = [l["text"] for l in d["session"]["transcript"] if l["role"] == "child"]
    assert all("Templ" not in x for x in echoed), echoed  # the child's literal "{name}" is not replaced by the name


@pytest.mark.parametrize("path", ["/v1/parent/voice/sessions/99999999999999999999",
                                  "/v1/parent/voice/sessions/9223372036854775808"])
def test_huge_session_id_is_404_not_500(rc, parent_headers, path):
    assert rc.get(path, headers=parent_headers).status_code in (404, 422)


def test_negative_and_zero_session_ids_are_404(rc, parent_headers, teacher_headers):
    for sid in (0, -1):
        assert rc.get(f"/v1/parent/voice/sessions/{sid}", headers=parent_headers).status_code == 404
        assert rc.get(f"/v1/voice_sessions/{sid}", headers=teacher_headers).status_code == 404
    assert rc.get("/v1/children/0/voice_sessions", headers=teacher_headers).status_code == 404


def test_two_threads_uploading_the_identical_turn_never_500(w):
    """The retry-after-timeout case: the same client_turn_id arrives twice at once. Both must be answered
    (200, identical) and the try must be counted once."""
    outcomes = []
    for rnd in range(10):
        c = w.child(f"Race{rnd}")
        h = c["headers"]
        s = start(TestClient(app, raise_server_exceptions=False), h)
        item = s["item"]["id"]
        meta = json.dumps({"item_id": item, "client_turn_id": f"race-{rnd}", "transcript": WRONG})
        barrier = threading.Barrier(2)
        res = [None, None]

        def fire(i):
            cl = TestClient(app, raise_server_exceptions=False)
            barrier.wait()
            res[i] = cl.post(f"/v1/parent/voice/sessions/{s['id']}/turn", headers=h, data={"meta": meta})
        ths = [threading.Thread(target=fire, args=(i,)) for i in range(2)]
        [t.start() for t in ths]
        [t.join(30) for t in ths]
        codes = sorted(r.status_code for r in res)
        with SessionLocal() as db:
            st = db.get(VoiceSession, s["id"]).state
            tries = len(st["outcomes"][item]["attempts"])
            rows = db.scalar(select(func.count()).select_from(VoiceTurn).where(
                VoiceTurn.session_id == s["id"], VoiceTurn.client_turn_id == f"race-{rnd}"))
        outcomes.append((codes, tries, rows, res[0].json() == res[1].json() if codes == [200, 200] else None))
    bad = [o for o in outcomes if o[0] != [200, 200] or o[1] != 1 or o[2] != 1 or o[3] is not True]
    assert not bad, f"concurrent identical uploads misbehaved: {bad}"


def test_concurrent_start_and_end_never_500(w):
    c = w.child("Busy")
    h = c["headers"]
    cl = TestClient(app, raise_server_exceptions=False)
    s = start(cl, h)
    codes = []

    def go(fn):
        codes.append(fn(TestClient(app, raise_server_exceptions=False)).status_code)
    fns = [lambda x: x.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h),
           lambda x: x.post(f"/v1/parent/voice/sessions/{s['id']}/end", headers=h),
           lambda x: x.get(f"/v1/parent/voice/sessions/{s['id']}", headers=h),
           lambda x: x.post("/v1/parent/voice/sessions", headers=h, json={"lang": "en"}),
           lambda x: x.get("/v1/parent/voice/sessions", headers=h)]
    ths = [threading.Thread(target=go, args=(f,)) for f in fns]
    [t.start() for t in ths]
    [t.join(30) for t in ths]
    assert len(codes) == 5 and all(code == 200 for code in codes), codes


def test_simultaneous_logins_never_500(w):
    c = w.child("Login", phone="9666666666", pin="1212")
    codes = []

    def go():
        r = TestClient(app, raise_server_exceptions=False).post("/v1/parent/login", json={
            "school_code": w.code, "child_roll": c["roll"], "parent_phone": "9666666666", "pin": "1212"})
        codes.append(r.status_code)
    ths = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ths]
    [t.join(60) for t in ths]
    assert codes == [200] * 6


def test_no_500_on_any_parent_route_with_junk_query_strings(rc, parent_headers):
    for path in ("/v1/parent/child", "/v1/parent/school_week", "/v1/parent/tips", "/v1/parent/moments",
                 "/v1/parent/weekly", "/v1/parent/history", "/v1/parent/pack", "/v1/parent/voice/sessions"):
        r = rc.get(path + "?x=%00&y=" + "a" * 5000 + "&z[]=1", headers=parent_headers)
        assert r.status_code == 200, (path, r.status_code)
