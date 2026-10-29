"""Parent app e2e: AUTH/GATE, HOME and the legacy practice routes kept for installed APKs.

Read-only on DEMO; everything that writes uses the sandbox school (see test_parent_e2e_common.py).
Known production bugs are marked `xfail(strict=True)` with a "BUG:" reason, so the suite stays green and
flips red the moment one is fixed (then drop the marker).
"""
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models.tables import HomeSession, ParentAccount, VoiceSession

from .test_parent_e2e_common import DEMO_PARENT, World, end, skip, start, tok, turn


@pytest.fixture(scope="module")
def rc():
    """A client that turns server errors into 500 responses (so a crash is a FAIL line, not an exception)."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def w(rc):
    world = World()
    yield world
    world.cleanup()


def login(rc, **over):
    return rc.post("/v1/parent/login", json={**DEMO_PARENT, **over})


# ------------------------------------------------------------------ 1. login
def test_login_ok(rc):
    r = login(rc)
    assert r.status_code == 200
    j = r.json()
    assert j["token"] and j["child"]["roll_no"] == 12 and j["child"]["first_name"] == "कविता"
    assert set(j["child"]) == {"id", "first_name", "roll_no", "class"}


@pytest.mark.parametrize("over", [{"pin": "1111"}, {"parent_phone": "9876500001"}, {"child_roll": 11},
                                  {"child_roll": 9999}, {"school_code": "NOPE"}, {"pin": ""},
                                  {"parent_phone": ""}, {"pin": "0000 "}, {"pin": "x" * 500}])
def test_login_bad_credentials_401(rc, over):
    # an over-long PIN is refused at validation (422) before it is ever compared
    assert login(rc, **over).status_code in ((401, 422) if len(over.get("pin", "")) > 12 else (401,))


def test_login_lowercase_and_padded_school_code(rc):
    assert login(rc, school_code="demo").status_code == 200
    assert login(rc, school_code="  Demo ").status_code == 200


@pytest.mark.parametrize("phone", ["+91 98765 00000", "+919876500000", "98765-00000", "91 9876500000",
                                   "(98765) 00000", "09876500000"])
def test_login_phone_formats(rc, phone):
    assert login(rc, parent_phone=phone).status_code == 200


def test_login_roll_as_string_and_missing_fields(rc):
    assert login(rc, child_roll="12").status_code == 200
    for k in DEMO_PARENT:
        body = {kk: v for kk, v in DEMO_PARENT.items() if kk != k}
        assert rc.post("/v1/parent/login", json=body).status_code == 422, k
    assert rc.post("/v1/parent/login", json={}).status_code == 422
    assert rc.post("/v1/parent/login", content=b"not json",
                   headers={"Content-Type": "application/json"}).status_code == 422
    assert login(rc, child_roll="abc").status_code == 422


@pytest.mark.parametrize("roll", [0, -1, 2 ** 31, 2 ** 63 - 1])
def test_login_extreme_roll_never_500(rc, roll):
    assert login(rc, child_roll=roll).status_code in (401, 422)


@pytest.mark.parametrize("roll", [2 ** 63, 10 ** 30])
def test_login_huge_roll_is_4xx_not_500(rc, roll):
    assert login(rc, child_roll=roll).status_code in (401, 422)


@pytest.mark.parametrize("pin", ["' OR '1'='1", "0000'; DROP TABLE parent_accounts;--", "🙂🙂🙂🙂", "\x00\x00\x00\x00"])
def test_login_sqlish_pin_is_just_wrong(rc, pin):
    assert login(rc, pin=pin).status_code in (401, 422)  # 422 when it is longer than a PIN can be
    assert login(rc).status_code == 200  # table still there


def test_login_child_without_account_is_401(rc, w):
    c = w.child("NoAcct", account=False)
    r = rc.post("/v1/parent/login", json={"school_code": w.code, "child_roll": c["roll"],
                                          "parent_phone": "9000000000", "pin": "0000"})
    assert r.status_code == 401


def test_login_locks_out_a_guesser_but_not_the_parent_elsewhere(rc):
    parent_login_body = {"school_code": "DEMO", "child_roll": 12, "parent_phone": "9876500000", "pin": "0000"}
    bad = {**parent_login_body, "pin": "1357"}
    for _ in range(5):
        assert rc.post("/v1/parent/login", json=bad, headers={"x-forwarded-for": "203.0.113.9"}).status_code == 401
    # the 6th try from the same address is refused, even with the right PIN
    assert rc.post("/v1/parent/login", json=parent_login_body,
                   headers={"x-forwarded-for": "203.0.113.9"}).status_code == 429
    # the real parent, on another address, can still sign in
    assert rc.post("/v1/parent/login", json=parent_login_body,
                   headers={"x-forwarded-for": "198.51.100.7"}).status_code == 200

def consent_body(w, c, **over):
    return {"school_code": w.code, "child_roll": c["roll"], "parent_phone": "+91 90000 11111", "consents": True,
            "pin": "2468", **over}


def test_consent_403_when_school_has_no_consent_form(rc, w):
    c = w.child("NoForm", account=False, consent=False)
    r = rc.post("/v1/parent/consent", json=consent_body(w, c))
    assert r.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(ParentAccount).where(ParentAccount.child_id == c["id"])) is None


def test_consent_409_when_account_exists(rc, w):
    c = w.child("Has", account=True)
    assert rc.post("/v1/parent/consent", json=consent_body(w, c)).status_code == 409
    # DEMO child 12 already has an account too
    r = rc.post("/v1/parent/consent", json={"school_code": "DEMO", "child_roll": 12, "parent_phone": "9876500000",
                                            "consents": True, "pin": "0000"})
    assert r.status_code == 409


def test_consent_200_then_login_with_the_new_credentials(rc, w):
    c = w.child("Fresh", account=False, consent=True)
    r = rc.post("/v1/parent/consent", json=consent_body(w, c, language="en"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["child"]["first_name"] == "Fresh" and j["child"]["id"] == c["id"]
    h = {"Authorization": f"Bearer {j['token']}"}
    assert rc.get("/v1/parent/child", headers=h).status_code == 200
    ok = rc.post("/v1/parent/login", json={"school_code": w.code.lower(), "child_roll": c["roll"],
                                           "parent_phone": "9000011111", "pin": "2468"})
    assert ok.status_code == 200
    assert rc.post("/v1/parent/login", json={"school_code": w.code, "child_roll": c["roll"],
                                             "parent_phone": "9000011111", "pin": "0000"}).status_code == 401
    # a second registration for the same child is now refused
    assert rc.post("/v1/parent/consent", json=consent_body(w, c)).status_code == 409
    with SessionLocal() as db:  # the phone and the PIN are stored hashed
        p = db.scalar(select(ParentAccount).where(ParentAccount.child_id == c["id"]))
        assert "9000011111" not in p.phone_hash and "2468" not in p.pin_hash and p.language == "en"


def test_consent_unknown_school_or_child_404_and_consent_flag_422(rc, w):
    c = w.child("X", account=False)
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, school_code="NOPE")).status_code == 404
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, child_roll=4242)).status_code == 404
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, consents=False)).status_code == 422
    assert rc.post("/v1/parent/consent", json={k: v for k, v in consent_body(w, c).items()
                                               if k != "consents"}).status_code == 422


@pytest.mark.parametrize("pin,code", [("123", 422), ("", 422), ("1234567", 422), ("1234", 200), ("123456", 200)])
def test_consent_pin_length_limits(rc, w, pin, code):
    c = w.child("PinLen", account=False)
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, pin=pin)).status_code == code


@pytest.mark.parametrize("phone,code", [("1234567", 422), ("12345678", 422), ("1" * 16, 422), ("9876543210", 200), ("+91 98765 43210", 200)])
def test_consent_phone_length_limits(rc, w, phone, code):
    c = w.child("PhLen", account=False)
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, parent_phone=phone)).status_code == code


def test_consent_rejects_a_phone_without_digits(rc, w):
    c = w.child("NoDigits", account=False)
    assert rc.post("/v1/parent/consent", json=consent_body(w, c, parent_phone="abcdefgh")).status_code == 422


@pytest.mark.xfail(strict=True, reason="BUG: consent picks the lowest-grade child with that roll, so a grade-3 child whose "
                                       "roll equals a registered grade-2 child's can never sign up (parent.py:parent_consent kids[0])")
def test_consent_same_roll_in_two_classes(rc, w):
    g3 = w.klass(3)
    a = w.child("TwoA", account=False, roll=77)
    b = w.child("ThreeA", account=False, roll=77, class_id=g3)
    assert rc.post("/v1/parent/consent", json=consent_body(w, a)).status_code == 200
    r = rc.post("/v1/parent/consent", json=consent_body(w, b, parent_phone="9222222222"))
    assert r.status_code == 200, r.status_code
    assert r.json()["child"]["id"] == b["id"]


def test_login_same_roll_in_two_classes_picks_the_matching_account(rc, w):
    g3 = w.klass(3)
    a = w.child("TwoLogin", roll=88, phone="9333333333", pin="1357")
    b = w.child("ThreeLogin", roll=88, class_id=g3, phone="9444444444", pin="2468")
    la = rc.post("/v1/parent/login", json={"school_code": w.code, "child_roll": 88, "parent_phone": "9333333333",
                                           "pin": "1357"})
    lb = rc.post("/v1/parent/login", json={"school_code": w.code, "child_roll": 88, "parent_phone": "9444444444",
                                           "pin": "2468"})
    assert la.json()["child"]["id"] == a["id"] and lb.json()["child"]["id"] == b["id"]


# ------------------------------------------------------------------ 1. tokens
PARENT_GETS = ["/v1/parent/child", "/v1/parent/pack", "/v1/parent/history", "/v1/parent/teacher_note",
               "/v1/parent/school_week", "/v1/parent/journey", "/v1/parent/tips", "/v1/parent/moments",
               "/v1/parent/weekly", "/v1/parent/voice/sessions", "/v1/parent/voice/sessions/1"]
PARENT_POSTS = ["/v1/parent/sessions", "/v1/parent/sessions/sync", "/v1/parent/voice/sessions",
                "/v1/parent/voice/sessions/1/skip", "/v1/parent/voice/sessions/1/end"]


def _hit(rc, method, path, headers=None):
    if method == "GET":
        return rc.get(path, headers=headers)
    if method == "DELETE":
        return rc.delete(path, headers=headers)
    return rc.post(path, headers=headers, json={"started_at": "2026-01-01T00:00:00Z", "item_id": "x", "lang": "hi"})


ALL_PARENT = [("GET", p) for p in PARENT_GETS] + [("POST", p) for p in PARENT_POSTS] + [
    ("DELETE", "/v1/parent/child/data")]


@pytest.mark.parametrize("method,path", ALL_PARENT)
def test_parent_routes_reject_teacher_token_403(rc, teacher_headers, method, path):
    assert _hit(rc, method, path, teacher_headers).status_code == 403


@pytest.mark.parametrize("method,path", ALL_PARENT)
@pytest.mark.parametrize("auth", [None, "", "Bearer", "Bearer ", "Bearer garbage", "Basic abc", "garbage",
                                  "Bearer a.b.c"])
def test_parent_routes_reject_missing_or_garbage_token_401(rc, method, path, auth):
    hdr = {"Authorization": auth} if auth is not None else None
    assert _hit(rc, method, path, hdr).status_code == 401


def test_parent_token_on_teacher_routes_is_403(rc, parent_headers):
    for path in ("/v1/classes", "/v1/children/12/voice_sessions", "/v1/voice_sessions/1"):
        assert rc.get(path, headers=parent_headers).status_code == 403, path


def test_expired_and_wrongly_signed_tokens_are_401(rc):
    s = get_settings()
    now = datetime.now(timezone.utc)
    old = jwt.encode({"sub": "1", "kind": "parent", "iat": now - timedelta(days=3), "exp": now - timedelta(days=1)},
                     s.jwt_secret, algorithm="HS256")
    forged = jwt.encode({"sub": "1", "kind": "parent", "exp": now + timedelta(days=1)}, "not-the-secret",
                        algorithm="HS256")
    none_alg = jwt.encode({"sub": "1", "kind": "parent"}, None, algorithm="none")
    for t in (old, forged, none_alg):
        assert rc.get("/v1/parent/child", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_token_for_a_deleted_parent_is_401(rc, w):
    c = w.child("Gone")
    assert rc.get("/v1/parent/child", headers=c["headers"]).status_code == 200
    with SessionLocal() as db:
        db.delete(db.get(ParentAccount, c["parent_id"]))
        db.commit()
    for method, path in (("GET", "/v1/parent/child"), ("GET", "/v1/parent/voice/sessions"),
                         ("POST", "/v1/parent/voice/sessions"), ("GET", "/v1/parent/weekly"),
                         ("DELETE", "/v1/parent/child/data")):
        assert _hit(rc, method, path, c["headers"]).status_code == 401, path


def test_token_with_non_numeric_sub_is_401_not_500(rc):
    r = rc.get("/v1/parent/child", headers=tok("abc", "parent"))
    assert r.status_code == 401, r.status_code


# ------------------------------------------------------------------ 2. home
def test_home_shape_for_demo_child(rc, parent_headers):
    r = rc.get("/v1/parent/child", headers=parent_headers)
    assert r.status_code == 200
    j = r.json()
    assert set(j) >= {"child", "focus", "streak"}
    assert j["child"] == {"id": 12, "first_name": "कविता", "roll_no": 12, "class": "कक्षा 2A"}
    assert isinstance(j["streak"], int) and j["streak"] >= 0
    names = {"needs_intervention", "needs_practice", "on_track", "not_started"}
    assert j["focus"], "seeded child 12 has gaps, so there must be focus items"
    for f in j["focus"]:
        assert set(f) >= {"checkpoint_id", "status", "title_hi", "title_en", "label_hi", "label_en"}
        assert f["status"] in names, f
        assert f["title_hi"] and f["title_en"] and f["label_hi"] and f["label_en"]
        assert not any(ch.isdigit() for ch in f["label_en"] + f["label_hi"])  # no numbers/scores in labels


def test_home_for_brand_new_child_still_works(rc, w):
    c = w.child("Newbie")
    r = rc.get("/v1/parent/child", headers=c["headers"])
    assert r.status_code == 200
    j = r.json()
    assert j["child"]["first_name"] == "Newbie" and j["child"]["class"] == "2E" and j["streak"] == 0
    assert isinstance(j["focus"], list)


def _voice_row(child_id, days_ago, school_id):
    with SessionLocal() as db:
        db.add(VoiceSession(school_id=school_id, child_id=child_id, lang="hi", status="ended",
                            started_at=(datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(tzinfo=None),
                            state={}))
        db.commit()


def test_streak_counts_consecutive_voice_session_days(rc, w):
    c = w.child("Streaky")
    other = w.child("Other")
    streak = lambda hh: rc.get("/v1/parent/child", headers=hh).json()["streak"]  # noqa: E731
    assert streak(c["headers"]) == 0
    s = start(rc, c["headers"])  # a real session today
    assert streak(c["headers"]) == 1
    _voice_row(c["id"], 1, w.school_id)
    _voice_row(c["id"], 2, w.school_id)
    assert streak(c["headers"]) == 3
    _voice_row(c["id"], 4, w.school_id)  # a gap at 3 days ago ends the run
    assert streak(c["headers"]) == 3
    assert streak(other["headers"]) == 0  # another child's days never count
    end(rc, c["headers"], s["id"])


def test_streak_counts_two_sessions_on_one_day_once(rc, w):
    c = w.child("Twice")
    start(rc, c["headers"])
    start(rc, c["headers"])
    assert rc.get("/v1/parent/child", headers=c["headers"]).json()["streak"] == 1


def test_streak_survives_until_the_end_of_today(rc, w):
    c = w.child("Yesterday")
    _voice_row(c["id"], 1, w.school_id)
    _voice_row(c["id"], 2, w.school_id)
    assert rc.get("/v1/parent/child", headers=c["headers"]).json()["streak"] == 2


def test_streak_counts_legacy_home_sessions_too(rc, w):
    c = w.child("Legacy")
    with SessionLocal() as db:
        db.add(HomeSession(school_id=w.school_id, child_id=c["id"]))
        db.commit()
    assert rc.get("/v1/parent/child", headers=c["headers"]).json()["streak"] == 1


# ------------------------------------------------------------------ 3. practice removal: old routes still answer
@pytest.fixture
def old(rc, w):
    return w.child("OldApk")


def test_legacy_pack_still_works(rc, old):
    r = rc.get("/v1/parent/pack", headers=old["headers"])
    assert r.status_code == 200
    j = r.json()
    assert j["activities"] and j["canned_lines"] and j["version"] and j["child_name"] == "OldApk"


def test_legacy_session_start_turn_end_history_roundtrip(rc, old):
    h = old["headers"]
    r = rc.post("/v1/parent/sessions", headers=h)  # no body is allowed
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["session_id"] and j["activity"] and j["max_attempts"] and j["intro_hi"]
    act = j["activity"]
    meta = {"index": 0, "attempt": 0, "activity_ref": act["ref"]}
    if act["type"].startswith("tap"):
        meta["tap"] = act["target"]
    else:
        meta["transcript"] = act["target"]
    t = rc.post(f"/v1/parent/sessions/{j['session_id']}/turn", headers=h, data={"meta": json.dumps(meta)})
    assert t.status_code == 200, t.text
    assert t.json()["judged"] == "correct" and t.json()["record_evidence"] is True
    e = rc.post(f"/v1/parent/sessions/{j['session_id']}/end", headers=h)
    assert e.status_code == 200 and e.json()["evidence"] == 1 and e.json()["summary_hi"]
    hist = rc.get("/v1/parent/history", headers=h)
    assert hist.status_code == 200 and hist.json()[0]["id"] == j["session_id"] and hist.json()[0]["activities"] == 1
    # another family's session id is invisible
    other = rc.post("/v1/parent/sessions", headers=h).json()["session_id"]
    assert other != j["session_id"]


def test_legacy_turn_bad_inputs_are_4xx(rc, old, w):
    h = old["headers"]
    sid = rc.post("/v1/parent/sessions", headers=h).json()["session_id"]
    post = lambda meta, s=sid: rc.post(f"/v1/parent/sessions/{s}/turn", headers=h, data={"meta": meta})  # noqa: E731
    assert post("{not json").status_code == 422
    assert post(json.dumps({"index": 0})).status_code == 422
    assert post(json.dumps({"index": 99, "attempt": 0, "activity_ref": "x"})).status_code == 422
    assert post(json.dumps({"index": 0, "attempt": 0, "activity_ref": "x"}), s=999999).status_code == 404
    stranger = w.child("Stranger")
    r = rc.post(f"/v1/parent/sessions/{sid}/turn", headers=stranger["headers"],
                data={"meta": json.dumps({"index": 0, "attempt": 0, "activity_ref": "x"})})
    assert r.status_code == 404


def test_legacy_sync_still_works_and_is_idempotent(rc, old):
    h = old["headers"]
    body = {"started_at": "2026-10-01T10:00:00Z", "ended_at": "2026-10-01T10:05:00Z", "items": []}
    a = rc.post("/v1/parent/sessions/sync", headers=h, json=body)
    b = rc.post("/v1/parent/sessions/sync", headers=h, json=body)
    assert a.status_code == 200 and a.json()["synced"] is True
    assert b.status_code == 200 and b.json()["synced"] is False and b.json()["session_id"] == a.json()["session_id"]
    assert rc.post("/v1/parent/sessions/sync", headers=h, json={"started_at": "garbage"}).status_code == 422


def test_legacy_teacher_note_still_works(rc, parent_headers):
    r = rc.get("/v1/parent/teacher_note", headers=parent_headers)
    assert r.status_code == 200 and r.json()["has_gap"] is True
