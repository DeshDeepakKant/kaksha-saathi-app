"""Database tables. Every child-related row is reachable from a School (tenant)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class School(Base):
    __tablename__ = "schools"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(20))
    pin_hash: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(8), default="hi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Classroom(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("school_id", "grade", "section"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    grade: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(8), default="A")
    label: Mapped[str] = mapped_column(String(40))

    @property
    def name(self) -> str:
        return self.label


class Child(Base):
    __tablename__ = "children"
    __table_args__ = (UniqueConstraint("class_id", "roll_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    roll_no: Mapped[int] = mapped_column(Integer)
    first_name: Mapped[str] = mapped_column(String(60))
    consent_on: Mapped[date | None] = mapped_column(Date)
    consent_source: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Roadmap(Base):
    """An immutable, confirmed roadmap for a class + subject."""
    __tablename__ = "roadmaps"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    subject: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(16), default="template")  # template|photo|import
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    items: Mapped[list["RoadmapItem"]] = relationship(
        order_by="RoadmapItem.position", cascade="all, delete-orphan", lazy="selectin"
    )


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id"))
    position: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str] = mapped_column(String(120))
    checkpoint_id: Mapped[str] = mapped_column(String(80), index=True)
    custom_title: Mapped[str | None] = mapped_column(String(200))


class CaptureSession(Base):
    __tablename__ = "capture_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    kind: Mapped[str] = mapped_column(String(24))  # note|photo|voice|tap|probe|home
    input_ref: Mapped[str | None] = mapped_column(String(300))
    input_text: Mapped[str | None] = mapped_column(Text)  # transcript (audio itself is never stored)
    ai_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ready|fallback|failed
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|confirmed|discarded
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_child_cp_at", "child_id", "checkpoint_id", "at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    checkpoint_id: Mapped[str] = mapped_column(String(80), index=True)
    result: Mapped[str] = mapped_column(String(16))  # correct|partial|incorrect|unattempted
    score: Mapped[float | None] = mapped_column(Float)
    misconception: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("capture_sessions.id"))
    quote: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="confirmed")  # proposed|confirmed|rejected
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("child_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    day: Mapped[date] = mapped_column(Date)
    present: Mapped[bool] = mapped_column(Boolean)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    subject: Mapped[str] = mapped_column(String(16))
    for_date: Mapped[date] = mapped_column(Date)
    generated_by: Mapped[str] = mapped_column(String(16))  # ai|fallback
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("class_id", "subject", "for_date"),)


class InterventionLog(Base):
    __tablename__ = "intervention_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    group_key: Mapped[str] = mapped_column(String(80))
    done_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reassessed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ParentAccount(Base):
    __tablename__ = "parent_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    phone_hash: Mapped[str] = mapped_column(String(200))
    pin_hash: Mapped[str] = mapped_column(String(200))
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    language: Mapped[str] = mapped_column(String(8), default="hi")
    __table_args__ = (UniqueConstraint("child_id"),)


class HomeSession(Base):
    __tablename__ = "home_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    offline: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_hi: Mapped[str | None] = mapped_column(Text)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)


class AiCall(Base):
    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    feature: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_inr: Mapped[float] = mapped_column(Float, default=0)
    validation_status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsageCounter(Base):
    """Per-school daily AI budget counter (INR)."""
    __tablename__ = "usage_counters"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    day: Mapped[date] = mapped_column(Date)
    cost_inr: Mapped[float] = mapped_column(Float, default=0.0)
    __table_args__ = (UniqueConstraint("school_id", "day"),)


class CustomSubject(Base):
    """A subject a school added itself (the built-ins `numeracy` and `literacy` are not stored)."""
    __tablename__ = "custom_subjects"
    __table_args__ = (UniqueConstraint("school_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    key: Mapped[str] = mapped_column(String(16))
    name_en: Mapped[str] = mapped_column(String(60))
    name_hi: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CustomCheckpoint(Base):
    """A topic a teacher typed in. Registered into the in-memory content as a real checkpoint."""
    __tablename__ = "custom_checkpoints"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # "C<school>-<n>"
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    subject: Mapped[str] = mapped_column(String(16))
    grade: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str] = mapped_column(String(120))
    title_en: Mapped[str] = mapped_column(String(120))
    title_hi: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VoiceSession(Base):
    """A 30-minute voice learning session (see docs/voice_session_contract.md).

    `state` is the engine's whole working memory (ladder stage, item queues, current item, try,
    streaks, weak sounds, timer), so a turn survives a restart. `report` is written once, at the end.
    """
    __tablename__ = "voice_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    lang: Mapped[str] = mapped_column(String(4), default="hi")
    status: Mapped[str] = mapped_column(String(12), default="active")  # active|ended
    stage: Mapped[str] = mapped_column(String(20), default="letter")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_reason: Mapped[str | None] = mapped_column(String(16))  # time_up|parent_stop|abandoned
    elapsed_s: Mapped[float] = mapped_column(Float, default=0.0)
    safety_flag: Mapped[str | None] = mapped_column(String(16))  # last distress/personal flag, if any
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict | None] = mapped_column(JSON)


class VoiceTurn(Base):
    """One transcript line of a voice session (Saathi or the child).

    The child's row of each turn also keeps the turn's full response under its `client_turn_id`,
    so a retried upload returns the stored answer instead of judging twice. Rows with empty text
    (silence, skips, safety-redacted speech) are kept for that purpose but not shown in transcripts.
    """
    __tablename__ = "voice_turns"
    __table_args__ = (UniqueConstraint("session_id", "client_turn_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("voice_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(8))  # tutor|child
    text: Mapped[str] = mapped_column(Text, default="")
    item_id: Mapped[str | None] = mapped_column(String(80))
    verdict: Mapped[str | None] = mapped_column(String(12))  # correct|close|wrong|silent|skipped|flagged
    words: Mapped[list | None] = mapped_column(JSON)
    client_turn_id: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LevelCheck(Base):
    """One first-week / end-of-term level check of a child on a subject's ladder (content/level_check.json).

    `level_index` is the highest level passed (-1 = beginner). The per-level results are stored as
    `guided_probe` evidence; this row only keeps the placement so first vs latest can be compared.
    """
    __tablename__ = "level_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    subject: Mapped[str] = mapped_column(String(16))
    level_index: Mapped[int] = mapped_column(Integer)
    level_key: Mapped[str] = mapped_column(String(24))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))


class GroupSession(Base):
    """Snapshot of one group being taught (written when the teacher taps Done on a plan group).

    Deleting a plan or class removes its sessions (the existing class/plan delete paths stay valid).
    """
    __tablename__ = "group_sessions"
    __table_args__ = (UniqueConstraint("plan_id", "group_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(16))
    group_key: Mapped[str] = mapped_column(String(80))
    checkpoint_id: Mapped[str] = mapped_column(String(80))
    activity_id: Mapped[str | None] = mapped_column(String(80))
    member_ids: Mapped[list] = mapped_column(JSON, default=list)  # child ids, frozen at done time
    done_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))


class AppMeta(Base):
    """Small key/value facts about the deployment itself (e.g. which demo seed version is loaded)."""
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class TextbookMap(Base):
    """A teacher-approved textbook → chapters → topics mapping, saved with a syllabus (source "book").

    Append-only: the latest row for a class + subject is the current book. `mapping` holds the chapters
    as reviewed ({"chapters": [{title, inferred, basis, topics: [{text, checkpoint_id}]}]}).
    """
    __tablename__ = "textbook_maps"
    __table_args__ = (Index("ix_textbook_maps_class_subject", "class_id", "subject"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    subject: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(120))
    grade: Mapped[int | None] = mapped_column(Integer)
    board: Mapped[str] = mapped_column(String(60), default="")
    publisher: Mapped[str] = mapped_column(String(60), default="")
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("teachers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserPrefs(Base):
    """One teacher's or parent's language and voice choices (docs/lang_provider_contract.md section 3).

    `kind` + `user_id` point at teachers.id or parent_accounts.id; no row means the defaults
    (Sarvam, English app, Hindi content), which is exactly how the apps behaved before prefs existed.
    """
    __tablename__ = "user_prefs"
    __table_args__ = (UniqueConstraint("kind", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # teacher | parent
    user_id: Mapped[int] = mapped_column(Integer)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    voice_provider: Mapped[str] = mapped_column(String(12), default="gnani")
    app_lang: Mapped[str] = mapped_column(String(8), default="en")
    content_lang: Mapped[str] = mapped_column(String(8), default="hi")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TranslationCache(Base):
    """Machine translations already paid for, keyed by (source lang, target lang, sha256 of source)."""
    __tablename__ = "translation_cache"
    __table_args__ = (UniqueConstraint("src_lang", "tgt_lang", "src_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    src_lang: Mapped[str] = mapped_column(String(8))
    tgt_lang: Mapped[str] = mapped_column(String(8))
    src_hash: Mapped[str] = mapped_column(String(64))
    src: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HomeFocus(Base):
    """A teacher's override of what a child's home voice sessions practise (docs/voice_focus_contract.md §3).

    One subject per row (literacy | english). Setting a new focus deactivates the old row instead of
    deleting it, so the history of what the teacher asked for stays; a row counts until `until`.
    """
    __tablename__ = "home_focus"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), index=True)
    subject: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str] = mapped_column(String(20))
    checkpoint_ids: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    until: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
