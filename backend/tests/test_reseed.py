"""The DEMO reseed must be able to delete a school that has saved preferences (it failed on the live
Postgres database with a foreign-key error), and a new school-linked table must not be forgotten."""
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import seed as seed_mod
from app.db import Base
from app.models.tables import HomeFocus, ParentAccount, School, Teacher, UserPrefs, VoiceSession

# Every table with a foreign key to schools.id. When you add one, make seed()'s reset branch delete it
# (see the delete(...) calls in app/seed.py), then add its name here.
SCHOOL_LINKED = {
    "ai_calls", "attendance", "capture_sessions", "classes", "custom_checkpoints", "custom_subjects",
    "evidence", "group_sessions", "home_focus", "home_sessions", "intervention_logs", "level_checks", "parent_accounts",
    "plans", "roadmaps", "teachers", "textbook_maps", "usage_counters", "user_prefs", "voice_sessions",
}


def test_school_linked_tables_are_all_known():
    linked = {t.name for t in Base.metadata.sorted_tables
              if any(fk.target_fullname == "schools.id" for c in t.columns for fk in c.foreign_keys)}
    assert linked == SCHOOL_LINKED, (
        f"school-linked tables changed: new {sorted(linked - SCHOOL_LINKED)}, gone {sorted(SCHOOL_LINKED - linked)}. "
        "Make seed()'s reset branch delete new tables, then update SCHOOL_LINKED.")


def test_reseed_deletes_a_demo_school_with_saved_prefs(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'reseed.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    monkeypatch.setattr(seed_mod, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))
    monkeypatch.setattr(seed_mod, "init_db", lambda: None)
    seed_mod.seed()
    with seed_mod.SessionLocal() as db:
        sch = db.scalar(select(School).where(School.code == seed_mod.DEMO_CODE))
        t = db.scalar(select(Teacher).where(Teacher.school_id == sch.id))
        p = db.scalar(select(ParentAccount).where(ParentAccount.school_id == sch.id))
        assert db.scalars(select(HomeFocus)).all() and db.scalars(select(VoiceSession)).all()  # the demo has both
        db.add(UserPrefs(kind="teacher", user_id=t.id, school_id=sch.id, content_lang="mr"))
        db.add(UserPrefs(kind="parent", user_id=p.id, school_id=sch.id, voice_provider="gnani"))
        db.commit()
    seed_mod.seed()  # the reset branch: deletes the old school, then builds a new one
    with seed_mod.SessionLocal() as db:
        new = db.scalar(select(School).where(School.code == seed_mod.DEMO_CODE))
        assert new is not None  # rebuilt (SQLite may reuse the old id; Postgres does not)
        assert db.scalars(select(UserPrefs)).all() == []  # the old users' settings are gone with them
        assert all(r.school_id == new.id for r in db.scalars(select(HomeFocus)))
