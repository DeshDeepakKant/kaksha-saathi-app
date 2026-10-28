"""Parent insights (school → home): this week at school, learning journey, tips, moments, weekly.

Everything is deterministic: statuses come from the mastery engine, texts are fixed bilingual
templates plus reviewed content (see docs/parent_insights_contract.md). Rules kept here:
- only the parent's own child; never group labels, classmates, scores or ranks;
- "learned" comes from school evidence only (home evidence never makes anything learned);
- every function returns sensible empty values for a brand-new child.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tables import (Attendance, Child, Classroom, Evidence, HomeSession, Plan,
                               VoiceSession)
from app.services import ledger, mastery, tips
from app.services.content import Content, get_content

CELEBRATE_DAYS = 14
BETTER_DAYS = 7
TIP_DAYS = 30
CATCH_UP_DAYS = 3
TOPIC_DAYS = 7
GROWTH_WEEKS = 6
MAX_TIPS = 3

WORKING = ("needs_intervention", "needs_practice")


# ------------------------------------------------------------------ time helpers
def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ist_day(dt: datetime) -> date:
    return _utc(dt).astimezone(ledger.IST).date()


def _ist_midnight_utc(day: date) -> datetime:
    """Start of an IST day as an aware UTC datetime."""
    return datetime.combine(day, time.min, tzinfo=ledger.IST).astimezone(timezone.utc)


# ------------------------------------------------------------------ the child's context
@dataclass
class Kid:
    db: Session
    child: Child
    cls: Classroom
    now: datetime
    content: Content
    school_evs: dict[str, list[mastery.Ev]]  # school-confirmed evidence only, per checkpoint
    school_st: dict[str, str]  # statuses from school evidence only (drives "learned")
    all_st: dict[str, str]  # statuses from all evidence (home ceiling applied)

    @property
    def name(self) -> str:
        return self.child.first_name


def load_kid(db: Session, child_id: int, now: datetime | None = None) -> Kid:
    now = _utc(now or datetime.now(timezone.utc))
    child = db.get(Child, child_id)
    cls = db.get(Classroom, child.class_id)
    school_evs: dict[str, list[mastery.Ev]] = {}
    for e in db.scalars(select(Evidence).where(Evidence.child_id == child.id, Evidence.status == "confirmed",
                                               Evidence.source.not_in(tuple(mastery.HOME_SOURCES)))):
        school_evs.setdefault(e.checkpoint_id, []).append(
            mastery.Ev(result=e.result, source=e.source, confidence=e.confidence, at=e.at, id=e.id,
                       misconception=e.misconception))
    school_st = {cp: mastery.status_for(evs, now).status for cp, evs in school_evs.items()}
    all_st = {cp: r.status for cp, r in ledger.child_statuses(db, [child.id], now=now)[child.id].items()}
    return Kid(db, child, cls, now, get_content(), school_evs, school_st, all_st)


def _visible(kid: Kid, cp_id: str) -> bool:
    """A checkpoint the parent may see: reviewed content, or a custom topic of the child's own school."""
    if cp_id not in kid.content.checkpoints:
        return False
    return cp_id not in kid.content.custom_ids or cp_id.startswith(f"C{kid.cls.school_id}-")


def _titles(kid: Kid, cp_id: str, fallback: str | None = None) -> tuple[str, str]:
    cp = kid.content.checkpoints.get(cp_id) if _visible(kid, cp_id) else None
    if cp:
        return cp.title_hi, cp.title_en
    return fallback or "", fallback or ""


def _state(kid: Kid, cp_id: str) -> str:
    """learned (school evidence only) / working / not_started."""
    if kid.school_st.get(cp_id) == "on_track":
        return "learned"
    if kid.all_st.get(cp_id) in WORKING or kid.all_st.get(cp_id) == "on_track":
        return "working"  # on_track from mixed school+home evidence still counts as "working" here
    return "not_started"


def _status_at(evs: list[mastery.Ev], at: datetime) -> str:
    seen = [e for e in evs if _utc(e.at) < at]
    return mastery.status_for(seen, at).status if seen else "not_started"


def _moved_at(evs: list[mastery.Ev], since: datetime, target: str) -> datetime | None:
    """When the status last moved into `target` after `since` (None if it hasn't)."""
    moved = None
    prev = _status_at(evs, since)
    for e in sorted((e for e in evs if _utc(e.at) >= since), key=lambda e: (_utc(e.at), e.id)):
        cur = mastery.status_for([x for x in evs if _utc(x.at) <= _utc(e.at)], e.at).status
        if cur == target and prev != target:
            moved = _utc(e.at)
        prev = cur
    return moved


# ------------------------------------------------------------------ plans and class topic
def _plan_group_cp(g: dict) -> str:
    return g.get("checkpoint_id") or g.get("key") or ""


def _is_member(g: dict, child: Child) -> bool:
    for m in g.get("members") or []:
        if isinstance(m, dict) and m.get("id") == child.id:
            return True
        if isinstance(m, int) and m == child.roll_no:
            return True
    return False


def _recent_plans(kid: Kid, days: int = TOPIC_DAYS) -> list[Plan]:
    today = ledger.school_today(kid.now)
    plans = list(kid.db.scalars(select(Plan).where(Plan.class_id == kid.cls.id,
                                                   Plan.for_date > today - timedelta(days=days),
                                                   Plan.for_date <= today)
                                .order_by(Plan.for_date.desc(), Plan.id.desc())))
    if not plans:  # no plan this week: the latest one the class had
        last = kid.db.scalar(select(Plan).where(Plan.class_id == kid.cls.id, Plan.for_date <= today)
                             .order_by(Plan.for_date.desc(), Plan.id.desc()).limit(1))
        plans = [last] if last else []
    return plans


def _chapter(kid: Kid, cp_id: str) -> str:
    sub = kid.content.checkpoints[cp_id].subject if cp_id in kid.content.checkpoints else None
    if sub:
        rm = ledger.current_roadmap(kid.db, kid.cls.id, sub)
        for it in (rm.items if rm else []):
            if it.checkpoint_id == cp_id:
                return it.chapter
    cp = kid.content.checkpoints.get(cp_id)
    return cp.chapter if cp else ""


def class_topic(kid: Kid) -> dict | None:
    since = (kid.now - timedelta(days=TOPIC_DAYS)).replace(tzinfo=None)
    rows = kid.db.execute(select(Evidence.checkpoint_id, Evidence.at).where(
        Evidence.class_id == kid.cls.id, Evidence.status == "confirmed",
        Evidence.source.not_in(tuple(mastery.HOME_SOURCES)), Evidence.at >= since)).all()
    counts = Counter(cp for cp, _ in rows if _visible(kid, cp))
    best: str | None = None
    top = counts.most_common()
    if top and (len(top) == 1 or top[0][1] > top[1][1]):
        best = top[0][0]
    if best is None:  # tie or no evidence: what the latest plans worked on
        plan_counts = Counter(cp for p in _recent_plans(kid) for g in (p.payload or {}).get("groups", [])
                              if _visible(kid, cp := _plan_group_cp(g)))
        tied = {cp for cp, n in top if n == top[0][1]} if top else set()
        ranked = [cp for cp, _ in plan_counts.most_common() if not tied or cp in tied]
        best = ranked[0] if ranked else (plan_counts.most_common(1)[0][0] if plan_counts else None)
    if best is None and top:  # a tie the plans can't break: the most recently taught of the tied ones
        tied = {cp for cp, n in top if n == top[0][1]}
        last = {cp: max(_utc(at) for c, at in rows if c == cp) for cp in tied}
        best = max(sorted(tied), key=lambda cp: last[cp])
    if best is None:
        return None
    cp = kid.content.checkpoints[best]
    return {"checkpoint_id": best, "chapter": _chapter(kid, best), "title_hi": cp.title_hi,
            "title_en": cp.title_en, "subject": cp.subject}


def child_focus(kid: Kid) -> dict | None:
    cp_id = None
    plans = _recent_plans(kid)
    if plans:  # the child's own topic in the latest day's plans (shown as a topic, never as a group)
        latest_day = plans[0].for_date
        for p in plans:
            if p.for_date != latest_day:
                break
            g = next((g for g in (p.payload or {}).get("groups", [])
                      if _is_member(g, kid.child) and _visible(kid, _plan_group_cp(g))), None)
            if g:
                cp_id = _plan_group_cp(g)
                break
    if cp_id is None:
        gap = mastery.find_gap(kid.content, {cp: s for cp, s in kid.school_st.items() if _visible(kid, cp)})
        cp_id = gap.checkpoint_id if gap else None
    if cp_id is None:
        return None
    cp = kid.content.checkpoints[cp_id]
    state = _state(kid, cp_id)
    return {"checkpoint_id": cp_id, "title_hi": cp.title_hi, "title_en": cp.title_en, "subject": cp.subject,
            "state": "next" if state == "not_started" else state}


# ------------------------------------------------------------------ 1. this week at school
def school_week(db: Session, child_id: int, now: datetime | None = None) -> dict:
    kid = load_kid(db, child_id, now)
    topic, focus = class_topic(kid), child_focus(kid)
    n = kid.name
    if topic and focus and topic["checkpoint_id"] == focus["checkpoint_id"]:
        hi = f"इस हफ़्ते कक्षा में “{topic['title_hi']}” पढ़ाया जा रहा है। {n} का अभ्यास भी इसी पर चल रहा है।"
        en = f"This week the class is learning “{topic['title_en']}”. {n} is practising this too."
    elif topic and focus:
        hi = (f"इस हफ़्ते कक्षा में “{topic['title_hi']}” पढ़ाया जा रहा है। "
              f"{n} का अभ्यास “{focus['title_hi']}” पर चल रहा है।")
        en = f"This week the class is learning “{topic['title_en']}”. {n} is practising “{focus['title_en']}”."
    elif topic:
        hi = f"इस हफ़्ते कक्षा में “{topic['title_hi']}” पढ़ाया जा रहा है। घर पर {n} से इसके बारे में बात करें।"
        en = f"This week the class is learning “{topic['title_en']}”. Talk with {n} about it at home."
    elif focus:
        hi = f"इस हफ़्ते {n} का अभ्यास “{focus['title_hi']}” पर चल रहा है।"
        en = f"This week {n} is practising “{focus['title_en']}”."
    else:
        hi = f"इस हफ़्ते की जानकारी जल्द आएगी। तब तक {n} के साथ रोज़ थोड़ा पढ़ें।"
        en = f"This week's update is coming soon. Until then, read a little with {n} every day."
    return {"class_topic": topic, "child_focus": focus, "line_hi": hi, "line_en": en,
            "as_of": ledger.school_today(kid.now).isoformat()}


# ------------------------------------------------------------------ 2. learning journey
def _milestone_rows(kid: Kid, subject: str) -> list[tuple[str, str, str | None]]:
    """(checkpoint_id, chapter, custom_title) in roadmap order; template when no roadmap."""
    rm = ledger.current_roadmap(kid.db, kid.cls.id, subject)
    if rm:
        rows = [(i.checkpoint_id, i.chapter, i.custom_title) for i in rm.items]
    else:
        rows = [(i["checkpoint_id"], i["chapter"], None) for i in kid.content.template_roadmap(subject, kid.cls.grade)]
    seen, out = set(), []
    for cp, chapter, custom in rows:
        if cp in seen or (cp in kid.content.checkpoints and not _visible(kid, cp)):
            continue
        if cp not in kid.content.checkpoints and not custom:
            continue
        seen.add(cp)
        out.append((cp, chapter, custom))
    return out


def _celebration(kid: Kid, cp_id: str, at: datetime) -> dict:
    hi, en = _titles(kid, cp_id)
    return {"checkpoint_id": cp_id, "title_hi": hi, "title_en": en, "at": at.isoformat(),
            "line_hi": f"⭐ {kid.name} ने अब “{hi}” सीख लिया है!",
            "line_en": f"⭐ {kid.name} has now learned “{en}”!"}


def celebrations(kid: Kid, cps: set[str] | None = None) -> list[dict]:
    """Checkpoints that became learned (on track from school evidence) within the last 14 days."""
    since = kid.now - timedelta(days=CELEBRATE_DAYS)
    out = []
    for cp, evs in kid.school_evs.items():
        if (cps is not None and cp not in cps) or not _visible(kid, cp) or kid.school_st.get(cp) != "on_track":
            continue
        if _status_at(evs, since) == "on_track":
            continue  # already learned before the window
        at = _moved_at(evs, since, "on_track") or max(_utc(e.at) for e in evs)
        out.append(_celebration(kid, cp, at))
    return sorted(out, key=lambda c: (c["at"], c["checkpoint_id"]), reverse=True)


def _growth(kid: Kid, cps: list[str]) -> list[dict]:
    today = ledger.school_today(kid.now)
    points = []
    for back in range(GROWTH_WEEKS - 1, -1, -1):
        day = today - timedelta(days=7 * back)
        at = kid.now if back == 0 else _ist_midnight_utc(day + timedelta(days=1))
        n = sum(1 for cp in cps if cp in kid.school_evs and _status_at(kid.school_evs[cp], at) == "on_track")
        points.append({"week_end": day.isoformat(), "learned": n})
    return points


def _journey(kid: Kid, subject: str) -> dict:
    rows = _milestone_rows(kid, subject)
    states = [_state(kid, cp) for cp, _, _ in rows]
    active = [i for i, s in enumerate(states) if s != "not_started"]
    after = active[-1] + 1 if active else 0
    nxt = [i for i in range(after, len(rows)) if states[i] == "not_started"][:2]
    if not nxt:  # the roadmap's last topic is already in progress: the earliest ones not started yet
        nxt = [i for i, s in enumerate(states) if s == "not_started"][:2]
    milestones = []
    for i, (cp, chapter, custom) in enumerate(rows):
        hi, en = _titles(kid, cp, custom)
        state = states[i] if states[i] != "not_started" else ("next" if i in nxt else "later")
        milestones.append({"checkpoint_id": cp, "chapter": chapter, "title_hi": hi, "title_en": en,
                           "nipun_ref": ledger.nipun_ref(kid.content, cp), "state": state})
    cps = [cp for cp, _, _ in rows]
    return {"subject": subject, "grade": kid.cls.grade, "milestones": milestones,
            "counts": {"learned": states.count("learned"), "working": states.count("working"), "total": len(rows)},
            "celebrations": celebrations(kid, set(cps)), "growth": _growth(kid, cps)}


def journey(db: Session, child_id: int, subject: str = "numeracy", now: datetime | None = None) -> dict:
    return _journey(load_kid(db, child_id, now), subject)


# ------------------------------------------------------------------ 3. tips for specific mistakes
def _tips(kid: Kid) -> list[dict]:
    since = kid.now - timedelta(days=TIP_DAYS)
    rows = sorted(((e, cp) for cp, evs in kid.school_evs.items() for e in evs
                   if e.misconception and _utc(e.at) >= since),
                  key=lambda x: (_utc(x[0].at), x[0].id), reverse=True)
    out, seen = [], set()
    for e, cp in rows:
        if e.misconception in seen or kid.school_st.get(cp) == "on_track" or not _visible(kid, cp):
            continue
        seen.add(e.misconception)
        tip = tips.get_tip(e.misconception)
        if not tip:  # no reviewed text for this mistake yet: show nothing rather than something unreviewed
            continue
        hi, en = _titles(kid, cp)
        out.append({"misconception": e.misconception, "checkpoint_id": cp, "title_hi": hi, "title_en": en,
                    "explain_hi": tip.get("explain_hi", ""), "explain_en": tip.get("explain_en", ""),
                    "game_hi": tip.get("game_hi", ""), "game_en": tip.get("game_en", ""),
                    "example": tip.get("example", ""), "seen_at": _utc(e.at).isoformat()})
        if len(out) >= MAX_TIPS:
            break
    return out


def tips_for(db: Session, child_id: int, now: datetime | None = None) -> dict:
    return {"tips": _tips(load_kid(db, child_id, now))}


# ------------------------------------------------------------------ 4. teacher noticed moments
def _getting_better(kid: Kid) -> list[dict]:
    since = kid.now - timedelta(days=BETTER_DAYS)
    out = []
    for cp, evs in kid.school_evs.items():
        if not _visible(kid, cp) or kid.school_st.get(cp) != "needs_practice":
            continue
        if _status_at(evs, since) != "needs_intervention":
            continue
        at = _moved_at(evs, since, "needs_practice") or max(_utc(e.at) for e in evs)
        hi, en = _titles(kid, cp)
        out.append({"kind": "celebration", "move": "getting_better", "checkpoint_id": cp, "title_hi": hi,
                    "title_en": en, "at": at.isoformat(),
                    "line_hi": f"🌱 “{hi}” में {kid.name} की पकड़ बढ़ रही है।",
                    "line_en": f"🌱 {kid.name} is getting better at “{en}”."})
    return out


def _day_words(day: date, today: date) -> tuple[str, str]:
    if day == today:
        return "आज", "today"
    if day == today - timedelta(days=1):
        return "कल", "yesterday"
    return day.strftime("%d/%m"), f"on {day.strftime('%d %b')}"


def _home_activity(activity_id: str | None) -> dict | None:
    h = tips.home_version(activity_id) if activity_id else None
    if not h:
        return None
    return {"id": h.get("id", activity_id), "title_hi": h.get("title_hi", ""), "title_en": h.get("title_en", ""),
            "materials_hi": h.get("materials_hi", ""), "materials_en": h.get("materials_en", ""),
            "steps_hi": list(h.get("steps_hi") or [])[:3], "steps_en": list(h.get("steps_en") or [])[:3],
            "minutes": h.get("minutes", 5)}


def _catch_ups(kid: Kid) -> list[dict]:
    today = ledger.school_today(kid.now)
    days = sorted((a.day for a in kid.db.scalars(select(Attendance).where(
        Attendance.child_id == kid.child.id, Attendance.present.is_(False),
        Attendance.day > today - timedelta(days=CATCH_UP_DAYS), Attendance.day <= today))), reverse=True)
    out = []
    topic = class_topic(kid) if days else None
    for day in days:
        cp_id, activity_id = None, None
        for p in kid.db.scalars(select(Plan).where(Plan.class_id == kid.cls.id, Plan.for_date == day)
                                .order_by(Plan.id)):
            groups = [g for g in (p.payload or {}).get("groups", []) if _visible(kid, _plan_group_cp(g))]
            g = next((g for g in groups if _is_member(g, kid.child)), groups[0] if groups else None)
            if g:
                cp_id = _plan_group_cp(g)
                activity_id = g.get("activity_id") or (g.get("activity") or {}).get("id")
                break
        if cp_id is None and topic:
            cp_id = topic["checkpoint_id"]
        if cp_id is None:
            continue
        if not activity_id or activity_id not in kid.content.activities:
            acts = kid.content.activities_for({cp_id})
            activity_id = acts[0]["id"] if acts else activity_id
        hi, en = _titles(kid, cp_id)
        dw_hi, dw_en = _day_words(day, today)
        activity = _home_activity(activity_id)
        line_hi = f"{dw_hi} {kid.name} की कक्षा छूट गई। कोई बात नहीं!"
        line_en = f"{kid.name} missed class {dw_en}. No problem!"
        if activity:
            line_hi += f" घर पर {activity['minutes']} मिनट में ऐसे करें:"
            line_en += f" Here is a {activity['minutes']}-minute way to catch up at home:"
        else:
            line_hi += f" घर पर 5 मिनट “{hi}” के बारे में साथ बैठकर बात करें।"
            line_en += f" Spend 5 minutes at home talking together about “{en}”."
        out.append({"kind": "catch_up", "day": day.isoformat(),
                    "class_did_hi": f"{dw_hi} कक्षा में “{hi}” पर काम हुआ।",
                    "class_did_en": f"The class worked on “{en}” {dw_en}.",
                    "activity": activity, "line_hi": line_hi, "line_en": line_en})
    return out


def moments(db: Session, child_id: int, now: datetime | None = None) -> dict:
    kid = load_kid(db, child_id, now)
    cel = [{"kind": "celebration", "move": "learned", **c} for c in celebrations(kid)] + _getting_better(kid)
    cel.sort(key=lambda c: (c["at"], c["checkpoint_id"]), reverse=True)
    return {"moments": _catch_ups(kid) + cel}


# ------------------------------------------------------------------ 5. weekly summary
def _voice_minutes(vs: VoiceSession) -> float:
    rep = vs.report if isinstance(vs.report, dict) else {}
    if isinstance(rep.get("minutes"), (int, float)):
        return float(rep["minutes"])
    st = vs.state if isinstance(vs.state, dict) else {}
    secs = st.get("elapsed_s") if isinstance(st.get("elapsed_s"), (int, float)) else vs.elapsed_s
    return float(secs or 0) / 60.0


def weekly(db: Session, child_id: int, now: datetime | None = None) -> dict:
    kid = load_kid(db, child_id, now)
    today = ledger.school_today(kid.now)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    start_utc = _ist_midnight_utc(week_start)
    end_utc = _ist_midnight_utc(week_end + timedelta(days=1))
    lo, hi_ = start_utc.replace(tzinfo=None), end_utc.replace(tzinfo=None)

    voice = list(db.scalars(select(VoiceSession).where(VoiceSession.child_id == kid.child.id,
                                                       VoiceSession.started_at >= lo, VoiceSession.started_at < hi_)))
    home = list(db.scalars(select(HomeSession).where(HomeSession.child_id == kid.child.id,
                                                     HomeSession.started_at >= lo, HomeSession.started_at < hi_)))
    practice_days = len({_ist_day(s.started_at) for s in voice} | {_ist_day(s.started_at) for s in home})
    voice_minutes = int(round(sum(_voice_minutes(v) for v in voice)))

    # learned this week: on track from school evidence now, not on track when the week began
    learned_cps = [cp for cp, evs in kid.school_evs.items()
                   if _visible(kid, cp) and kid.school_st.get(cp) == "on_track"
                   and _status_at(evs, start_utc) != "on_track"]
    # working on: still being practised and touched this week (school or home), else the current focus
    week_evs = {cp for (cp,) in db.execute(select(Evidence.checkpoint_id).where(
        Evidence.child_id == kid.child.id, Evidence.status == "confirmed",
        Evidence.at >= lo, Evidence.at < hi_)).all()}
    working_cps = sorted((cp for cp in week_evs if _visible(kid, cp) and _state(kid, cp) == "working"),
                         key=lambda cp: (kid.content.checkpoints[cp].grade, cp))
    focus = child_focus(kid)
    if not working_cps and focus and focus["state"] == "working":
        working_cps = [focus["checkpoint_id"]]
    subject = (kid.content.checkpoints[working_cps[0]].subject if working_cps
               else focus["subject"] if focus else "numeracy")
    nxt = [m for m in _journey(kid, subject)["milestones"] if m["state"] == "next"]

    def t(cp: str) -> dict:
        h, e = _titles(kid, cp)
        return {"title_hi": h, "title_en": e}

    learned = [t(cp) for cp in sorted(learned_cps)][:3]
    tip_list = _tips(kid)
    n = kid.name
    if practice_days:
        line_hi = f"इस हफ़्ते {n} ने {practice_days} दिन घर पर अभ्यास किया।"
        line_en = f"This week {n} practised at home on {practice_days} day{'s' if practice_days != 1 else ''}."
    else:
        line_hi = f"इस हफ़्ते घर पर अभ्यास अभी शुरू नहीं हुआ। आज {n} के साथ 5 मिनट बैठें।"
        line_en = f"No home practice yet this week. Sit with {n} for 5 minutes today."
    if learned:
        line_hi += f" ⭐ नया सीखा: “{learned[0]['title_hi']}”। शाबाश!"
        line_en += f" ⭐ Newly learned: “{learned[0]['title_en']}”. Well done!"
    return {"week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
            "practice_days": practice_days, "voice_sessions": len(voice), "voice_minutes": voice_minutes,
            "learned": learned, "working_on": [t(cp) for cp in working_cps][:3],
            "next": [{"title_hi": m["title_hi"], "title_en": m["title_en"]} for m in nxt][:2],
            "tip": tip_list[0] if tip_list else None, "line_hi": line_hi, "line_en": line_en}
