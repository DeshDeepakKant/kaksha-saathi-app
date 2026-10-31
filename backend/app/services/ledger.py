"""DB-facing helpers: evidence → statuses → groups → plans. Shared by teacher and parent APIs."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import features
from app.models.tables import (
    Attendance, Child, Classroom, Evidence, Plan, Roadmap, RoadmapItem,
)
from app.services import content_lang, mastery
from app.services.content import Content, get_content
from app.services.grouping import group_class
from app.services.plan_templates import render_group


# Schools run on Indian time: before 05:30 IST the UTC date is still "yesterday".
IST = timezone(timedelta(hours=5, minutes=30))


def school_today(now: datetime | None = None) -> date:
    """Today's date for the school register and board (IST), whatever the server's timezone."""
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(IST).date()


def current_roadmap(db: Session, class_id: int, subject: str) -> Roadmap | None:
    return db.scalar(select(Roadmap).where(Roadmap.class_id == class_id, Roadmap.subject == subject)
                     .order_by(Roadmap.version.desc()).limit(1))


def roadmap_checkpoint_ids(roadmap: Roadmap | None) -> list[str]:
    return [i.checkpoint_id for i in roadmap.items] if roadmap else []


def class_children(db: Session, class_id: int) -> list[Child]:
    return list(db.scalars(select(Child).where(Child.class_id == class_id, Child.active)
                           .order_by(Child.roll_no)))


def evidence_rows(db: Session, child_ids: list[int],
                  before: datetime | None = None) -> dict[int, dict[str, list[mastery.Ev]]]:
    out: dict[int, dict[str, list[mastery.Ev]]] = {c: {} for c in child_ids}
    if not child_ids:
        return out
    q = select(Evidence).where(Evidence.child_id.in_(child_ids), Evidence.status == "confirmed")
    if before is not None:
        q = q.where(Evidence.at < before)
    for e in db.scalars(q):
        out.setdefault(e.child_id, {}).setdefault(e.checkpoint_id, []).append(
            mastery.Ev(result=e.result, source=e.source, confidence=e.confidence, at=e.at, id=e.id,
                       misconception=e.misconception))
    return out


def child_statuses(db: Session, child_ids: list[int], now: datetime | None = None,
                   before: datetime | None = None) -> dict[int, dict[str, mastery.StatusResult]]:
    """`before` ignores evidence recorded at or after that moment (e.g. during a home session)."""
    rows = evidence_rows(db, child_ids, before)
    return {cid: {cp: mastery.status_for(evs, now) for cp, evs in cps.items()} for cid, cps in rows.items()}


def statuses_plain(st: dict[int, dict[str, mastery.StatusResult]]) -> dict[int, dict[str, str]]:
    return {cid: {cp: r.status for cp, r in cps.items()} for cid, cps in st.items()}


def attendance_today(db: Session, class_id: int, day: date) -> dict[int, bool]:
    return {a.child_id: a.present for a in db.scalars(
        select(Attendance).where(Attendance.class_id == class_id, Attendance.day == day))}


def nipun_ref(content: Content, checkpoint_id: str | None) -> str:
    cp = content.checkpoints.get(checkpoint_id or "")
    return getattr(cp, "nipun_ref", "") or "" if cp else ""


def class_roadmap_cps(db: Session, cls: Classroom, subject: str) -> list[str]:
    """Checkpoints this class works on in `subject`: confirmed roadmap, else the template."""
    return roadmap_checkpoint_ids(current_roadmap(db, cls.id, subject)) or [
        i["checkpoint_id"] for i in get_content().template_roadmap(subject, cls.grade)]


def group_snapshot(db: Session, cls: Classroom, subject: str, at: datetime | None = None):
    """Each child's group key (None = on track / not assessed) and gap rank as of `at` (None = now).

    Same grouping rules as the board, but attendance is ignored: a child who was absent is not "moved".
    """
    children = class_children(db, cls.id)
    ids = [c.id for c in children]
    st = statuses_plain(child_statuses(db, ids, now=at, before=at))
    cps = set(class_roadmap_cps(db, cls, subject))
    learning = {cid: {cp: s for cp, s in cps_.items() if cp in cps} for cid, cps_ in st.items()}
    needs = {cid for cid in learning if not learning[cid]}
    grouping = group_class(get_content(), learning, needs)
    keys: dict[int, str | None] = {cid: None for cid in ids}
    for g in grouping.groups:
        for m in g.members:
            keys[m] = g.key
    return keys, {cid: gap.rank for cid, gap in grouping.gaps.items()}, children


def status_timeline(db: Session, child: Child, cps: list[str], now: datetime, weeks: int) -> list[dict]:
    """Status counts over `cps` at each of the last `weeks` week-ends (the last point is `now`)."""
    cp_set = set(cps)
    evs = {cp: rows for cp, rows in evidence_rows(db, [child.id])[child.id].items() if cp in cp_set}
    points = []
    for i in range(weeks):
        back = weeks - 1 - i
        day = now.date() - timedelta(days=7 * back)
        at = now if back == 0 else datetime.combine(day + timedelta(days=1), datetime.min.time())
        at_aware = mastery._aware(at)
        counts = {"on_track": 0, "needs_practice": 0, "needs_intervention": 0}
        for cp, rows in evs.items():
            seen = [e for e in rows if mastery._aware(e.at) < at_aware]
            st = mastery.status_for(seen, at).status if seen else "not_started"
            if st in counts:
                counts[st] += 1
        points.append({"week_end": day.isoformat(), **counts,
                       "assessed": sum(counts.values()), "total": len(cp_set)})
    return points


def build_groups(db: Session, cls: Classroom, subject: str, now: datetime | None = None):
    children = class_children(db, cls.id)
    st = child_statuses(db, [c.id for c in children], now)
    st_plain = statuses_plain(st)
    today = school_today(now)
    att = attendance_today(db, cls.id, today)
    absent = {cid for cid, present in att.items() if not present}
    # "needs assessment": absent today, or no evidence at all in this subject's roadmap
    roadmap = current_roadmap(db, cls.id, subject)
    cps = set(roadmap_checkpoint_ids(roadmap)) or {
        i["checkpoint_id"] for i in get_content().template_roadmap(subject, cls.grade)}
    learning = {cid: {cp: s for cp, s in cps_.items() if cp in cps} for cid, cps_ in st_plain.items()}
    needs = {cid for cid in learning if cid in absent or not learning[cid]}
    return group_class(get_content(), learning, needs), st, children, roadmap


def plan_lang(payload: dict | None) -> str:
    """The content language a saved plan was written in (plans before content languages are Hindi)."""
    return (payload or {}).get("content_lang") or content_lang.SOURCE_LANG


def todays_plan(db: Session, cls: Classroom, subject: str, for_date: date, content: Content,
                force: bool = False, lang: str = content_lang.SOURCE_LANG) -> Plan:
    """Today's plan, written in the teacher's content language `lang`. A saved plan in another language
    is rewritten (as with `force`)."""
    existing = db.scalar(select(Plan).where(Plan.class_id == cls.id, Plan.subject == subject,
                                            Plan.for_date == for_date))
    if existing and not force and plan_lang(existing.payload) == lang:
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
                                     day=for_date.isoformat(), groups=real_groups, content=content, lang=lang)
        payload = proposal.payload
        generated_by = "ai" if proposal.ai_status == "ready" else "fallback"
        if generated_by == "fallback":
            payload = _template_in_lang(db, payload, content, lang, cls.school_id)
    else:
        payload = {"groups": [], "whole_class_note_hi": "आज किसी समूह के लिए योजना की ज़रूरत नहीं, या मूल्यांकन बाकी है।",
                   "today_observation_to_collect_hi": ""}
        generated_by = "fallback"
        payload = _template_in_lang(db, payload, content, lang, cls.school_id)
    by_roll = {c.roll_no: {"first_name": c.first_name, "id": c.id} for c in children}
    rendered = [render_group(g, by_roll) for g in payload.get("groups", [])]
    cp_of = {g["key"]: g["checkpoint_id"] for g in groups}
    for g in rendered:
        members = [by_roll[r] for r in (g.get("members") or _member_rolls(groups, g["key"])) if r in by_roll]
        g["members"] = members
        g["nipun_ref"] = nipun_ref(content, cp_of.get(g["key"]))
        act = content.activities.get(g.get("activity_id"))
        g["activity"] = ({k: act.get(k) for k in ("id", "title_hi", "steps_hi", "materials_hi", "blackboard_hi",
                                                 "source_doc")} if act else None)
    assess = next((g for g in groups if g["unassessed"]), None)
    if assess:  # members as {id, first_name} like every other group (the planner input keeps roll numbers)
        assess = {**assess, "nipun_ref": "",
                  "members": [{"id": c.id, "first_name": c.first_name} for c in children
                              if c.roll_no in set(assess["members"])]}
    payload = {"groups": rendered, "assess_first": assess,
               "whole_class_note_hi": payload.get("whole_class_note_hi", ""),
               "today_observation_to_collect_hi": payload.get("today_observation_to_collect_hi", ""),
               "generated_by": generated_by, "content_lang": lang,
               **({"machine_translated": bool(payload.get("machine_translated"))}
                  if lang != content_lang.SOURCE_LANG else {})}
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


_TEMPLATE_TEXT = ("why_hi", "teacher_script_hi", "defer_note_hi")
_PLAN_TEXT = ("whole_class_note_hi", "today_observation_to_collect_hi")


def _template_in_lang(db: Session, payload: dict, content: Content, lang: str, school_id: int) -> dict:
    """A template (fallback) plan's canned Hindi in `lang`: the script from the localized library activity,
    the other canned lines machine-translated (cached). Hindi: unchanged."""
    if lang == content_lang.SOURCE_LANG:
        return payload
    out = {**payload, "groups": [dict(g) for g in payload.get("groups", [])]}
    mt = False
    slots: list[tuple] = []  # (container, key) pairs whose Hindi text gets translated in one batch
    for g in out["groups"]:
        act = content_lang.activity(content.activities.get(g.get("activity_id")), lang)
        if act is not None:
            g["teacher_script_hi"] = " ".join(act["steps_hi"])[:600]
            g["reassessment"] = act.get("reassessment", g.get("reassessment"))
            mt = mt or act["machine_translated"]
        else:
            if isinstance(g.get("reassessment"), dict) and g["reassessment"].get("ask_hi"):
                g["reassessment"] = dict(g["reassessment"])
                slots.append((g["reassessment"], "ask_hi"))
            if isinstance(g.get("generic_steps_hi"), list):
                g["generic_steps_hi"] = list(g["generic_steps_hi"])
                slots.extend((g["generic_steps_hi"], i) for i in range(len(g["generic_steps_hi"])))
        slots.extend((g, k) for k in _TEMPLATE_TEXT if g.get(k) and (k != "teacher_script_hi" or act is None))
    slots.extend((out, k) for k in _PLAN_TEXT if out.get(k))
    texts, tmt = content_lang.translate(db, [obj[k] for obj, k in slots], lang, school_id)
    for (obj, k), text in zip(slots, texts):
        obj[k] = text
    out["machine_translated"] = mt or tmt
    return out


def localize_plan(payload: dict, content: Content) -> dict:
    """Response copy of a saved plan with each group's library activity in the plan's own language
    (storage keeps the reviewed Hindi). Hindi plans are returned as they are."""
    lang = plan_lang(payload)
    if lang == content_lang.SOURCE_LANG:
        return payload
    out = dict(payload)
    out["groups"] = [{**g, "activity": content_lang.activity(g["activity"], lang)} if g.get("activity") else g
                     for g in payload.get("groups", [])]
    if any((g.get("activity") or {}).get("machine_translated") for g in out["groups"]):
        out["machine_translated"] = True
    return out


def upgrade_plan_payload(payload: dict, children: list[Child], content: Content) -> dict:
    """Plans saved before the v2 contract: members of `assess_first` were roll numbers, groups had no
    `nipun_ref`. Returns a copy in the current shape (no-op for current plans)."""
    out = dict(payload or {})
    a = out.get("assess_first")
    if a:
        by_roll = {c.roll_no: c for c in children}
        members = [m if isinstance(m, dict) else {"id": by_roll[m].id, "first_name": by_roll[m].first_name}
                   for m in a.get("members", []) if isinstance(m, dict) or m in by_roll]
        out["assess_first"] = {**a, "nipun_ref": a.get("nipun_ref", ""), "members": members}
    out["groups"] = [g if "nipun_ref" in g else {**g, "nipun_ref": nipun_ref(content, g.get("key"))}
                     for g in out.get("groups", [])]
    return out


def _member_rolls(groups: list[dict], key: str) -> list[int]:
    for g in groups:
        if g["key"] == key:
            return g["members"]
    return []


def child_profile(db: Session, child: Child, roadmap: Roadmap | None, content: Content,
                  now: datetime | None = None, subject: str | None = None, grade: int | None = None) -> dict:
    st = child_statuses(db, [child.id], now)[child.id]
    evs = evidence_rows(db, [child.id])[child.id]
    items = []
    # No confirmed roadmap yet: use the template the teacher sees in the capture sheet.
    rows = ([(i.checkpoint_id, i.chapter, i.custom_title) for i in roadmap.items] if roadmap else
            [(i["checkpoint_id"], i["chapter"], None) for i in content.template_roadmap(subject, grade)]
            if subject and grade else [])
    for checkpoint_id, chapter, custom_title in rows:
        cp = content.checkpoints.get(checkpoint_id)
        r = st.get(checkpoint_id)
        e = evs.get(checkpoint_id, [])
        misc = [x.misconception for x in e if x.misconception]
        items.append({
            "checkpoint_id": checkpoint_id, "chapter": chapter,
            "nipun_ref": nipun_ref(content, checkpoint_id),
            "title_hi": cp.title_hi if cp else (custom_title or checkpoint_id),
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
            "subject": roadmap.subject if roadmap else subject,
            "items": items}


def _top_misc(misc: list[str]) -> str | None:
    if not misc:
        return None
    return max(set(misc), key=misc.count)
