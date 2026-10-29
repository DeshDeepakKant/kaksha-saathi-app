"""Teacher follow-ups and outcomes from taught group sessions (docs/teacher_loop_contract.md).

Everything here is deterministic: code decides who needs a re-check, who is stuck, who missed group time,
who has not been checked lately, which statuses are about to fade, and whether a session moved children.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tables import Attendance, Child, Classroom, Evidence, GroupSession, Plan
from app.services import ledger, mastery
from app.services.content import Content, get_content

CAP = 20
RECHECK_DAYS = 14
STUCK_DAYS = 42
STUCK_MIN_SESSIONS = 3
MISSED_DAYS = 28
CHECK_DAYS = 14
FADE_WITHIN = 5

# "moved up/down" order: not assessed and needs intervention are both the bottom rung
ORDER = {"not_started": 0, "needs_intervention": 0, "needs_practice": 1, "on_track": 2}

STUCK_HINT = ("Try a different activity, or check the earlier step with the 2-minute probe.",
              "कोई दूसरी गतिविधि आज़माएँ, या 2 मिनट की जाँच से पिछला कदम देखें।")
STUCK_HINT_NO_ALT = ("Check the earlier step with the 2-minute probe.",
                     "2 मिनट की जाँच से पिछला कदम देखें।")


def _now(now: datetime | None) -> datetime:
    return mastery._aware(now or datetime.now(timezone.utc))


def _naive(dt: datetime) -> datetime:
    """UTC without tzinfo, the way timestamps are stored."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _day(dt: datetime) -> date:
    return ledger.school_today(dt)


def _titles(content: Content, cid: str) -> dict:
    cp = content.checkpoints.get(cid)
    return {"title_en": cp.title_en if cp else "", "title_hi": cp.title_hi if cp else cid}


def _act_title(content: Content, aid: str | None) -> str | None:
    a = content.activities.get(aid or "")
    return a.get("title_hi") if a else None


def _is_classroom(e: Evidence) -> bool:
    return e.source not in mastery.HOME_SOURCES


# ------------------------------------------------------------------ done → snapshot
def record_done(db: Session, plan: Plan, group_key: str, teacher_id: int | None) -> GroupSession | None:
    """Upsert the session for a plan group. The first snapshot is kept, so replays never move `done_at`.

    `assess_first` and unknown keys are not teaching groups (None)."""
    existing = db.scalar(select(GroupSession).where(GroupSession.plan_id == plan.id,
                                                    GroupSession.group_key == group_key))
    if existing:
        return existing
    g = next((g for g in (plan.payload or {}).get("groups", []) if g.get("key") == group_key), None)
    if g is None or group_key == "assess_first" or g.get("unassessed"):
        return None
    content = get_content()
    activity_id = g.get("activity_id")
    s = GroupSession(school_id=plan.school_id, class_id=plan.class_id, plan_id=plan.id, subject=plan.subject,
                     group_key=group_key, checkpoint_id=g.get("checkpoint_id") or group_key,
                     activity_id=activity_id if activity_id in content.activities else None,  # not "generic"
                     member_ids=_member_ids(db, plan.class_id, g.get("members") or []), done_by=teacher_id)
    db.add(s)
    db.flush()
    return s


def _member_ids(db: Session, class_id: int, members: list) -> list[int]:
    """v2 members are {id, first_name}; older plans hold roll numbers."""
    rolls = [m for m in members if isinstance(m, int)]
    by_roll = {c.roll_no: c.id for c in db.scalars(
        select(Child).where(Child.class_id == class_id, Child.roll_no.in_(rolls)))} if rolls else {}
    ids = [m["id"] if isinstance(m, dict) else by_roll.get(m) for m in members]
    return [i for i in ids if isinstance(i, int)]


def sessions(db: Session, cls: Classroom, subject: str, since: datetime) -> list[GroupSession]:
    """This class + subject's sessions done since `since`, newest first."""
    return list(db.scalars(select(GroupSession).where(
        GroupSession.class_id == cls.id, GroupSession.subject == subject,
        GroupSession.done_at >= _naive(since)).order_by(GroupSession.done_at.desc(), GroupSession.id.desc())))


def _classroom_evidence(db: Session, child_ids: list[int], since: datetime) -> list[Evidence]:
    if not child_ids:
        return []
    return [e for e in db.scalars(select(Evidence).where(
        Evidence.child_id.in_(child_ids), Evidence.status == "confirmed",
        Evidence.at >= _naive(since))) if _is_classroom(e)]


def _rechecked(evs: list[Evidence], child_id: int, checkpoint_id: str, after: datetime) -> bool:
    a = mastery._aware(after)
    return any(e.child_id == child_id and e.checkpoint_id == checkpoint_id and mastery._aware(e.at) > a
               for e in evs)


# ------------------------------------------------------------------ follow-ups
def followups(db: Session, cls: Classroom, subject: str, now: datetime | None = None) -> dict:
    now = _now(now)
    content = get_content()
    children = ledger.class_children(db, cls.id)
    by_id = {c.id: c for c in children}
    ids = list(by_id)
    rows = ledger.evidence_rows(db, ids)
    st = {cid: {cp: mastery.status_for(evs, now) for cp, evs in cps.items()} for cid, cps in rows.items()}
    recent = sessions(db, cls, subject, now - timedelta(days=STUCK_DAYS))
    evs = _classroom_evidence(db, ids, now - timedelta(days=STUCK_DAYS))
    return {"subject": subject, "generated_at": now.isoformat(),
            "recheck": recheck(recent, evs, by_id, content, now),
            "stuck": stuck(recent, st, by_id, content, now),
            "missed": missed(db, cls, recent, by_id, content, now),
            "not_checked": not_checked(db, children, subject, evs, content, now),
            "fading": fading(db, cls, subject, rows, st, by_id, content, now)}


def _child(c: Child) -> dict:
    return {"child_id": c.id, "first_name": c.first_name, "roll_no": c.roll_no}


def recheck(recent: list[GroupSession], evs: list[Evidence], by_id: dict[int, Child], content: Content,
            now: datetime) -> list[dict]:
    """Taught on an earlier day in the last 14 days, no classroom evidence on that topic since."""
    today = _day(now)
    out: dict[int, dict] = {}
    for s in recent:  # newest first, so the latest un-checked session wins
        days = (today - _day(mastery._aware(s.done_at))).days
        if not 1 <= days <= RECHECK_DAYS:
            continue
        for cid in s.member_ids:
            if cid in out or cid not in by_id or _rechecked(evs, cid, s.checkpoint_id, s.done_at):
                continue
            out[cid] = {**_child(by_id[cid]), "checkpoint_id": s.checkpoint_id,
                        **_titles(content, s.checkpoint_id), "group_key": s.group_key, "session_id": s.id,
                        "taught_on": (today - timedelta(days=days)).isoformat(), "days_since": days,
                        "has_probe": s.checkpoint_id in content.probes}
    return sorted(out.values(), key=lambda r: (-r["days_since"], r["roll_no"]))[:CAP]


def stuck(recent: list[GroupSession], st: dict, by_id: dict[int, Child], content: Content,
          now: datetime) -> list[dict]:
    """In 3+ sessions on the same topic in the last 42 days and still not on track."""
    seen: dict[tuple[int, str], list[GroupSession]] = {}
    for s in recent:
        for cid in s.member_ids:
            seen.setdefault((cid, s.checkpoint_id), []).append(s)
    out = []
    for (cid, cp), ss in seen.items():
        status = st.get(cid, {}).get(cp)
        status = status.status if status else "not_started"
        if cid not in by_id or len(ss) < STUCK_MIN_SESSIONS or status == "on_track":
            continue
        used = {s.activity_id for s in ss}
        alt = next((a for a in content.activities_for({cp}) if a["id"] not in used), None)
        hint_en, hint_hi = STUCK_HINT if alt else STUCK_HINT_NO_ALT
        out.append({**_child(by_id[cid]), "checkpoint_id": cp, **_titles(content, cp), "status": status,
                    "sessions": len(ss), "since": min(_day(mastery._aware(s.done_at)) for s in ss).isoformat(),
                    "alt_activity_id": alt["id"] if alt else None,
                    "alt_activity_title_hi": alt.get("title_hi") if alt else None,
                    "suggestion_en": hint_en, "suggestion_hi": hint_hi})
    return sorted(out, key=lambda r: (-r["sessions"], ORDER[r["status"]], r["roll_no"]))[:CAP]


def missed(db: Session, cls: Classroom, recent: list[GroupSession], by_id: dict[int, Child],
           content: Content, now: datetime) -> list[dict]:
    """Marked absent on the day a group they belong to was taught (last 28 days).

    A child belongs to a topic's group if they were a member of any of its sessions in the window
    (absent children are often left out of that day's plan). `of` = the topic's sessions they were in or missed.
    A day with no attendance row is not an absence."""
    window = [s for s in recent if mastery._aware(s.done_at) >= now - timedelta(days=MISSED_DAYS)]
    days = {_day(mastery._aware(s.done_at)) for s in window}
    absent = {(a.child_id, a.day) for a in db.scalars(select(Attendance).where(
        Attendance.class_id == cls.id, Attendance.present.is_(False), Attendance.day.in_(days)))} if days else set()
    by_cp: dict[str, list[GroupSession]] = {}
    for s in window:
        by_cp.setdefault(s.checkpoint_id, []).append(s)
    out = []
    for cp, ss in by_cp.items():
        on = [(s, _day(mastery._aware(s.done_at))) for s in ss]
        for cid in sorted({m for s in ss for m in s.member_ids if m in by_id}):
            gone = [d for _, d in on if (cid, d) in absent]
            of = sum(1 for s, d in on if cid in s.member_ids or (cid, d) in absent)
            if len(gone) >= 2 or (len(gone) >= 1 and of <= 2):
                out.append({**_child(by_id[cid]), "checkpoint_id": cp, **_titles(content, cp),
                            "missed": len(gone), "of": of, "last_missed": max(gone).isoformat()})
    return sorted(out, key=lambda r: (-r["missed"], -date.fromisoformat(r["last_missed"]).toordinal(),
                                      r["roll_no"]))[:CAP]


def _subject_cps(content: Content, subject: str) -> set[str]:
    return {cid for cid, cp in content.checkpoints.items() if cp.subject == subject}


def not_checked(db: Session, children: list[Child], subject: str, evs: list[Evidence], content: Content,
                now: datetime) -> list[dict]:
    """Active children with at most one classroom evidence row in this subject in the last 14 days."""
    cps = _subject_cps(content, subject)
    since = now - timedelta(days=CHECK_DAYS)
    counts = {c.id: 0 for c in children}
    for e in evs:
        if e.checkpoint_id in cps and mastery._aware(e.at) >= since and e.child_id in counts:
            counts[e.child_id] += 1
    quiet = [c for c in children if counts[c.id] <= 1]
    last = _last_checked(db, [c.id for c in quiet], cps)
    out = [{**_child(c), "checks_14d": counts[c.id],
            "last_checked": last[c.id].isoformat() if c.id in last else None} for c in quiet]
    return sorted(out, key=lambda r: (r["checks_14d"], r["last_checked"] or "", r["roll_no"]))[:CAP]


def _last_checked(db: Session, child_ids: list[int], cps: set[str]) -> dict[int, date]:
    if not child_ids or not cps:
        return {}
    q = (select(Evidence.child_id, Evidence.source, func.max(Evidence.at))
         .where(Evidence.child_id.in_(child_ids), Evidence.status == "confirmed", Evidence.checkpoint_id.in_(cps))
         .group_by(Evidence.child_id, Evidence.source))
    out: dict[int, date] = {}
    for cid, source, at in db.execute(q):
        if source in mastery.HOME_SOURCES or at is None:
            continue
        d = _day(mastery._aware(at))
        out[cid] = max(out.get(cid, d), d)
    return out


def fading(db: Session, cls: Classroom, subject: str, rows: dict, st: dict, by_id: dict[int, Child],
           content: Content, now: datetime) -> list[dict]:
    """Assessed statuses whose newest evidence leaves the mastery window within 5 days."""
    out = []
    for cp in ledger.class_roadmap_cps(db, cls, subject):
        for cid, child in by_id.items():
            r = st.get(cid, {}).get(cp)
            evs = rows.get(cid, {}).get(cp)
            if not r or not evs or r.status not in ("on_track", "needs_practice"):
                continue
            newest = max(mastery._aware(e.at) for e in evs)
            left = mastery.WINDOW_DAYS - (now - newest).days
            if 0 <= left <= FADE_WITHIN:
                out.append({**_child(child), "checkpoint_id": cp, **_titles(content, cp), "status": r.status,
                            "last_evidence_on": _day(newest).isoformat(), "expires_in_days": left})
    return sorted(out, key=lambda r: (r["expires_in_days"], r["roll_no"], r["checkpoint_id"]))[:CAP]


# ------------------------------------------------------------------ outcomes
def _change(before: str, after: str | None) -> str:
    if after is None:
        return "not_rechecked"
    d = ORDER[after] - ORDER[before]
    return "up" if d > 0 else "down" if d < 0 else "same"


def outcomes(db: Session, cls: Classroom, subject: str, days: int = 42, now: datetime | None = None) -> dict:
    """Did it work? Per session: status before `done_at` vs now, for children re-checked in class since."""
    now = _now(now)
    content = get_content()
    ss = sessions(db, cls, subject, now - timedelta(days=days))
    all_ids = sorted({m for s in ss for m in s.member_ids})
    kids = {c.id: c for c in db.scalars(select(Child).where(Child.id.in_(all_ids), Child.class_id == cls.id))} \
        if all_ids else {}
    current = ledger.child_statuses(db, list(kids), now)
    evs = _classroom_evidence(db, list(kids), min((mastery._aware(s.done_at) for s in ss), default=now))
    out = [_session_outcome(db, s, kids, current, evs, content) for s in ss]
    return {"subject": subject, "sessions": out, "activities": _by_activity(out)}


def _session_outcome(db: Session, s: GroupSession, kids: dict[int, Child], current: dict, evs: list[Evidence],
                     content: Content) -> dict:
    members = [m for m in s.member_ids if m in kids]
    before = ledger.child_statuses(db, members, now=s.done_at, before=s.done_at)
    children = []
    for cid in members:
        b = before.get(cid, {}).get(s.checkpoint_id)
        b = b.status if b else "not_started"
        a = None
        if _rechecked(evs, cid, s.checkpoint_id, s.done_at):
            now_st = current.get(cid, {}).get(s.checkpoint_id)
            a = now_st.status if now_st else "not_started"
        children.append({"child_id": cid, "first_name": kids[cid].first_name, "before": b, "after": a,
                         "change": _change(b, a)})
    count = {k: sum(1 for c in children if c["change"] == k) for k in ("up", "same", "down", "not_rechecked")}
    return {"session_id": s.id, "plan_id": s.plan_id, "group_key": s.group_key, "checkpoint_id": s.checkpoint_id,
            **_titles(content, s.checkpoint_id), "activity_id": s.activity_id,
            "activity_title_hi": _act_title(content, s.activity_id),
            "done_on": _day(mastery._aware(s.done_at)).isoformat(), "members": len(children),
            "moved_up": count["up"], "same": count["same"], "moved_down": count["down"],
            "not_rechecked": count["not_rechecked"], "children": children}


def _by_activity(out: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for s in out:
        if not s["activity_id"]:
            continue
        a = agg.setdefault(s["activity_id"], {"activity_id": s["activity_id"], "title_hi": s["activity_title_hi"],
                                              "sessions": 0, "children": 0, "rechecked": 0, "moved_up": 0})
        a["sessions"] += 1
        a["children"] += s["members"]
        a["rechecked"] += s["members"] - s["not_rechecked"]
        a["moved_up"] += s["moved_up"]
    return sorted(agg.values(), key=lambda a: (-(a["moved_up"] / a["rechecked"] if a["rechecked"] else 0),
                                               -a["rechecked"], a["activity_id"]))
