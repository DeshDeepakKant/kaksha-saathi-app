"""Offline home practice uploads through /parent/sessions/sync."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models.tables import Evidence


def _home_evidence_count(child_id: int = 12) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Evidence).where(Evidence.child_id == child_id,
                                                     Evidence.source == "home_tap")).all())


def test_offline_session_syncs_once(client, parent_headers):
    started = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    body = {"started_at": started,
            "items": [{"activity_ref": "pi_am_e", "tap": "के"},      # tap, correct
                      {"activity_ref": "pi_n1_add2", "tap": "8"},    # tap, wrong
                      {"activity_ref": "pi_ma_ka"},                  # spoken: practised, no evidence
                      {"activity_ref": "no_such_item", "tap": "x"}]}
    before = _home_evidence_count()
    r = client.post("/v1/parent/sessions/sync", json=body, headers=parent_headers)
    assert r.status_code == 200 and r.json()["synced"] is True and r.json()["evidence"] == 2
    assert _home_evidence_count() == before + 2
    # retry after a lost response: skipped, nothing doubled
    again = client.post("/v1/parent/sessions/sync", json=body, headers=parent_headers).json()
    assert again["synced"] is False and again["session_id"] == r.json()["session_id"]
    assert _home_evidence_count() == before + 2
    hist = client.get("/v1/parent/history", headers=parent_headers).json()
    row = next(h for h in hist if h["id"] == r.json()["session_id"])
    assert row["offline"] is True and row["ended_at"] and row["summary_hi"]


def test_sync_finishes_a_session_that_lost_the_network(client, parent_headers):
    s = client.post("/v1/parent/sessions", json={"offline": False}, headers=parent_headers).json()
    body = {"started_at": datetime.now(timezone.utc).isoformat(), "session_id": s["session_id"],
            "items": [{"activity_ref": "pi_am_e", "tap": "के"}]}
    r = client.post("/v1/parent/sessions/sync", json=body, headers=parent_headers).json()
    assert r["synced"] is True and r["session_id"] == s["session_id"] and r["evidence"] == 1
    assert client.post("/v1/parent/sessions/sync", json=body, headers=parent_headers).json()["synced"] is False


def test_sync_rejects_someone_elses_session(client, parent_headers):
    r = client.post("/v1/parent/sessions/sync", headers=parent_headers,
                    json={"started_at": datetime.now(timezone.utc).isoformat(), "session_id": 999999, "items": []})
    assert r.status_code == 404
