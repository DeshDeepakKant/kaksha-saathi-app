"""DB-facing helpers: evidence → statuses → groups → plans. Shared by teacher and parent APIs."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import features
from app.models.tables import (
    Attendance, Child, Classroom, Evidence, Plan, Roadmap, RoadmapItem,
)
from app.services import mastery
from app.services.content import Content, get_content
from app.services.grouping import group_class
from app.services.plan_templates import render_group


def current_roadmap(db: Session, class_id: int, subject: str) -> Roadmap | None:
    return db.scalar(select(Roadmap).where(Roadmap.class_id == class_id, Roadmap.subject == subject)
                     .order_by(Roadmap.version.desc()).limit(1))


def roadmap_checkpoint_ids(roadmap: Roadmap | None) -> list[str]:
    return [i.checkpoint_id for i in roadmap.items] if roadmap else []


def class_children(db: Session, class_id: int) -> list[Child]:
    return list(db.scalars(select(Child).where(Child.class_id == class_id, Child.active)
                           .order_by(Child.roll_no)))


def evidence_rows(db: Session, child_ids: list[int]) -> dict[int, dict[str, list[mastery.Ev]]]:
    out: dict[int, dict[str, list[mastery.Ev]]] = {c: {} for c in child_ids}
    if not child_ids:
        return out
    for e in db.scalars(select(Evidence).where(Evidence.child_id.in_(child_ids),
                                               Evidence.status == "confirmed")):
        out.setdefault(e.child_id, {}).setdefault(e.checkpoint_id, []).append(
            mastery.Ev(result=e.result, source=e.source, confidence=e.confidence, at=e.at, id=e.id,
                       misconception=e.misconception))
    return out


def child_statuses(db: Session, child_ids: list[int], now: datetime | None = None) -> dict[int, dict[str, mastery.StatusResult]]:
    rows = evidence_rows(db, child_ids)
    return {cid: {cp: mastery.status_for(evs, now) for cp, evs in cps.items()} for cid, cps in rows.items()}


def statuses_plain(st: dict[int, dict[str, mastery.StatusResult]]) -> dict[int, dict[str, str]]:
    return {cid: {cp: r.status for cp, r in cps.items()} for cid, cps in st.items()}


def attendance_today(db: Session, class_id: int, day: date) -> dict[int, bool]:
    return {a.child_id: a.present for a in db.scalars(
        select(Attendance).where(Attendance.class_id == class_id, Attendance.day == day))}


def build_groups(db: Session, cls: Classroom, subject: str, now: datetime | None = None):
    children = class_children(db, cls.id)
    st = child_statuses(db, [c.id for c in children], now)
    st_plain = statuses_plain(st)
    today = (now or datetime.now(timezone.utc)).date()
    att = attendance_today(db, cls.id, today)
    absent = {cid for cid, present in att.items() if not present}
    # "needs assessment": absent today, or no evidence at all in this subject's roadmap
    roadmap = current_roadmap(db, cls.id, subject)
    cps = set(roadmap_checkpoint_ids(roadmap))
    learning = {cid: {cp: s for cp, s in cps_.items() if cp in cps} for cid, cps_ in st_plain.items()}
    needs = {cid for cid in learning if cid in absent}
    return group_class(get_content(), learning, needs), st, children, roadmap


def todays_plan(db: Session, cls: Classroom, subject: str, for_date: date, content: Content,
                force: bool = False) -> Plan:
    existing = db.scalar(select(Plan).where(Plan.class_id == cls.id, Plan.subject == subject,
                                            Plan.for_date == for_date))
    if existing and not force:
        return existing
    grouping, st, children, roadmap = build_groups(db, cls, subject)
    by_id = {c.id: c for c in children}
    groups = [{"key": g.key, "checkpoint_id": g.checkpoint_id, "title_hi": g.title_hi,
               "title_en": g.title_en, "chapter": g.chapter, "status": g.status,
               "members": [by_id[m].roll_no for m in g.members if m in by_id],
               "unassessed": False, "merged_from": g.merged_from, "whole_class_flag": g.whole_class_flag,
               "reason": g.reason}
              for g in grouping.groups]
    if grouping.unassessed:
        groups.append({"key": "assess_first", "checkpoint_id": "", "title_hi": "मूल्यांकन बाकी", "title_en": "Assessment pending",
                       "chapter": "", "status": "not_started", "members": [by_id[m].roll_no for m in grouping.unassessed if m in by_id],
                       "unassessed": True, "merged_from": [], "whole_class_flag": False, "reason": "unassessed"})
    real_groups = [g for g in groups if not g["unassessed"]]
    if real_groups:
        proposal = features.plan_day(db, school_id=cls.school_id, grade=cls.grade, subject=subject,
                                     day=for_date.isoformat(), groups=real_groups, content=content)
        payload = proposal.payload
        generated_by = "ai" if proposal.ai_status == "ready" else "fallback"
    else:
        payload = {"groups": [], "whole_class_note_hi": "आज किसी समूह के लिए योजना की ज़रूरत नहीं — या मूल्यांकन बाकी है।",
                   "today_observation_to_collect_hi": ""}
        generated_by = "fallback"
    by_roll = {c.roll_no: {"first_name": c.first_name, "id": c.id} for c in children}
    rendered = [render_group(g, by_roll) for g in payload.get("groups", [])]
    for g in rendered:
        members = [by_roll[r] for r in (g.get("members") or _member_rolls(groups, g["key"])) if r in by_roll]
        g["members"] = members
        act = content.activities.get(g.get("activity_id"))
        g["activity"] = ({k: act.get(k) for k in ("id", "title_hi", "steps_hi", "materials_hi", "blackboard_hi",
                                                 "source_doc")} if act else None)
    payload = {"groups": rendered, "assess_first": next((g for g in groups if g["unassessed"]), None),
               "whole_class_note_hi": payload.get("whole_class_note_hi", ""),
               "today_observation_to_collect_hi": payload.get("today_observation_to_collect_hi", ""),
               "generated_by": generated_by}
    if existing:
        existing.payload = payload
        existing.generated_by = generated_by
        db.flush()
        return existing
    plan = Plan(school_id=cls.school_id, class_id=cls.id, subject=subject, for_date=for_date,
                generated_by=generated_by, payload=payload)
    db.add(plan)
    db.flush()
    return plan


def _member_rolls(groups: list[dict], key: str) -> list[int]:
    for g in groups:
        if g["key"] == key:
            return g["members"]
    return []


def child_profile(db: Session, child: Child, roadmap: Roadmap | None, content: Content,
                  now: datetime | None = None) -> dict:
    st = child_statuses(db, [child.id], now)[child.id]
    evs = evidence_rows(db, [child.id])[child.id]
    items = []
    for it in (roadmap.items if roadmap else []):
        cp = content.checkpoints.get(it.checkpoint_id)
        r = st.get(it.checkpoint_id)
        e = evs.get(it.checkpoint_id, [])
        misc = [x.misconception for x in e if x.misconception]
        items.append({
            "checkpoint_id": it.checkpoint_id, "chapter": it.chapter,
            "title_hi": cp.title_hi if cp else (it.custom_title or it.checkpoint_id),
            "title_en": cp.title_en if cp else "",
            "status": r.status if r else "not_started",
            "confidence": r.confidence if r else 0.0,
            "improving": r.improving if r else False,
            "ceiling_applied": r.ceiling_applied if r else False,
            "evidence_count": len(e),
            "last_at": max((x.at for x in e), default=None),
            "misconception_top": _top_misc(misc),
        })
    return {"child": {"id": child.id, "first_name": child.first_name, "roll_no": child.roll_no},
            "subject": roadmap.subject if roadmap else None,
            "items": items}


def _top_misc(misc: list[str]) -> str | None:
    if not misc:
        return None
    return max(set(misc), key=misc.count)
