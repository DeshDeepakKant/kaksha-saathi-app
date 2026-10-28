"""Seed a demo school with fictional children and ~3 weeks of realistic history.

    python -m app.seed          (idempotent: re-running resets DEMO school)

All children are fictional. Names are common first names; no real data.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.security import hash_phone, hash_pin
from app.db import SessionLocal, init_db
from app.models.tables import (
    AiCall, Attendance, CaptureSession, Child, Classroom, Evidence, HomeSession, InterventionLog, ParentAccount,
    Plan, Roadmap, RoadmapItem, School, Teacher, UsageCounter, utcnow, CustomCheckpoint, CustomSubject,
    VoiceSession, VoiceTurn,
)
from app.services.content import get_content
from app.services.ledger import school_today

DEMO_CODE = "DEMO"
TEACHER_PIN = "1234"
PARENT_PIN = "0000"
PARENT_PHONE = "9876500000"

NAMES_2A = ["राहुल", "मीना", "अर्जुन", "प्रिया", "करन", "सोनल", "अमित", "राजकुमार", "सूरज", "दीपा",
            "नितेश", "कविता", "विकास", "पूजा", "मनीष", "रीना", "अनिल", "सीमा", "दिनेश", "गीता",
            "मोहन", "लक्ष्मी", "बबलू", "सुनीता", "रवि", "आशा", "जय", "नेहा", "दिलीप", "रमेश"]
NAMES_3A = ["सोना", "अजय", "रितेश", "ममता", "प्रकाश", "ज्योति", "सतीश", "उषा", "विनोद", "कमला",
            "रोहित", "सविता", "महेश", "गौरव", "रीता", "अशोक", "पिंकी", "रामू", "टीना", "देवी",
            "मुकेश", "संध्या", "हरीश", "पूनम", "किरण", "अनीता", "गोपाल", "मधु"]


def _ev(db, sch, cls, child, cp, result, source, at, conf=0.9, misc=None):
    db.add(Evidence(school_id=sch, class_id=cls, child_id=child, checkpoint_id=cp, result=result,
                    source=source, confidence=conf, at=at, status="confirmed", misconception=misc))


def seed() -> dict:
    init_db()
    content = get_content()
    db = SessionLocal()
    try:
        old = db.scalar(select(School).where(School.code == DEMO_CODE))
        if old:
            ids = [c.id for c in db.scalars(select(Child).where(Child.class_id.in_(
                select(Classroom.id).where(Classroom.school_id == old.id))))]
            if ids:
                db.execute(delete(Evidence).where(Evidence.session_id.in_(
                    select(CaptureSession.id).where(CaptureSession.school_id == old.id))))
            db.execute(delete(CaptureSession).where(CaptureSession.school_id == old.id))
            db.execute(delete(InterventionLog).where(InterventionLog.school_id == old.id))
            db.execute(delete(AiCall).where(AiCall.school_id == old.id))
            db.execute(delete(UsageCounter).where(UsageCounter.school_id == old.id))
            if ids:
                db.execute(delete(Evidence).where(Evidence.child_id.in_(ids)))
                db.execute(delete(Attendance).where(Attendance.child_id.in_(ids)))
                db.execute(delete(HomeSession).where(HomeSession.child_id.in_(ids)))
            voice = select(VoiceSession.id).where(VoiceSession.school_id == old.id)
            db.execute(delete(VoiceTurn).where(VoiceTurn.session_id.in_(voice)))
            db.execute(delete(VoiceSession).where(VoiceSession.school_id == old.id))
            db.execute(delete(CustomCheckpoint).where(CustomCheckpoint.school_id == old.id))
            db.execute(delete(CustomSubject).where(CustomSubject.school_id == old.id))
            db.execute(delete(Plan).where(Plan.school_id == old.id))
            db.execute(delete(RoadmapItem).where(RoadmapItem.roadmap_id.in_(
                select(Roadmap.id).where(Roadmap.school_id == old.id))))
            db.execute(delete(Roadmap).where(Roadmap.school_id == old.id))
            db.execute(delete(ParentAccount).where(ParentAccount.school_id == old.id))
            db.execute(delete(Child).where(Child.class_id.in_(select(Classroom.id).where(Classroom.school_id == old.id))))
            db.execute(delete(Classroom).where(Classroom.school_id == old.id))
            db.execute(delete(Teacher).where(Teacher.school_id == old.id))
            db.execute(delete(School).where(School.id == old.id))
            db.commit()

        sch = School(name="डेमो प्राथमिक विद्यालय", code=DEMO_CODE)
        db.add(sch)
        db.flush()
        teacher = Teacher(school_id=sch.id, name="आशा शिक्षिका", pin_hash=hash_pin(TEACHER_PIN))
        db.add(teacher)
        db.flush()

        classes = {}
        for grade, names, section in ((2, NAMES_2A, "A"), (3, NAMES_3A, "A")):
            cls = Classroom(school_id=sch.id, teacher_id=teacher.id, grade=grade, section=section,
                            label=f"कक्षा {grade}{section}")
            db.add(cls)
            db.flush()
            classes[cls.school_id, grade] = cls
            for i, nm in enumerate(names, start=1):
                db.add(Child(class_id=cls.id, roll_no=i, first_name=nm, consent_on=date.today() - timedelta(days=30),
                             consent_source="parent_form_photo"))
            db.flush()
            # roadmaps for both subjects (confirmed)
            for subject in ("numeracy", "literacy"):
                rm = Roadmap(school_id=sch.id, class_id=cls.id, subject=subject, version=1,
                             source="template", confirmed_by=teacher.id)
                db.add(rm)
                db.flush()
                for it in content.template_roadmap(subject, grade):
                    db.add(RoadmapItem(roadmap_id=rm.id, position=it["position"], chapter=it["chapter"],
                                       checkpoint_id=it["checkpoint_id"]))

        rng = random.Random(42)
        now = utcnow()
        db.flush()
        cls2 = classes[sch.id, 2]
        cls3 = classes[sch.id, 3]

        # --- class 2A: 3 weeks of evidence with a deliberate structure
        kids2 = list(db.scalars(select(Child).where(Child.class_id == cls2.id).order_by(Child.roll_no)))
        sub_borrow = ["N.G2.sub_2digit_no_borrow", "N.G2.sub_2digit_borrow"]
        add_carry = ["N.G2.add_2digit_no_carry", "N.G2.add_2digit_carry"]
        pv = ["N.G2.place_value_99"]
        lit = [("L.G1.swar", "L.G1.vyanjan"), ("L.G1.matra_basic",), ("L.G1.read_matra_words",),
               ("L.G2.all_matras",), ("L.G2.word_formation",)]
        for idx, k in enumerate(kids2):
            base_day = 21
            # group assignment by idx (deterministic, matches the demo story)
            if idx < 5:          # Group 1: borrowing
                profile = {"borrow": "incorrect", "nocarry": "correct", "pv": "correct", "carry": "partial"}
            elif idx < 9:        # Group 2: add with carry
                profile = {"borrow": "correct", "nocarry": "correct", "pv": "correct", "carry": "incorrect"}
            elif idx < 12:       # Group 3: place value
                profile = {"borrow": "incorrect", "nocarry": "incorrect", "pv": "incorrect", "carry": "incorrect"}
            elif idx < 14:       # unassessed starters (little evidence)
                profile = {"borrow": None, "nocarry": None, "pv": None, "carry": None}
            else:                # on track
                profile = {"borrow": "correct", "nocarry": "correct", "pv": "correct", "carry": "correct"}
            for d in range(base_day, 0, -1):
                at = now - timedelta(days=d, hours=rng.randint(0, 5))
                if d in (18, 13, 7, 3) and profile["borrow"] is not None:
                    _ev(db, sch.id, cls2.id, k.id, sub_borrow[0], profile["nocarry"], "teacher_tap", at, 1.0)
                if d in (16, 11, 5, 1) and profile["borrow"] is not None:
                    r = "incorrect" if profile["borrow"] == "incorrect" and d > 4 else (
                        "partial" if profile["borrow"] == "incorrect" else profile["borrow"])
                    _ev(db, sch.id, cls2.id, k.id, sub_borrow[1], r, "photo_work" if d % 2 else "teacher_tap", at,
                        0.9, "smaller_minus_larger" if r == "incorrect" else None)
                if d in (15, 9, 2) and profile["carry"] is not None:
                    _ev(db, sch.id, cls2.id, k.id, add_carry[1], profile["carry"], "photo_work", at, 0.85)
                if d in (17, 8) and profile["pv"] is not None:
                    _ev(db, sch.id, cls2.id, k.id, pv[0], profile["pv"], "teacher_tap", at, 1.0)
            # literacy: different children have different gaps
            lit_level = idx % 5
            for lvl, cps in enumerate(lit):
                if lvl >= lit_level:
                    for cp in cps:
                        at = now - timedelta(days=14 - lvl * 2, hours=1)
                        res = "incorrect" if lvl == lit_level else "correct"
                        src = rng.choice(["class_voice", "teacher_tap"])
                        _ev(db, sch.id, cls2.id, k.id, cp, res, src, at, 0.8 if src == "class_voice" else 1.0,
                            "confuses_sa_sha" if cp == "L.G1.vyanjan" and res == "incorrect" else None)
            # one absent day (no evidence), as real life
        # marks: a couple of absent rows today for two children
        for k in kids2[:2]:
            db.add(Attendance(school_id=sch.id, class_id=cls2.id, child_id=k.id, day=school_today(), present=False))

        # --- class 3A: lighter history
        kids3 = list(db.scalars(select(Child).where(Child.class_id == cls3.id).order_by(Child.roll_no)))
        for idx, k in enumerate(kids3):
            for d, cp, res in ((9, "N.G3.mult_concept", "correct" if idx % 3 else "incorrect"),
                               (6, "N.G3.tables_2_5", "correct" if idx % 2 else "partial"),
                               (2, "L.G2.fluency_45_60", "correct" if idx < 20 else "incorrect")):
                _ev(db, sch.id, cls3.id, k.id, cp, res, "teacher_tap",
                    now - timedelta(days=d), 1.0)

        # --- demo parent account for the child in group 3 (roll 12)
        demo_child = kids2[11]
        db.add(ParentAccount(school_id=sch.id, child_id=demo_child.id, phone_hash=hash_phone(PARENT_PHONE),
                             pin_hash=hash_pin(PARENT_PIN)))
        rahul = demo_child
        for d in (2, 1):
            db.add(HomeSession(school_id=sch.id, child_id=rahul.id, started_at=now - timedelta(days=d),
                               ended_at=now - timedelta(days=d, hours=-1), evidence_count=7,
                               summary_hi="घर पर 7 गतिविधियाँ कीं।\nमात्रा वाले शब्दों पर अभ्यास चाहिए।"))

        db.commit()
        return {"school_code": DEMO_CODE, "teacher_pin": TEACHER_PIN, "parent_pin": PARENT_PIN,
                "parent_phone": PARENT_PHONE, "parent_child_roll": rahul.roll_no,
                "classes": [{"grade": g, "section": c.section, "label": c.label, "children": len(NAMES_2A if g == 2 else NAMES_3A)}
                            for (sid, g), c in classes.items()]}
    finally:
        db.close()


def seed_if_empty() -> None:
    init_db()
    db = SessionLocal()
    try:
        has = db.scalar(select(School).where(School.code == DEMO_CODE))
    finally:
        db.close()
    if not has:
        seed()


if __name__ == "__main__":
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
