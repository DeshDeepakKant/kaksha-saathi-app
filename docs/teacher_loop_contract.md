# Teacher loop features: contract (v1)

Seven teacher features that close the diagnose → group → teach → **reassess** loop:
did-it-work outcomes (1), re-check queue (2), stuck children (3), first-week level check (4),
who-haven't-I-checked and fading statuses (6), correcting mistakes (7), missed-session catch-up (10).

The Flutter `Api` has only `get`, `postJson`, `postQueued` and `delete`, so every write here is a POST.
Rules that apply everywhere (see CLAUDE.md): code decides every status and count, no AI is used by
any of these features, every response is tenant-scoped (school of the JWT), payload changes are
additive only, UI text uses `tr('English', 'हिन्दी')` inline (do not edit `l10n.dart`), classroom
content stays Hindi. Status order used for "moved up/down": `not_started` = 0, `needs_intervention` = 0,
`needs_practice` = 1, `on_track` = 2. Dates are ISO `YYYY-MM-DD`, datetimes ISO 8601.
"Classroom evidence" = confirmed `Evidence` whose `source` is not in `mastery.HOME_SOURCES`.

## Data model (append to `backend/app/models/tables.py`; new tables only, so `create_all` adds them)

```python
class GroupSession(Base):          # owner: Backend-Insights
    """Snapshot of one group being taught (written when the teacher taps Done on a plan group)."""
    __tablename__ = "group_sessions"
    __table_args__ = (UniqueConstraint("plan_id", "group_key"),)
    id, school_id (FK schools), class_id (FK classes), plan_id (FK plans), subject String(16),
    group_key String(80), checkpoint_id String(80), activity_id String(80) | None,
    member_ids JSON (list[int] child ids, frozen at done time), done_at DateTime default utcnow,
    done_by FK teachers | None

class LevelCheck(Base):            # owner: Backend-Manage
    __tablename__ = "level_checks"
    id, school_id, class_id, child_id (FK children), subject String(16),
    level_index Integer (-1 = beginner, 0.. = index into the ladder), level_key String(24),
    at DateTime default utcnow, created_by FK teachers | None
```

## Content: `content/level_check.json` (Lead; already written, read-only for agents)
`subjects.{literacy|numeracy}` → `title_en/title_hi`, `beginner {key,title_en,title_hi}`, `levels[]` with
`key, title_en, title_hi, checkpoint_id, ask_en, ask_hi, items[{show, expect?, from?}], pass_min, of`.
A child passes a level when at least `pass_min` of the `of` items are right (teacher's judgment).

## Backend-Insights (features 1, 2, 3, 6, 10)

**Done records a snapshot.** `POST /v1/plans/{plan_id}/groups/{group_key}/done` (existing, idempotent):
also upserts a `GroupSession` from `plan.payload.groups[]` where `key == group_key` (members are
`{id, first_name}` dicts in v2 plans; older plans may hold roll numbers, resolve them). Response becomes
`{"ok": true, "session_id": int}`. `assess_first` is not a teaching group: return `{"ok": true, "session_id": null}`.

**History gains ids.** `GET /v1/children/{id}/history` rows gain `"id": evidence.id` (additive).

**`GET /v1/classes/{class_id}/followups?subject=`** (all lists capped at 20, sorted most urgent first)
```json
{"subject": "numeracy", "generated_at": "...",
 "recheck": [{"child_id": 1, "first_name": "मीना", "roll_no": 4, "checkpoint_id": "N.G2.sub_2digit_borrow",
              "title_en": "...", "title_hi": "...", "group_key": "...", "session_id": 3,
              "taught_on": "2026-10-27", "days_since": 2, "has_probe": true}],
 "stuck":   [{"child_id": 1, "first_name": "...", "roll_no": 4, "checkpoint_id": "...", "title_en": "...", "title_hi": "...",
              "status": "needs_intervention", "sessions": 3, "since": "2026-10-08",
              "alt_activity_id": "act_x" , "alt_activity_title_hi": "..." , "suggestion_en": "...", "suggestion_hi": "..."}],
 "missed":  [{"child_id": 1, "first_name": "...", "roll_no": 4, "checkpoint_id": "...", "title_en": "...", "title_hi": "...",
              "missed": 3, "of": 4, "last_missed": "2026-10-28"}],
 "not_checked": [{"child_id": 1, "first_name": "...", "roll_no": 4, "checks_14d": 0, "last_checked": "2026-10-10"}],
 "fading":  [{"child_id": 1, "first_name": "...", "roll_no": 4, "checkpoint_id": "...", "title_en": "...", "title_hi": "...",
              "status": "on_track", "last_evidence_on": "2026-10-10", "expires_in_days": 2}]}
```
- **recheck (2):** members of this class+subject's `GroupSession`s done in the last 14 days, done at least
  1 day ago, with no classroom evidence on that session's checkpoint after `done_at`. One row per child
  (latest session wins). `has_probe` = a probe exists for the checkpoint (`GET /checkpoints/{id}/probe` works).
- **stuck (3):** child is a member of ≥ 3 `GroupSession`s on the same checkpoint in the last 42 days and
  that checkpoint's current status is not `on_track`. `alt_activity_*` = a library activity for that
  checkpoint not used by those sessions (null if none). Suggestion text is fixed/templated, never AI, and
  never a diagnosis ("Try a different activity, or check the earlier step with the 2-minute probe").
- **missed (10):** over this subject's `GroupSession`s in the last 28 days, a child marked absent
  (`Attendance.present == False`) on the session's `done_at` date (school local date = UTC+5:30) counts as
  missed. List children with missed ≥ 2, or missed ≥ 1 when `of` ≤ 2. A missing attendance row is NOT absence.
- **not_checked (6a):** active children with ≤ 1 classroom evidence rows in this subject in the last 14 days.
- **fading (6b):** child × checkpoint (in this class's syllabus for the subject) whose current status is
  `on_track` or `needs_practice` and whose newest confirmed evidence is old enough that it drops out of
  `mastery.WINDOW_DAYS` within 5 days: `expires_in_days = WINDOW_DAYS - days_since_newest` (0..5).

**`GET /v1/classes/{class_id}/outcomes?subject=&days=42`** (feature 1)
```json
{"subject": "numeracy",
 "sessions": [{"session_id": 3, "plan_id": 9, "group_key": "...", "checkpoint_id": "...", "title_en": "...", "title_hi": "...",
               "activity_id": "act_x", "activity_title_hi": "...", "done_on": "2026-10-27",
               "members": 6, "moved_up": 4, "same": 1, "moved_down": 0, "not_rechecked": 1,
               "children": [{"child_id": 1, "first_name": "...", "before": "needs_intervention", "after": "needs_practice", "change": "up"}]}],
 "activities": [{"activity_id": "act_x", "title_hi": "...", "sessions": 2, "children": 10, "rechecked": 8, "moved_up": 6}]}
```
- `before` = status on the checkpoint from evidence strictly before `done_at` (`ledger.child_statuses(before=…)`).
- `after` = current status if the child has classroom evidence on that checkpoint after `done_at`, else
  `null` with `change: "not_rechecked"`. `change` ∈ `up|same|down|not_rechecked` by the status order above.
- Sessions newest first. `activities` aggregates sessions with an `activity_id`, sorted by `moved_up/rechecked`.

**Demo seed:** extend `backend/app/seed.py` so the DEMO class 2A (numeracy) has realistic history for
these lists on first boot: ~3 past `GroupSession`s on the borrowing group (some members re-checked and
improved, one not re-checked, one stuck across 3 sessions), and one absence on a session day.

## Backend-Manage (features 4 and 7; new files `api/level_check.py`, `api/manage.py`, `services/level_check.py`)

**`GET /v1/classes/{class_id}/level_check?subject=`**
```json
{"subject": "literacy", "title_en": "...", "title_hi": "...",
 "beginner": {"key": "beginner", "title_en": "...", "title_hi": "..."},
 "levels": [{"index": 0, "key": "letter", "title_en": "...", "title_hi": "...", "checkpoint_id": "...",
             "ask_en": "...", "ask_hi": "...", "items": [{"show": "क", "expect": null}], "pass_min": 4, "of": 5}],
 "children": [{"child_id": 1, "first_name": "...", "roll_no": 4,
               "first": {"level_index": 0, "level_key": "letter", "at": "..."} , "latest": {"level_index": 2, "level_key": "sentence", "at": "..."}}],
 "summary": {"total": 30, "checked": 12, "moved_up": 5,
             "first": {"beginner": 2, "letter": 4}, "latest": {"beginner": 1, "letter": 2, "word": 3}}}
```
`first`/`latest` are null when the child has no check. `moved_up` counts children whose latest level index > first.
422 for a subject with no ladder (only `literacy` and `numeracy` have one).

**`POST /v1/classes/{class_id}/level_check`** body
`{"subject": "literacy", "child_id": 1, "results": [{"level_key": "letter", "passed": true}, {"level_key": "word", "passed": false}], "client_uuid": "optional"}`
- `results` must start at level 0 and follow ladder order with no gaps; everything after the first
  `passed: false` is rejected (422). An all-pass run is fine.
- Writes one confirmed `Evidence` per tested level on its `checkpoint_id` (`source="guided_probe"`,
  `result` correct|incorrect, `score` 1.0|0.0, `confidence` 1.0, `created_by`) and one `LevelCheck` row
  (`level_index` = last passed index, or -1).
- Replays with the same `client_uuid` return the first answer without writing again.
- Response `{"level_index": 1, "level_key": "word", "title_en": "...", "title_hi": "..."}`.

**Undo a wrong entry.** `POST /v1/evidence/{evidence_id}/undo` → sets `status="rejected"` (only from
`confirmed`; 409 otherwise). `POST /v1/evidence/{evidence_id}/restore` → back to `confirmed` (only from
`rejected` and only for rows the teacher's school owns). Both return `{"id": 5, "status": "rejected|confirmed"}`.
Mastery already ignores non-confirmed evidence, so statuses update with no other change.

**Edit a student.** `POST /v1/children/{child_id}/edit` body any of `{"first_name": str, "roll_no": int,
"class_id": int, "active": bool}` → 409 when the roll number is taken in the target class, 404 for a class
of another school, 422 for an empty name. Returns `{"id", "first_name", "roll_no", "class_id", "active"}`.
**`GET /v1/classes/{class_id}/children/inactive`** → `[{"id", "first_name", "roll_no"}]` so a removed child can be restored.

**Topics.** `POST /v1/classes/{class_id}/syllabus/topics/{checkpoint_id}/rename` body `{"subject": str,
"title_en"?: str, "title_hi"?: str}` → only the school's own custom topics (422 "library topics can't be
renamed" otherwise); updates the `CustomCheckpoint` and re-registers it in the content cache.
`POST /v1/classes/{class_id}/syllabus/reorder` body `{"subject": str, "order": [checkpoint_id, ...]}` →
must be exactly the current topic ids (422 otherwise); writes a new syllabus version with the same
chapters and the new positions (`coverage.write_version`). Both return the same body as `GET /classes/{id}/syllabus`.

## Flutter-Loop (features 1, 2, 3, 6, 10) — owns `board_screen.dart`, `group_plan_screen.dart`, new `widgets/board_followups.dart`, new `screens/outcomes_screen.dart`
- "Done" on a plan group also calls `Api.i.postQueued('/v1/plans/$planId/groups/$key/done', {})`
  (keep the local SharedPreferences tick for instant feedback).
- Board: a "Follow-ups" card (collapsed summary with counts, expands to sections: Re-check today,
  Not moving, Missed group time, Not checked lately, Fading soon). Tapping a child opens the child profile
  (`LevelScreen`), where the existing 2-minute probe lives. Stuck rows show the alternative activity.
- "Did it work?": `outcomes_screen.dart` lists sessions ("4 of 6 moved up · 1 not re-checked") with the
  per-child before → after, and an "Activities that moved children" list. Reach it from the board
  (follow-ups card or app bar) and from the plan screen.
- Use `Api.i.get` / `Api.i.postQueued` directly; do not edit `api.dart`, `api_admin.dart` or `l10n.dart`.

## Flutter-Manage (features 4 and 7) — owns `roster_screen.dart`, `level_screen.dart`, `syllabus_screen.dart`, `widgets/syllabus_widgets.dart`, new `screens/level_check_screen.dart`
- `LevelCheckScreen({required int classId, required String subject})`: class summary (first vs latest per
  level, moved up), pick a child, then one level at a time: big `show` items, the `ask` line, tap each item
  right/wrong, "pass" computed from `pass_min`; stop at the first fail; save with `postQueued` and a
  `client_uuid`; then next child. Reach it from the roster app bar. (The Lead wires the board entry.)
- Child profile (`level_screen.dart`): each evidence history row gets "Undo" (with confirm) → undo route,
  then a snackbar with "Restore". Rows need `id` from history (added by Backend-Insights).
- Roster: edit name / roll number, move to another class, remove (deactivate) with confirm, and a
  "Removed students" list with restore.
- Syllabus: rename a custom topic; move a topic up/down (calls reorder with the full new order).
- Use `Api.i.get` / `postJson` / `postQueued` directly; no edits to `api.dart`, `api_admin.dart`, `l10n.dart`.
