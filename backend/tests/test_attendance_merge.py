"""Voice-note absences merge into the day's register instead of replacing it."""
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.models.tables import Attendance, Child


def _register(class_id: int = 1) -> dict[int, bool]:
    """roll_no -> present for today's rows in the class."""
    with SessionLocal() as db:
        rows = db.execute(select(Child.roll_no, Attendance.present)
                          .join(Attendance, Attendance.child_id == Child.id)
                          .where(Attendance.class_id == class_id, Attendance.day == date.today())).all()
    return {roll: present for roll, present in rows}


def test_merge_keeps_earlier_absences(client, teacher_headers):
    # start from the seeded state: rolls 1 and 2 absent, everyone else present
    r = client.post("/v1/classes/1/attendance", json={"absent_rolls": [1, 2]}, headers=teacher_headers)
    assert r.status_code == 200
    before = _register()
    assert {roll for roll, p in before.items() if not p} == {1, 2}
    try:
        r = client.post("/v1/classes/1/attendance?merge=true", json={"absent_rolls": [5]}, headers=teacher_headers)
        assert r.status_code == 200 and r.json()["absent"] == [5]
        after = _register()
        assert {roll for roll, p in after.items() if not p} == {1, 2, 5}
        # nobody else was touched
        assert {k: v for k, v in after.items() if k != 5} == {k: v for k, v in before.items() if k != 5}
    finally:
        # the seeded DB is shared across tests: restore the seed's absences
        client.post("/v1/classes/1/attendance", json={"absent_rolls": [1, 2]}, headers=teacher_headers)
    assert {roll for roll, p in _register().items() if not p} == {1, 2}


def test_default_still_replaces(client, teacher_headers):
    try:
        client.post("/v1/classes/1/attendance?merge=true", json={"absent_rolls": [7]}, headers=teacher_headers)
        r = client.post("/v1/classes/1/attendance", json={"absent_rolls": [3]}, headers=teacher_headers)
        assert r.status_code == 200
        assert {roll for roll, p in _register().items() if not p} == {3}
    finally:
        client.post("/v1/classes/1/attendance", json={"absent_rolls": [1, 2]}, headers=teacher_headers)
    assert {roll for roll, p in _register().items() if not p} == {1, 2}
