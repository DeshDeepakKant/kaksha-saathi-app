"""Regressions for app ↔ API contract bugs found against the live deployment."""
import json

from app.services import tutor
from app.services.content import get_content


def test_attendance_accepts_app_body(client, teacher_headers):
    # the teacher app posts {"absent_rolls": [...]}; same rolls the seed marks absent
    r = client.post("/v1/classes/1/attendance", json={"absent_rolls": [1, 2]}, headers=teacher_headers)
    assert r.status_code == 200 and r.json()["absent"] == [1, 2]


def test_subject_alias_and_unknown(client, teacher_headers):
    b = client.get("/v1/classes/1/board?subject=math", headers=teacher_headers)
    assert b.status_code == 200 and b.json()["groups"]
    assert client.get("/v1/classes/1/board?subject=science", headers=teacher_headers).status_code == 422
    p = client.get("/v1/children/1/profile?subject=Maths", headers=teacher_headers).json()
    assert p["subject"] == "numeracy" and p["items"]


def test_children_without_evidence_are_unassessed(client, teacher_headers):
    b = client.get("/v1/classes/1/board?subject=numeracy", headers=teacher_headers).json()
    unassessed = {c["roll_no"] for c in b["unassessed"]}
    on_track = {c["roll_no"] for c in b["on_track"]}
    assert {13, 14} <= unassessed  # seeded starters with no numeracy evidence
    assert not ({13, 14} & on_track)


def test_history_subject_filter(client, teacher_headers):
    h = client.get("/v1/children/1/history?subject=literacy", headers=teacher_headers).json()
    assert h and all(e["checkpoint_id"].startswith("L.") for e in h)


def test_probe_rejects_child_from_other_class(client, teacher_headers):
    r = client.post("/v1/classes/2/captures/probe?child_id=1&checkpoint_id=L.G1.swar&passed=1&total=2",
                    headers=teacher_headers)
    assert r.status_code == 422


def test_parent_focus_status_is_a_name(client, parent_headers):
    focus = client.get("/v1/parent/child", headers=parent_headers).json()["focus"]
    assert focus and all(isinstance(f["status"], str) and f["label_en"] for f in focus)


def test_parent_login_normalises_phone(client):
    r = client.post("/v1/parent/login", json={"school_code": "demo", "child_roll": 12,
                                              "parent_phone": "+91 98765 00000", "pin": "0000"})
    assert r.status_code == 200 and r.json()["child"]["roll_no"] == 12


def test_two_tries_then_move_on():
    act = tutor.find_activity("pi_ma_ka", get_content())
    plan = {"activities": [act.__dict__, act.__dict__]}
    kw = dict(child_name="x", plan=plan, index=0, activity=act, transcript="", tap=None,
              school_id=1, offline=True)
    first = tutor.next_turn(None, attempt=0, **kw)
    second = tutor.next_turn(None, attempt=1, **kw)
    assert not first["advance"] and first["attempt"] == 1
    assert second["advance"] and second["record_evidence"]


def test_tap_order_items_have_options():
    for ref in ("pi_wf_ka", "pi_wf_kamal"):
        act = tutor.find_activity(ref, get_content())
        assert act.target in act.options and len(act.options) >= 2


def _start(client, parent_headers):
    return client.post("/v1/parent/sessions", json={"offline": True}, headers=parent_headers).json()


def test_turn_bad_meta_is_422(client, parent_headers):
    s = _start(client, parent_headers)
    r = client.post(f"/v1/parent/sessions/{s['session_id']}/turn", headers=parent_headers,
                    data={"meta": '{"index": 0, "attempt": 0, "activity_ref": null}'})
    assert r.status_code == 422


def test_turn_survives_asr_outage(client, parent_headers, monkeypatch):
    class Down:
        def transcribe(self, *a, **k):
            raise RuntimeError("sarvam down")
    monkeypatch.setattr("app.api.parent.get_asr", lambda: Down())
    s = _start(client, parent_headers)
    act = s["activity"]
    r = client.post(f"/v1/parent/sessions/{s['session_id']}/turn", headers=parent_headers,
                    data={"meta": json.dumps({"index": 0, "attempt": 0, "activity_ref": act["ref"],
                                              "offline": True})},
                    files={"audio": ("turn.webm", b"\x00" * 64, "audio/webm")})
    assert r.status_code == 200 and r.json()["asr"] == "failed"


def test_turn_judges_activity_by_ref(client, parent_headers):
    s = _start(client, parent_headers)
    acts = s["plan"]["activities"]
    tap_act = next(a for a in acts if a["type"].startswith("tap"))
    # index 0 but the ref names the tap activity: the tap must be judged against that activity
    r = client.post(f"/v1/parent/sessions/{s['session_id']}/turn", headers=parent_headers,
                    data={"meta": json.dumps({"index": 0, "attempt": 0, "activity_ref": tap_act["ref"],
                                              "tap": tap_act["target"], "offline": True})}).json()
    assert r["judged"] == "correct" and r["activity"]["ref"] == tap_act["ref"]
