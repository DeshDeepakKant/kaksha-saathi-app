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
    AiCall, Attendance, CaptureSession, Child, Classroom, Evidence, GroupSession, HomeSession,
    InterventionLog, ParentAccount, Plan, Roadmap, RoadmapItem, School, Teacher, UsageCounter, utcnow,
    CustomCheckpoint, CustomSubject, VoiceSession, VoiceTurn, AppMeta, TextbookMap,
)
from app.services import level_check, tips
from app.services.content import get_content
from app.services.ledger import school_today

DEMO_CODE = "DEMO"
# Bump when the demo story changes: the next start rebuilds the DEMO school once (other schools
# are never touched). Needed because the live database is persistent (Neon), so restarts no longer
# reseed it.
SEED_VERSION = "2026-10-31-english"
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


BORROW = "N.G2.sub_2digit_borrow"


def _seed_group_sessions(db, sch: int, cls: Classroom, teacher: int, kids: list[Child], now: datetime) -> None:
    """Three past borrowing lessons for 2A (follow-ups and "did it work?" on first boot).

    Roll 3 sat through all three and is still behind (stuck); rolls 1-2 joined for the last two and
    improved; roll 5 was absent on the second day and has not been re-checked since the third.
    """
    content = get_content()
    cp = content.checkpoints[BORROW]
    act = next(iter(content.activities_for({BORROW})), {}).get("id")
    for days_ago, idxs in ((13, (2, 3)), (9, (0, 1, 2, 3, 4)), (3, (0, 1, 2, 4))):
        done_at = now - timedelta(days=days_ago)
        members = [{"id": kids[i].id, "first_name": kids[i].first_name} for i in idxs]
        group = {"key": BORROW, "checkpoint_id": BORROW, "title_hi": cp.title_hi, "title_en": cp.title_en,
                 "activity_id": act, "members": members, "nipun_ref": cp.nipun_ref or "", "time_min": 10}
        plan = Plan(school_id=sch, class_id=cls.id, subject="numeracy", for_date=school_today(done_at),
                    generated_by="fallback", created_at=done_at,
                    payload={"groups": [group], "assess_first": None, "whole_class_note_hi": "",
                             "today_observation_to_collect_hi": "", "generated_by": "fallback"})
        db.add(plan)
        db.flush()
        db.add(InterventionLog(school_id=sch, plan_id=plan.id, group_key=BORROW, done_at=done_at))
        db.add(GroupSession(school_id=sch, class_id=cls.id, plan_id=plan.id, subject="numeracy", group_key=BORROW,
                            checkpoint_id=BORROW, activity_id=act, member_ids=[m["id"] for m in members],
                            done_at=done_at, done_by=teacher))
    db.add(Attendance(school_id=sch, class_id=cls.id, child_id=kids[4].id,
                      day=school_today(now - timedelta(days=9)), present=False))


# ------------------------------------------------------------------ English (third built-in subject)
EN = "english"
EN_CPS = ("E.G1.letter_names", "E.G1.letter_sounds", "E.G1.oral_vocab", "E.G1.build_cvc", "E.G1.read_cvc",
          "E.G1.sight_words", "E.G1.read_short_sent", "E.G2.blends_digraphs", "E.G2.read_sentences",
          "E.G3.sentence_formation", "E.G3.read_passage")
_CONF = {"teacher_tap": 1.0, "class_voice": 0.8, "photo_work": 0.85, "home_voice": 0.8}


def _en_ready(content) -> bool:
    """The English demo needs the English lessons; without them (content not installed) it is skipped."""
    return all(cp in content.checkpoints for cp in EN_CPS)


def _misc(content, cp: str, n: int = 0) -> str | None:
    """A misconception of the lesson, preferring one that has a reviewed parent tip."""
    ms = list(content.checkpoints[cp].misconceptions)
    ms = [m for m in ms if tips.get_tip(m)] or ms
    return ms[n % len(ms)] if ms else None


def _en_ev(db, sch, cls, child, cp, rows, now, rng=None, base_hour=2):
    """`rows`: (days_ago, result[, source[, misconception]]). Source defaults to a teacher tap."""
    for r in rows:
        d, result = r[0], r[1]
        src = r[2] if len(r) > 2 and r[2] else "teacher_tap"
        misc = r[3] if len(r) > 3 else None
        _ev(db, sch, cls, child, cp, result, src, now - timedelta(days=d, hours=base_hour), _CONF[src], misc)


def _en_session_plan(db, sch: int, cls: Classroom, teacher: int, kids: list[Child], now: datetime,
                     content, days_ago: int, groups: list[tuple[str, tuple[int, ...], int]]) -> None:
    """One past English plan (a day's groups) with each group marked Done, like the borrowing story.
    `groups`: (checkpoint id, member indexes, activity index in that lesson's library list)."""
    done_at = now - timedelta(days=days_ago)
    rendered, sessions = [], []
    for cp_id, idxs, which in groups:
        cp = content.checkpoints[cp_id]
        acts = content.activities_for({cp_id})
        act = acts[which % len(acts)]["id"] if acts else None
        members = [{"id": kids[i].id, "first_name": kids[i].first_name} for i in idxs]
        rendered.append({"key": cp_id, "checkpoint_id": cp_id, "title_hi": cp.title_hi, "title_en": cp.title_en,
                         "activity_id": act, "members": members, "nipun_ref": cp.nipun_ref or "", "time_min": 10})
        sessions.append((cp_id, act, members))
    plan = Plan(school_id=sch, class_id=cls.id, subject=EN, for_date=school_today(done_at),
                generated_by="fallback", created_at=done_at,
                payload={"groups": rendered, "assess_first": None, "whole_class_note_hi": "",
                         "today_observation_to_collect_hi": "", "generated_by": "fallback"})
    db.add(plan)
    db.flush()
    for cp_id, act, members in sessions:
        db.add(InterventionLog(school_id=sch, plan_id=plan.id, group_key=cp_id, done_at=done_at))
        db.add(GroupSession(school_id=sch, class_id=cls.id, plan_id=plan.id, subject=EN, group_key=cp_id,
                            checkpoint_id=cp_id, activity_id=act, member_ids=[m["id"] for m in members],
                            done_at=done_at, done_by=teacher))


def _seed_english(db, sch: int, cls2: Classroom, cls3: Classroom, teacher: int, kids2: list[Child],
                  kids3: list[Child], demo_child: Child, now: datetime) -> None:
    """English for the demo school (docs/english_subject_contract.md). Own `Random(42)` and written after
    the Maths and Hindi story, so those rows, ids and statuses are exactly what they were.

    Class 2A, by roll-order index (the board is deterministic from this evidence):
      2-5 letter sounds group (letters known, sounds not), 6-10 three-letter words group,
      14-18 sentences group, 11 (the demo parent's child) + 19-21 blends group, 22-29 and 0-1 on track,
      12-13 no English evidence yet (unassessed). Seven past group lessons (letter sounds x3, words x2,
      sentences x2) give the follow-ups: roll 3 stuck, roll 6 not re-checked after the last words lesson,
      roll 10 missed the first words lesson, rolls 13-14 not checked at all.
    """
    content = get_content()
    rng = random.Random(42)
    LN, LS, CVC, RCVC, SENT, SIGHT, BL = ("E.G1.letter_names", "E.G1.letter_sounds", "E.G1.build_cvc",
                                          "E.G1.read_cvc", "E.G1.read_short_sent", "E.G1.sight_words",
                                          "E.G2.blends_digraphs")
    tap, voice, photo, home = "teacher_tap", "class_voice", "photo_work", "home_voice"

    def ev(i, cp, rows):
        _en_ev(db, sch, cls2.id, kids2[i].id, cp, rows, now, base_hour=1 + i % 4)

    KNOWN_DAYS = {LN: (17, 10), LS: (16, 9), RCVC: (13, 6), SENT: (8, 2), SIGHT: (7, 3)}

    def known(i, *cps):  # lessons known at school: correct checks, sources mixed
        for cp in cps:
            ev(i, cp, [(d, "correct", rng.choice((tap, voice, photo))) for d in KNOWN_DAYS[cp]])

    # on track: 0-1 (absent today, so the board lists them as unassessed) and 22-29
    for i in (0, 1, *range(22, 30)):
        known(i, LN, LS, RCVC, SENT, SIGHT)
        if i in (24, 26):
            ev(i, SIGHT, [(3, "correct", home)])
    # 2-5: know the letters, not their sounds
    for i in (2, 3, 4, 5):
        ev(i, LN, [(19, "correct", tap), (12, "correct", voice)])
    m_ls = _misc(content, LS)
    ev(2, LS, [(17, "incorrect", tap, m_ls), (12, "incorrect", voice, m_ls), (6, "incorrect", photo), (1, "incorrect", tap, m_ls)])
    ev(3, LS, [(17, "incorrect", tap, m_ls), (12, "incorrect", voice, m_ls), (6, "partial", photo), (1, "correct", tap)])
    ev(4, LS, [(17, "incorrect", tap, m_ls), (12, "incorrect", voice, m_ls), (2, "partial", tap)])
    ev(5, LS, [(17, "incorrect", tap, m_ls), (12, "incorrect", voice, m_ls), (6, "partial", photo)])
    ev(3, LN, [(5, "correct", home)])
    # 6-10: letters and sounds fine, cannot join sounds into a word
    for i in range(6, 11):
        known(i, LN, LS)
    m_cvc = _misc(content, CVC)
    for i, tail in ((6, [(2, "correct", tap)]), (7, [(2, "incorrect", tap, m_cvc)]), (8, []), (9, []), (10, [])):
        ev(i, CVC, [(15, "incorrect", tap, m_cvc), (10, "incorrect", voice, m_cvc), (6, "partial", photo), *tail])
    # 14-18: read 3-letter words, stumble on a whole sentence
    for i in range(14, 19):
        known(i, LN, LS, RCVC)
    m_sent = _misc(content, SENT)
    tails = {14: [(3, "correct", tap)], 15: [(3, "partial", tap)], 16: [(2, "correct", voice)], 17: [], 18: []}
    for i in range(14, 19):
        ev(i, SENT, [(13, "incorrect", tap, m_sent), (9, "partial", photo), (6, "incorrect", tap, m_sent), *tails[i]])
    # 19-21 and the demo child (11): the 3-letter words are secure, blends are not
    m_bl = _misc(content, BL)
    for i in (19, 20, 21):
        known(i, LN, LS, RCVC)
        ev(i, BL, [(12, "incorrect", tap, m_bl), (6, "incorrect", photo, m_bl), (1, "partial", tap)])
    # 12-13: no English evidence yet

    # the demo parent's child: letters learned over a month (growth), one lesson learned 3 days ago
    # (the celebration), blends getting better (a "getting better" moment and a tip). The older lessons were
    # learned more than 14 days ago, so only letter sounds is a celebration.
    ev(11, LN, [(29, "correct"), (25, "correct"), (8, "correct")])
    ev(11, "E.G1.oral_vocab", [(22, "correct"), (18, "correct"), (6, "correct")])
    ev(11, CVC, [(20, "correct"), (16, "correct"), (4, "correct")])
    ev(11, RCVC, [(18, "correct"), (15, "correct"), (2, "correct")])
    ev(11, LS, [(15, "incorrect"), (10, "partial"), (5, "correct"), (3, "correct"), (1, "correct")])
    ev(11, BL, [(11, "incorrect", tap, m_bl), (9, "incorrect", tap, m_bl), (4, "partial"), (1, "correct")])

    # past English group lessons: one plan per day, each group marked Done
    plan = lambda d, *g: _en_session_plan(db, sch, cls2, teacher, kids2, now, content, d, list(g))  # noqa: E731
    plan(13, (LS, (2, 3), 0))
    plan(11, (CVC, (6, 7, 8), 0))
    plan(10, (SENT, (14, 15, 16, 17, 18), 0))
    plan(8, (LS, (2, 3, 4, 5), 0))
    plan(5, (SENT, (14, 15, 16, 17, 18), 0))
    plan(4, (CVC, (6, 7, 8, 9, 10), 0))
    plan(3, (LS, (2, 3, 4, 5), 1))
    db.add(Attendance(school_id=sch, class_id=cls2.id, child_id=kids2[9].id,
                      day=school_today(now - timedelta(days=11)), present=False))

    # class 3A: a light English history
    for idx, k in enumerate(kids3):
        for d, cp, res, src in ((8, "E.G2.read_sentences", "correct" if idx % 3 else "partial", tap),
                                (5, "E.G3.sentence_formation", "correct" if idx % 2 else "incorrect", voice),
                                (2, "E.G3.read_passage", "correct" if idx < 20 else "partial", tap)):
            _ev(db, sch, cls3.id, k.id, cp, res, src, now - timedelta(days=d, hours=1), _CONF[src])


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
            db.execute(delete(GroupSession).where(GroupSession.school_id == old.id))
            level_check.delete_for_school(db, old.id)
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
            db.execute(delete(TextbookMap).where(TextbookMap.school_id == old.id))
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

        # English roadmaps (confirmed template) once the Maths and Hindi rows exist, so their ids stay as they were
        for cls in classes.values():
            items = content.template_roadmap(EN, cls.grade)
            if not items:
                continue
            rm = Roadmap(school_id=sch.id, class_id=cls.id, subject=EN, version=1, source="template",
                         confirmed_by=teacher.id)
            db.add(rm)
            db.flush()
            for it in items:
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
                if d in (16, 11, 5, 1) and profile["borrow"] is not None and not (d == 1 and idx == 4):
                    r = "incorrect" if profile["borrow"] == "incorrect" and d > 4 else (
                        "partial" if profile["borrow"] == "incorrect" else profile["borrow"])
                    if d == 1 and idx in (0, 1):
                        r = "correct"  # improved after the borrowing lessons (see _seed_group_sessions)
                    _ev(db, sch.id, cls2.id, k.id, sub_borrow[1], r, "photo_work" if d % 2 else "teacher_tap", at,
                        0.9, "smaller_minus_larger" if r == "incorrect" else None)
                if d == 2 and idx in (0, 1):
                    _ev(db, sch.id, cls2.id, k.id, sub_borrow[1], "correct", "teacher_tap", at, 1.0)
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
        _seed_group_sessions(db, sch.id, cls2, teacher.id, kids2, now)
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

        # --- the demo child's recent school story, so the parent app has something true to show:
        # early skills learned over three weeks (journey stars + growth), one learned 3 days ago
        # (celebration), matras getting better (a "getting better" moment), absent yesterday (catch-up)
        kid = demo_child.id
        for cp, days in (("N.G1.count_to_20", (20, 13, 6)), ("N.G1.add_single", (16, 9, 4)),
                         ("L.G1.swar", (11, 4)), ("L.G1.vyanjan", (10, 3))):
            for d in days:
                _ev(db, sch.id, cls2.id, kid, cp, "correct", "teacher_tap", now - timedelta(days=d, hours=2), 1.0)
        for d, res in ((15, "incorrect"), (10, "partial"), (5, "correct"), (3, "correct"), (1, "correct")):
            _ev(db, sch.id, cls2.id, kid, "N.G1.sub_single", res, "teacher_tap", now - timedelta(days=d, hours=2), 1.0)
        for d, res in ((6, "partial"), (2, "correct")):
            _ev(db, sch.id, cls2.id, kid, "L.G1.matra_basic", res, "teacher_tap", now - timedelta(days=d, hours=1), 1.0)
        db.add(Attendance(school_id=sch.id, class_id=cls2.id, child_id=kid,
                          day=school_today() - timedelta(days=1), present=False))

        if _en_ready(content):
            _seed_english(db, sch.id, cls2, cls3, teacher.id, kids2, kids3, demo_child, now)

        level_check.demo_seed(db, sch.id)

        db.merge(AppMeta(key="demo_seed_version", value=SEED_VERSION))
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


def reseed_demo_if_outdated() -> bool:
    """Rebuild the DEMO school once when its seed is older than SEED_VERSION. Returns True if it did."""
    init_db()
    db = SessionLocal()
    try:
        row = db.get(AppMeta, "demo_seed_version")
        current = row.value if row else None
    finally:
        db.close()
    if current == SEED_VERSION:
        return False
    seed()
    return True


if __name__ == "__main__":
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
