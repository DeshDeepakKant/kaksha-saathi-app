"""Which stage a child's voice session practises (docs/voice_focus_contract.md section 1).

Code decides, from the teacher's evidence, first match wins: the teacher's override (`HomeFocus`), the
latest level check (at most 45 days old), the child's group on the class board, the lowest stage that is
not secure, else a short placement probe. The last ended session's outcome takes over when it is newer
than that evidence (tracking across sessions), but never over a teacher override.

Pure reads: `plan_session` writes nothing, so the parent and teacher apps can preview the next session.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tables import Child, Classroom, Evidence, HomeFocus, LevelCheck, ParentAccount, VoiceSession
from app.services import ledger
from app.services.content import get_content
from app.services.voice_report import STAGE_NAMES
from app.services.voice_types import STAGES, stage_checkpoints

SECURE = "on_track"
SUBJECTS = ("literacy", "english")
LEVEL_CHECK_MAX_DAYS = 45
PLACEMENT_STAGE = "word_read"
MAX_FOCUS_CPS = 4
MAX_TARGET_SOUNDS = 8
HISTORY_ROWS = 8
# `level_key` is the highest level PASSED, so the focus is the next step.
LEVEL_FOCUS = {"beginner": "letter", "letter": "word_build", "word": "sentence_build", "sentence": "reading",
               "story": "reading"}
_LEVEL_SAYS = {  # what the level check showed, in a few words
    "beginner": ("not yet reading letters", "अक्षर पढ़ना अभी नहीं आता"),
    "letter": ("reads letters, not yet words", "अक्षर पढ़ना आता है, शब्द अभी नहीं"),
    "word": ("reads words, not yet sentences", "शब्द पढ़ना आता है, वाक्य अभी नहीं"),
    "sentence": ("reads sentences, not yet a story", "वाक्य पढ़ना आता है, कहानी अभी नहीं"),
    "story": ("reads a short story; now longer reading and questions",
              "छोटी कहानी पढ़ना आता है; अब लंबा पाठ और सवाल"),
}
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTHS_HI = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर",
              "नवंबर", "दिसंबर")


# ------------------------------------------------------------------ small helpers
def subject_for(lang: str | None) -> str:
    return "english" if lang == "en" else "literacy"


def label(stage: str | None, lang: str = "en") -> str:
    en, hi = STAGE_NAMES.get(stage or "", (stage or "", stage or ""))
    return hi if lang == "hi" else en


def below(stage: str | None) -> str | None:
    i = STAGES.index(stage) if stage in STAGES else -1
    return STAGES[i - 1] if i > 0 else None


def above(stage: str | None) -> str | None:
    i = STAGES.index(stage) if stage in STAGES else len(STAGES)
    return STAGES[i + 1] if i + 1 < len(STAGES) else None


def _naive(t: datetime | None) -> datetime | None:
    if t is None:
        return None
    return t.astimezone(timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def _day(t: datetime | date) -> date:
    if isinstance(t, datetime):
        return ledger.school_today(t if t.tzinfo else t.replace(tzinfo=timezone.utc))
    return t


def day_en(t: datetime | date) -> str:
    d = _day(t)
    return f"{d.day} {_MONTHS_EN[d.month - 1]}"


def day_hi(t: datetime | date) -> str:
    d = _day(t)
    return f"{d.day} {_MONTHS_HI[d.month - 1]}"


def stage_of(lang: str, cp: str | None) -> str | None:
    """The lowest ladder stage that practises a checkpoint (None when no stage does)."""
    return next((s for s in STAGES if cp and cp in stage_checkpoints(lang, s)), None)


def _statuses(db: Session, child: Child) -> dict[str, str]:
    return {cp: r.status for cp, r in ledger.child_statuses(db, [child.id]).get(child.id, {}).items()}


def _latest_evidence_at(db: Session, child_id: int, cps) -> datetime | None:
    cps = list(cps)
    if not cps:
        return None
    return db.scalar(select(func.max(Evidence.at)).where(
        Evidence.child_id == child_id, Evidence.status == "confirmed", Evidence.checkpoint_id.in_(cps)))


# ------------------------------------------------------------------ the evidence
def active_override(db: Session, child_id: int, subject: str, today: date | None = None) -> HomeFocus | None:
    today = today or ledger.school_today()
    return db.scalar(select(HomeFocus).where(
        HomeFocus.child_id == child_id, HomeFocus.subject == subject, HomeFocus.active.is_(True),
        HomeFocus.until >= today).order_by(HomeFocus.created_at.desc(), HomeFocus.id.desc()).limit(1))


def override_view(row: HomeFocus | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "stage": row.stage, "checkpoint_ids": list(row.checkpoint_ids or []),
            "note": row.note, "until": row.until.isoformat()}


def last_ended(db: Session, child_id: int, lang: str) -> VoiceSession | None:
    """The child's latest ended session in this language."""
    return db.scalar(select(VoiceSession).where(VoiceSession.child_id == child_id, VoiceSession.lang == lang,
                                                VoiceSession.status == "ended")
                     .order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc()).limit(1))


def _board_gap(db: Session, child: Child, subject: str, lang: str) -> tuple[str, str] | None:
    """(stage, checkpoint) of the child's group on the class board, when a ladder stage practises it."""
    cls = db.get(Classroom, child.class_id)
    if cls is None:
        return None
    grouping = ledger.build_groups(db, cls, subject)[0]
    cands = [g.checkpoint_id for g in grouping.groups if child.id in g.members]
    gap = grouping.gaps.get(child.id)
    if gap is not None:
        cands.append(gap.checkpoint_id)
    for cp in cands:
        stage = stage_of(lang, cp)
        if stage:
            return stage, cp
    return None


def _lowest_not_secure(lang: str, statuses: dict[str, str]) -> tuple[str | None, bool]:
    """(lowest stage not secure, any evidence on the ladder at all). The test is the old `start_stage`
    one: secure = at least half the stage's checkpoints assessed and every assessed one on track."""
    seen_any = False
    lowest = None
    for stage in STAGES:
        cps = stage_checkpoints(lang, stage)
        seen = [statuses[c] for c in cps if statuses.get(c, "not_started") != "not_started"]
        seen_any = seen_any or bool(seen)
        if lowest is None and (2 * len(seen) < len(cps) or any(s != SECURE for s in seen)):
            lowest = stage
    return lowest or STAGES[-1], seen_any


def focus_checkpoints(lang: str, syllabus: dict, stage: str, statuses: dict[str, str],
                      first: str | None = None) -> list[str]:
    """The stage's checkpoints in the class syllabus that are not secure, `first` (the board gap) first;
    else every syllabus checkpoint of the stage; else every checkpoint of the stage."""
    content = get_content()
    stage_cps = [c for c in stage_checkpoints(lang, stage) if c in content.checkpoints]
    syl = set(syllabus.get("english") if lang == "en" else syllabus.get("builtin") or [])
    in_syl = [c for c in stage_cps if c in syl]
    out = [c for c in in_syl if statuses.get(c) != SECURE]
    if first and first in stage_cps:
        out = [first] + [c for c in out if c != first]
    return (out or in_syl or stage_cps)[:MAX_FOCUS_CPS]


# ------------------------------------------------------------------ reasons
def _last_reason(vs: VoiceSession, outcome: dict) -> tuple[str, str]:
    when = vs.ended_at or vs.started_at
    en = outcome.get("next_reason_en") or f"next: {label(outcome.get('next_focus_stage'))}."
    hi = outcome.get("next_reason_hi") or f"अगला: {label(outcome.get('next_focus_stage'), 'hi')}।"
    return f"Last session on {day_en(when)}: {en[:1].lower()}{en[1:]}", f"{day_hi(when)} के सत्र से: {hi}"


def placement_reason(stage: str) -> tuple[str, str]:
    return (f"Saathi checked the level first: practise {label(stage).lower()}.",
            f"साथी ने पहले स्तर जाँचा: अब अभ्यास — {label(stage, 'hi')}।")


# ------------------------------------------------------------------ the plan
def plan_session(db: Session, child: Child, lang: str, syllabus: dict, *, now: datetime | None = None) -> dict:
    """The next session's plan for this child and language (contract section 1). Writes nothing."""
    now = now or datetime.now(timezone.utc)
    subject = subject_for(lang)
    statuses = _statuses(db, child)
    plan = {"v": 1, "subject": subject, "focus_stage": None, "warmup_stage": None, "stretch_stage": None,
            "start_difficulty": 1, "focus_checkpoints": [], "target_sounds": [], "source": None,
            "reason_en": "", "reason_hi": "", "placement": False, "override": None, "based_on_session": None}
    board_cp = None
    evidence_at: datetime | None = None
    override_cps: list[str] = []

    row = active_override(db, child.id, subject, _day(now))
    lc = db.scalar(select(LevelCheck).where(LevelCheck.child_id == child.id, LevelCheck.subject == subject)
                   .order_by(LevelCheck.at.desc(), LevelCheck.id.desc()).limit(1))
    if lc is not None and (_naive(lc.at) < _naive(now) - timedelta(days=LEVEL_CHECK_MAX_DAYS)
                           or lc.level_key not in LEVEL_FOCUS):
        lc = None
    if row is not None and row.stage in STAGES:
        plan.update(focus_stage=row.stage, source="teacher_override", override=override_view(row))
        override_cps = [c for c in row.checkpoint_ids or [] if c in get_content().checkpoints]
        until = row.until
        plan["reason_en"] = f"Set by the teacher until {day_en(until)}" + (f": {row.note}" if row.note else ".")
        plan["reason_hi"] = f"शिक्षक ने {day_hi(until)} तक तय किया" + (f": {row.note}" if row.note else "।")
    elif lc is not None:
        plan.update(focus_stage=LEVEL_FOCUS[lc.level_key], source="level_check")
        if lc.level_key == "story":
            plan["start_difficulty"] = 3
        evidence_at = _naive(lc.at)
        says_en, says_hi = _LEVEL_SAYS[lc.level_key]
        plan["reason_en"] = f"Level check on {day_en(lc.at)}: {says_en}."
        plan["reason_hi"] = f"{day_hi(lc.at)} की स्तर जाँच: {says_hi}।"
    else:
        gap = _board_gap(db, child, subject, lang)
        if gap is not None:
            stage, board_cp = gap
            cp = get_content().checkpoints.get(board_cp)
            plan.update(focus_stage=stage, source="board_gap")
            evidence_at = _naive(_latest_evidence_at(db, child.id, [board_cp]))
            plan["reason_en"] = f"Class board: working on {cp.title_en if cp else board_cp}."
            plan["reason_hi"] = f"कक्षा बोर्ड पर: {cp.title_hi if cp else board_cp} पर काम चल रहा है।"
        else:
            stage, seen_any = _lowest_not_secure(lang, statuses)
            if seen_any:
                ladder_cps = {c for s in STAGES for c in stage_checkpoints(lang, s)}
                plan.update(focus_stage=stage, source="mastery")
                evidence_at = _naive(_latest_evidence_at(db, child.id, ladder_cps))
                plan["reason_en"] = f"Class records: {label(stage).lower()} is the first step not yet secure."
                plan["reason_hi"] = f"कक्षा के रिकॉर्ड: {label(stage, 'hi')} अभी पक्का नहीं है।"
            else:
                plan.update(focus_stage=PLACEMENT_STAGE, source="placement", placement=True)
                plan["reason_en"] = "No level check or class records yet: Saathi will first find the right level."
                plan["reason_hi"] = "अभी कोई स्तर जाँच या कक्षा रिकॉर्ड नहीं: साथी पहले सही स्तर पता करेगा।"

    last = last_ended(db, child.id, lang)
    if last is not None and plan["source"] != "teacher_override":
        outcome = (last.report or {}).get("outcome") or {}
        nxt = outcome.get("next_focus_stage")
        ended = _naive(last.ended_at or last.started_at)
        if nxt in STAGES and (evidence_at is None or ended > evidence_at):
            plan.update(focus_stage=nxt, source="last_session", placement=False, based_on_session=last.id,
                        start_difficulty=1)
            board_cp = None
            plan["reason_en"], plan["reason_hi"] = _last_reason(last, outcome)
    if last is not None:
        weak = list(((last.state or {}).get("weak_sounds")) or [])
        plan["target_sounds"] = list(dict.fromkeys(reversed(weak)))[:MAX_TARGET_SOUNDS]

    focus = plan["focus_stage"]
    plan["warmup_stage"], plan["stretch_stage"] = below(focus), above(focus)
    plan["focus_checkpoints"] = (override_cps[:MAX_FOCUS_CPS] if override_cps
                                 else focus_checkpoints(lang, syllabus, focus, statuses, board_cp))
    return plan


def preview(db: Session, child: Child, lang: str) -> dict:
    """The plan for the child's next session in `lang` (parent "Today's practice", teacher home focus)."""
    from app.services import voice_session
    cls = db.get(Classroom, child.class_id)
    return plan_session(db, child, lang, voice_session._syllabus(db, cls, lang))


def preview_lang(db: Session, child: Child, subject: str) -> str:
    """English for the english subject; else the parent's content language (Hindi without a parent)."""
    if subject == "english":
        return "en"
    from app.services import prefs
    from app.services.voice_types import voice_lang
    parent = db.scalar(select(ParentAccount).where(ParentAccount.child_id == child.id)
                       .order_by(ParentAccount.id).limit(1))
    try:
        code = prefs.content_lang_for(db, parent=parent) if parent else "hi"
    except Exception:
        code = "hi"
    code = voice_lang(code)
    return "hi" if code == "en" else code


# ------------------------------------------------------------------ tracking (teacher view)
def history(db: Session, child_id: int, subject: str, limit: int = HISTORY_ROWS) -> list[dict]:
    """Ended sessions of the subject with an outcome, newest first."""
    q = select(VoiceSession).where(VoiceSession.child_id == child_id, VoiceSession.status == "ended")
    q = q.where(VoiceSession.lang == "en") if subject == "english" else q.where(VoiceSession.lang != "en")
    out = []
    for vs in db.scalars(q.order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc()).limit(4 * limit)):
        rep = vs.report or {}
        oc = rep.get("outcome")
        if not oc:
            continue
        out.append({"session_id": vs.id, "date": _day(vs.started_at).isoformat(), "lang": vs.lang,
                    "focus_stage": oc.get("focus_stage"), "focus_accuracy": oc.get("focus_accuracy"),
                    "mastered": bool(oc.get("mastered")), "next_focus_stage": oc.get("next_focus_stage"),
                    "plan_source": (rep.get("plan") or {}).get("source")})
        if len(out) >= limit:
            break
    return out


def home_focus_view(db: Session, child: Child, subject: str) -> dict:
    """GET /children/{id}/home_focus body."""
    return {"subject": subject, "plan": preview(db, child, preview_lang(db, child, subject)),
            "override": override_view(active_override(db, child.id, subject)),
            "history": history(db, child.id, subject)}
