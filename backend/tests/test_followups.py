"""Teacher loop insights: done snapshots, history ids, follow-ups and outcomes (docs/teacher_loop_contract.md).

Uses its own school ("FUPS") so the shared DEMO data is untouched; removed at module teardown.
Times are relative to now and stored as naive UTC, like the app does.
"""
import itertools
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.security import hash_pin
from app.db import SessionLocal
from app.models.tables import (
    Attendance, Child, Classroom, Evidence, GroupSession, InterventionLog, Plan, School, Teacher,
)
from app.services.ledger import school_today

BORROW = "N.G2.sub_2digit_borrow"
CARRY = "N.G2.add_2digit_carry"
PV = "N.G2.place_value_99"
NO_BORROW = "N.G2.sub_2digit_no_borrow"

NAMES = ["Anu", "Bela", "Chand", "Dev", "Ela", "Farid", "Gita", "Hari", "Indu", "Jai", "Kiran", "Lata",
         "Mohan", "Nina"]
OUT_NAMES = ["Pari", "Quasim", "Ravi", "Tara", "Usha"]


def _ago(**delta) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**delta)


@pytest.fixture(scope="module")
def fs(client):
    """School FUPS: class F (follow-ups scenarios) and class O (outcomes), each child named for its case."""
    with SessionLocal() as db:
        sch = School(name="Follow-ups school", code="FUPS")
        db.add(sch)
        db.flush()
        t = Teacher(school_id=sch.id, name="T", pin_hash=hash_pin("4321"))
        db.add(t)
        db.flush()
        info = {"school_id": sch.id, "teacher_id": t.id, "kids": {}}
        for section, names in (("F", NAMES), ("O", OUT_NAMES)):
            cls = Classroom(school_id=sch.id, teacher_id=t.id, grade=2, section=section, label=f"2{section}")
            db.add(cls)
            db.flush()
            info[section] = cls.id
            for roll, nm in enumerate(names, start=1):
                ch = Child(class_id=cls.id, roll_no=roll, first_name=nm)
                db.add(ch)
                db.flush()
                info["kids"][nm] = ch.id
        k = info["kids"]

        def ev(name, cp, result, source="teacher_tap", **ago):
            cls_id = info["O"] if name in OUT_NAMES else info["F"]
            db.add(Evidence(school_id=sch.id, class_id=cls_id, child_id=k[name], checkpoint_id=cp, result=result,
                            source=source, confidence=1.0, at=_ago(**ago), status="confirmed"))

        plan_day = itertools.count()

        def session(section, cp, names, act="act_borrow_sticks", **ago):
            done = _ago(**ago)
            plan = Plan(school_id=sch.id, class_id=info[section], subject="numeracy",  # any unique day will do
                        for_date=date(2000, 1, 1) + timedelta(days=next(plan_day)),
                        generated_by="fallback", payload={"groups": []})
            db.add(plan)
            db.flush()
            db.add(GroupSession(school_id=sch.id, class_id=info[section], plan_id=plan.id, subject="numeracy",
                                group_key=cp, checkpoint_id=cp, activity_id=act, member_ids=[k[n] for n in names],
                                done_at=done))
            return done

        # recheck: Anu not re-checked; Bela re-checked in class; Chand only practised at home (still due)
        session("F", BORROW, ["Anu", "Bela", "Chand"], days=3)
        ev("Bela", BORROW, "correct", days=1)
        ev("Chand", BORROW, "correct", source="home_tap", days=1)
        # taught today (not due yet) and 20 days ago (out of the window)
        session("F", PV, ["Dev"], minutes=1)
        session("F", NO_BORROW, ["Ela"], days=20)
        # stuck: Farid in 3 sessions and still behind; Gita in 3 sessions but on track now
        for d in (30, 20, 10):
            session("F", CARRY, ["Farid", "Gita"], act=None, days=d)
        for n, r in (("Farid", "incorrect"), ("Gita", "correct")):
            ev(n, CARRY, r, days=5)
            ev(n, CARRY, r, days=4)
        # missed: Hari absent on one of two session days; Indu no attendance row; Jai present
        d6 = session("F", NO_BORROW, ["Hari", "Indu", "Jai"], act=None, days=6)
        session("F", NO_BORROW, ["Hari", "Indu", "Jai"], act=None, days=5)
        day6 = school_today(d6.replace(tzinfo=timezone.utc))
        db.add(Attendance(school_id=sch.id, class_id=info["F"], child_id=k["Hari"], day=day6, present=False))
        db.add(Attendance(school_id=sch.id, class_id=info["F"], child_id=k["Jai"], day=day6, present=True))
        # not checked: Kiran has 2 classroom rows (checked); Lata has 1 classroom + 3 home rows (not checked)
        ev("Kiran", PV, "correct", days=2)
        ev("Kiran", PV, "correct", days=1)
        ev("Lata", PV, "correct", days=2)
        for d in (1, 2, 3):
            ev("Lata", PV, "correct", source="home_voice", days=d)
        # fading (on track, newest evidence N days old): Mohan 16 → 5 days left, Nina 15 → 6 (not yet)
        for name, newest in (("Mohan", 16), ("Nina", 15)):
            ev(name, PV, "correct", days=newest + 1, hours=1)
            ev(name, PV, "correct", days=newest, hours=1)
        # fading edge: Anu's newest is 21 days old → 0 days left; Bela's is 22 → already out of the window
        for name, newest in (("Anu", 21), ("Bela", 22)):
            ev(name, CARRY, "correct", days=newest + 1, hours=1)
            ev(name, CARRY, "correct", days=newest, hours=1)

        # outcomes (class O): one session 5 days ago on place value
        for n in OUT_NAMES:
            ev(n, PV, "correct" if n == "Quasim" else "incorrect", days=8)
            ev(n, PV, "correct" if n == "Quasim" else "incorrect", days=7)
        info["out_done"] = session("O", PV, OUT_NAMES, act="act_place_value_bundles", days=5)
        ev("Pari", PV, "correct", days=2)                    # needs_intervention → better
        ev("Pari", PV, "correct", days=1)
        ev("Quasim", PV, "incorrect", days=2)                # on_track → worse
        ev("Quasim", PV, "incorrect", days=1)
        ev("Usha", PV, "incorrect", days=1)                  # re-checked, no change
        ev("Tara", PV, "correct", source="home_voice", days=1)  # home only: not re-checked; Ravi: nothing
        db.commit()
    r = client.post("/v1/auth/login", json={"school_code": "FUPS", "pin": "4321"})
    assert r.status_code == 200, r.text
    info["h"] = {"Authorization": f"Bearer {r.json()['token']}"}
    yield info
    with SessionLocal() as db:
        cls_ids = [info["F"], info["O"]]
        db.execute(delete(GroupSession).where(GroupSession.school_id == info["school_id"]))
        db.execute(delete(InterventionLog).where(InterventionLog.school_id == info["school_id"]))
        db.execute(delete(Plan).where(Plan.school_id == info["school_id"]))
        db.execute(delete(Attendance).where(Attendance.class_id.in_(cls_ids)))
        db.execute(delete(Evidence).where(Evidence.class_id.in_(cls_ids)))
        db.execute(delete(Child).where(Child.class_id.in_(cls_ids)))
        db.execute(delete(Classroom).where(Classroom.id.in_(cls_ids)))
        db.execute(delete(Teacher).where(Teacher.school_id == info["school_id"]))
        db.execute(delete(School).where(School.id == info["school_id"]))
        db.commit()


@pytest.fixture(scope="module")
def fups(client, fs):
    r = client.get(f"/v1/classes/{fs['F']}/followups?subject=numeracy", headers=fs["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _ids(rows, fs, *names):
    return {r["child_id"] for r in rows} & {fs["kids"][n] for n in names}


def _row(rows, fs, name, **match):
    return next((r for r in rows if r["child_id"] == fs["kids"][name]
                 and all(r.get(k) == v for k, v in match.items())), None)


# ------------------------------------------------------------------ done → snapshot
def test_done_records_snapshot_idempotently(client, fs):
    k = fs["kids"]
    with SessionLocal() as db:
        plan = Plan(school_id=fs["school_id"], class_id=fs["F"], subject="numeracy", for_date=school_today(),
                    generated_by="fallback",
                    payload={"groups": [{"key": BORROW, "activity_id": "act_borrow_sticks",
                                         "members": [{"id": k["Anu"], "first_name": "Anu"},
                                                     {"id": k["Bela"], "first_name": "Bela"}]},
                                        {"key": CARRY, "activity_id": "generic", "members": [3, 4]}],
                             "assess_first": {"key": "assess_first", "members": [{"id": k["Dev"]}]}})
        db.add(plan)
        db.commit()
        pid = plan.id
    url = f"/v1/plans/{pid}/groups/{BORROW}/done"
    a = client.post(url, headers=fs["h"]).json()
    b = client.post(url, headers=fs["h"]).json()
    assert a["ok"] is True and isinstance(a["session_id"], int) and a == b
    legacy = client.post(f"/v1/plans/{pid}/groups/{CARRY}/done", headers=fs["h"]).json()
    assert client.post(f"/v1/plans/{pid}/groups/assess_first/done", headers=fs["h"]).json() == \
        {"ok": True, "session_id": None}
    assert client.post(f"/v1/plans/{pid}/groups/nope/done", headers=fs["h"]).json()["session_id"] is None
    with SessionLocal() as db:
        rows = {s.group_key: s for s in db.scalars(select(GroupSession).where(GroupSession.plan_id == pid))}
        assert set(rows) == {BORROW, CARRY}
        s = rows[BORROW]
        assert s.id == a["session_id"] and s.member_ids == [k["Anu"], k["Bela"]]
        assert (s.checkpoint_id, s.activity_id, s.subject, s.done_by) == (BORROW, "act_borrow_sticks", "numeracy",
                                                                         fs["teacher_id"])
        # legacy roll numbers resolved to ids; the non-library "generic" activity is stored as None
        assert rows[CARRY].id == legacy["session_id"] and rows[CARRY].member_ids == [k["Chand"], k["Dev"]]
        assert rows[CARRY].activity_id is None
        db.execute(delete(InterventionLog).where(InterventionLog.plan_id == pid))
        db.execute(delete(Plan).where(Plan.id == pid))  # cascades to its sessions
        db.commit()
        assert not db.scalars(select(GroupSession).where(GroupSession.plan_id == pid)).all()


def test_history_rows_have_evidence_ids(client, fs):
    rows = client.get(f"/v1/children/{fs['kids']['Lata']}/history", headers=fs["h"]).json()
    with SessionLocal() as db:
        ids = set(db.scalars(select(Evidence.id).where(Evidence.child_id == fs["kids"]["Lata"])))
    assert rows and {r["id"] for r in rows} == ids


# ------------------------------------------------------------------ follow-ups
def test_followups_shape(fups):
    assert fups["subject"] == "numeracy" and fups["generated_at"]
    assert all(len(fups[k]) <= 20 for k in ("recheck", "stuck", "missed", "not_checked", "fading"))


def test_recheck(fups, fs):
    rows = fups["recheck"]
    assert _ids(rows, fs, "Anu", "Bela", "Chand", "Dev", "Ela") == {fs["kids"]["Anu"], fs["kids"]["Chand"]}
    anu = _row(rows, fs, "Anu")
    assert anu["checkpoint_id"] == BORROW and anu["days_since"] == 3 and anu["has_probe"] is True
    assert anu["title_en"] and anu["group_key"] == BORROW and isinstance(anu["session_id"], int)
    assert len({r["child_id"] for r in rows}) == len(rows)  # one row per child
    assert [r["days_since"] for r in rows] == sorted((r["days_since"] for r in rows), reverse=True)


def test_stuck(fups, fs):
    rows = fups["stuck"]
    assert _ids(rows, fs, "Farid", "Gita") == {fs["kids"]["Farid"]}
    f = _row(rows, fs, "Farid")
    assert f["checkpoint_id"] == CARRY and f["sessions"] == 3 and f["status"] != "on_track"
    assert f["since"] == school_today(datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert f["alt_activity_id"] == "act_add_carry_sticks" and f["alt_activity_title_hi"]
    assert f["suggestion_en"].startswith("Try a different activity") and f["suggestion_hi"]


def test_missed_needs_an_absent_row(fups, fs):
    rows = fups["missed"]
    assert _ids(rows, fs, "Hari", "Indu", "Jai") == {fs["kids"]["Hari"]}  # no row ≠ absent; present ≠ absent
    h = _row(rows, fs, "Hari")
    assert (h["checkpoint_id"], h["missed"], h["of"]) == (NO_BORROW, 1, 2) and h["last_missed"]


def test_not_checked(fups, fs):
    rows = fups["not_checked"]
    ids = {r["child_id"] for r in rows}
    k = fs["kids"]
    assert k["Kiran"] not in ids  # 2 classroom rows in 14 days
    lata = _row(rows, fs, "Lata")
    assert lata["checks_14d"] == 1  # home practice does not count
    ela = _row(rows, fs, "Ela")
    assert ela["checks_14d"] == 0 and ela["last_checked"] is None
    assert [r["checks_14d"] for r in rows] == sorted(r["checks_14d"] for r in rows)


def test_fading_boundary(fups, fs):
    rows = fups["fading"]
    assert _row(rows, fs, "Mohan", checkpoint_id=PV)["expires_in_days"] == 5
    assert _row(rows, fs, "Nina", checkpoint_id=PV) is None          # 6 days left: not yet
    assert _row(rows, fs, "Anu", checkpoint_id=CARRY)["expires_in_days"] == 0
    assert _row(rows, fs, "Bela", checkpoint_id=CARRY) is None       # already out of the window
    m = _row(rows, fs, "Mohan", checkpoint_id=PV)
    assert m["status"] == "on_track" and m["last_evidence_on"]


# ------------------------------------------------------------------ outcomes
def test_outcomes_before_after(client, fs):
    r = client.get(f"/v1/classes/{fs['O']}/outcomes?subject=numeracy", headers=fs["h"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["subject"] == "numeracy" and len(j["sessions"]) == 1
    s = j["sessions"][0]
    assert s["checkpoint_id"] == PV and s["activity_id"] == "act_place_value_bundles" and s["members"] == 5
    by = {c["first_name"]: c for c in s["children"]}
    assert by["Pari"]["before"] == "needs_intervention" and by["Pari"]["change"] == "up"
    assert by["Quasim"]["before"] == "on_track" and by["Quasim"]["change"] == "down"
    assert by["Usha"]["change"] == "same" and by["Usha"]["after"] == "needs_intervention"
    for n in ("Ravi", "Tara"):
        assert by[n]["after"] is None and by[n]["change"] == "not_rechecked"
    assert (s["moved_up"], s["same"], s["moved_down"], s["not_rechecked"]) == (1, 1, 1, 2)
    assert j["activities"] == [{"activity_id": "act_place_value_bundles", "title_hi": s["activity_title_hi"], "sessions": 1,
                                "children": 5, "rechecked": 3, "moved_up": 1}]
    short = client.get(f"/v1/classes/{fs['O']}/outcomes?subject=numeracy&days=2", headers=fs["h"]).json()
    assert short["sessions"] == [] and short["activities"] == []


def test_outcomes_newest_first(client, fs):
    j = client.get(f"/v1/classes/{fs['F']}/outcomes?subject=numeracy", headers=fs["h"]).json()
    days = [s["done_on"] for s in j["sessions"]]
    assert days and days == sorted(days, reverse=True)
    assert j["activities"] and all(a["activity_id"] for a in j["activities"])


# ------------------------------------------------------------------ tenancy
def test_other_school_gets_404(client, fs, teacher_headers):
    for path in ("followups", "outcomes"):
        assert client.get(f"/v1/classes/{fs['F']}/{path}?subject=numeracy",
                          headers=teacher_headers).status_code == 404
        assert client.get(f"/v1/classes/1/{path}?subject=numeracy", headers=fs["h"]).status_code == 404
    with SessionLocal() as db:
        pid = db.scalar(select(Plan.id).where(Plan.school_id == fs["school_id"]).limit(1))
    assert client.post(f"/v1/plans/{pid}/groups/{BORROW}/done", headers=teacher_headers).status_code == 404
