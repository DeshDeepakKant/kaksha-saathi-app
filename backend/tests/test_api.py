"""End-to-end API flows with no external services (deterministic paths)."""
import json


def test_login_bad_pin(client):
    assert client.post("/v1/auth/login", json={"school_code": "DEMO", "pin": "9999"}).status_code == 401


def test_classes_and_roster(client, teacher_headers):
    r = client.get("/v1/classes", headers=teacher_headers).json()
    assert {c["grade"] for c in r} == {2, 3}
    roster = client.get(f"/v1/classes/{r[0]['id']}/roster", headers=teacher_headers).json()
    assert len(roster) == 30


def test_roadmap_default(client, teacher_headers):
    r = client.get("/v1/classes/1/roadmap?subject=numeracy", headers=teacher_headers).json()
    assert r["confirmed"] is True and len(r["items"]) > 10


def test_board_has_groups_on_track_unassessed(client, teacher_headers):
    b = client.get("/v1/classes/1/board?subject=numeracy", headers=teacher_headers).json()
    assert b["groups"] and b["on_track"]
    assert {g["reason"] for g in b["groups"]} <= {"direct", "needs_intervention_root", "needs_practice_root"}


def test_note_capture_rules_and_confirm(client, teacher_headers):
    r = client.post("/v1/classes/1/captures/note", headers=teacher_headers,
                    data={"transcript": "आज उधार वाला घटाव कराया। मीना को उधार समझ नहीं आया। अर्जुन ने सही किया। प्रिया नहीं आई।",
                          "subject": "numeracy"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ai_status"] in ("ready", "fallback")
    names = {d["first_name"] for d in j["drafts"]}
    assert "मीना" in names
    accepted = [{"child_id": d["child_id"], "checkpoint_id": d["checkpoint_id"] or "N.G2.sub_2digit_borrow",
                 "result": d.get("result") or "incorrect"} for d in j["drafts"] if d.get("checkpoint_id")]
    c = client.post(f"/v1/captures/{j['capture_id']}/confirm", headers=teacher_headers, json={"accepted": accepted})
    assert c.status_code == 200 and c.json()["committed"] >= 1
    assert client.post(f"/v1/captures/{j['capture_id']}/confirm", headers=teacher_headers,
                       json={"accepted": []}).status_code == 409


def test_tap_capture_changes_status(client, teacher_headers):
    cp = "L.G2.all_matras"
    client.post("/v1/classes/1/captures/tap", headers=teacher_headers,
                json={"items": [{"child_id": 20, "checkpoint_id": cp, "result": "incorrect"}] * 2})
    after = client.get("/v1/children/20/profile?subject=literacy", headers=teacher_headers).json()
    assert any(i["checkpoint_id"] == cp and i["status"] != "not_started" for i in after["items"])


def test_voice_capture_low_quality_without_text(client, teacher_headers):
    body = '{"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "target_items": ["का", "कि"]}'
    r = client.post("/v1/classes/1/captures/voice", headers=teacher_headers, data={"body_json": body})
    assert r.json()["ai_status"] == "low_audio_quality"


def test_voice_capture_with_transcript(client, teacher_headers):
    body = '{"child_id": 2, "checkpoint_id": "L.G1.matra_basic", "target_items": ["का", "कि", "की"]}'
    r = client.post("/v1/classes/1/captures/voice", headers=teacher_headers,
                    data={"body_json": body, "transcript": "का कि की"}).json()
    assert r["score"]["counts"]["correct"] == 3
    assert r["proposal"]["result"] in ("correct", "partial")


def test_plan_fallback_valid(client, teacher_headers):
    r = client.post("/v1/classes/1/plans?subject=numeracy&force=true", headers=teacher_headers).json()
    assert r["generated_by"] in ("ai", "fallback")
    for g in r["groups"]:
        assert g["teacher_script_hi"] and g["members"]
        assert g["time_min"] <= 12


def test_profile_and_history(client, teacher_headers):
    p = client.get("/v1/children/3/profile?subject=numeracy", headers=teacher_headers).json()
    assert p["child"]["roll_no"] == 3 and p["items"]
    assert isinstance(client.get("/v1/children/3/history", headers=teacher_headers).json(), list)


def test_parent_consent_duplicate(client):
    r = client.post("/v1/parent/consent", json={"school_code": "DEMO", "child_roll": 12,
                                                "parent_phone": "9876500000", "consents": True, "pin": "1234"})
    assert r.status_code == 409  # already set up by the seed


def test_parent_pack_and_session(client, parent_headers):
    pack = client.get("/v1/parent/pack", headers=parent_headers).json()
    assert pack["activities"] and pack["canned_lines"]
    s = client.post("/v1/parent/sessions", json={"offline": True}, headers=parent_headers).json()
    sid, act = s["session_id"], s["activity"]
    tap = act["target"] if act["type"].startswith("tap") else None
    t = client.post(f"/v1/parent/sessions/{sid}/turn", headers=parent_headers,
                    data={"meta": json.dumps({"index": 0, "attempt": 0, "activity_ref": act["ref"],
                                              "tap": tap, "offline": True})}).json()
    assert t["judged"] in ("correct", "wrong")
    e = client.post(f"/v1/parent/sessions/{sid}/end", headers=parent_headers).json()
    assert "summary_hi" in e


def test_parent_safety_redirect(client, parent_headers):
    s = client.post("/v1/parent/sessions", json={"offline": False}, headers=parent_headers).json()
    t = client.post(f"/v1/parent/sessions/{s['session_id']}/turn", headers=parent_headers,
                    data={"meta": json.dumps({"index": 0, "attempt": 0, "activity_ref": "x",
                                              "transcript": "मुझे डर लगता है", "offline": False})}).json()
    assert t["line_status"] == "safety" and t["safety_flag"] == "distress"


def test_ai_activity_counter(client, teacher_headers):
    j = client.get("/v1/ai_activity", headers=teacher_headers).json()
    assert {"captures", "proposals", "confirmed", "rejected", "degraded", "cost_inr"} <= set(j)


def test_tenant_isolation(client, teacher_headers):
    assert client.get("/v1/children/999999/profile?subject=numeracy", headers=teacher_headers).status_code == 404
    assert client.get("/v1/classes", headers={"Authorization": "Bearer bogus"}).status_code == 401


def test_delete_child_data(client, teacher_headers):
    assert client.delete("/v1/children/27/data", headers=teacher_headers).json()["deleted"] is True
