"""Cross-feature checks for the teacher-loop work: the delete routes clean up the new tables.

Uses its own school so the shared DEMO data is untouched.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.security import hash_pin, make_token
from app.db import SessionLocal
from app.models.tables import (
    Child, Classroom, GroupSession, InterventionLog, LevelCheck, Plan, School, Teacher,
)

BORROW = "N.G2.sub_2digit_borrow"


@pytest.fixture
def loop_class():
    """A class with one child, one plan marked done (log + session snapshot) and one level check."""
    with SessionLocal() as db:
        sch = School(name="Loop test school", code="LP" + uuid.uuid4().hex[:8].upper())
        db.add(sch)
        db.flush()
        t = Teacher(school_id=sch.id, name="Loop Teacher", pin_hash=hash_pin("2468"))
        db.add(t)
        db.flush()
        cls = Classroom(school_id=sch.id, teacher_id=t.id, grade=2, section="L", label="कक्षा 2L")
        db.add(cls)
        db.flush()
        kid = Child(class_id=cls.id, roll_no=1, first_name="Lata")
        db.add(kid)
        db.flush()
        plan = Plan(school_id=sch.id, class_id=cls.id, subject="numeracy", for_date=date(2026, 10, 20),
                    generated_by="fallback", payload={"groups": []})
        db.add(plan)
        db.flush()
        db.add(InterventionLog(school_id=sch.id, plan_id=plan.id, group_key=BORROW))
        db.add(GroupSession(school_id=sch.id, class_id=cls.id, plan_id=plan.id, subject="numeracy",
                            group_key=BORROW, checkpoint_id=BORROW, member_ids=[kid.id]))
        db.add(LevelCheck(school_id=sch.id, class_id=cls.id, child_id=kid.id, subject="numeracy",
                          level_index=1, level_key="num_10_99"))
        db.commit()
        headers = {"Authorization": f"Bearer {make_token(str(t.id), 'teacher')}"}
        return {"headers": headers, "class_id": cls.id, "child_id": kid.id, "plan_id": plan.id}


def test_delete_child_data_removes_level_checks(client, loop_class):
    r = client.delete(f"/v1/children/{loop_class['child_id']}/data", headers=loop_class["headers"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalars(select(LevelCheck).where(LevelCheck.child_id == loop_class["child_id"])).all() == []


def test_delete_class_data_with_done_groups(client, loop_class):
    """A group marked Done leaves a log and a session; deleting the class must still work and remove them."""
    r = client.delete(f"/v1/classes/{loop_class['class_id']}/data", headers=loop_class["headers"])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Plan, loop_class["plan_id"]) is None
        assert db.scalars(select(InterventionLog).where(InterventionLog.plan_id == loop_class["plan_id"])).all() == []
        assert db.scalars(select(GroupSession).where(GroupSession.plan_id == loop_class["plan_id"])).all() == []
        assert db.scalars(select(LevelCheck).where(LevelCheck.class_id == loop_class["class_id"])).all() == []
