# Voice session at the child's level: contract (v1)

Problem: every 30-minute voice session climbs the whole ladder (letter → word → sentence → reading),
because it starts low (English always at `letter`) and moves up a stage after **3 correct answers in a
row**. Children get a tour of every stage instead of practice on their own gap. The teacher's level
check, the child's group on the board and the last session's results are not used.

Goal: each session practises **the child's level**, chosen by code from the teacher's evidence, stays
there, moves up only on mastery (at most one stage per session), targets the child's specific weak
items, and is tracked across sessions. The teacher can set a child's home focus for a while.

Rules (all agents): CLAUDE.md. Code decides; additive payloads only (no renames/removals); new tables
only (create_all cannot alter); existing tests keep passing (update tests that assert the old
3-in-a-row climb, and say so); UI text through `tr()`/`trf()`; no new frameworks; children fictional.

Vocabulary: `STAGES = ("letter","word_build","word_read","sentence_build","reading")`
(`services/voice_types.py`). Session subject: `"english"` when `lang == "en"`, else `"literacy"`.

## 1. The plan (owner: Backend) — new `backend/app/services/voice_plan.py`

```python
def plan_session(db, child: Child, lang: str, syllabus: dict, *, now=None) -> dict
```
Pure read; no writes. Returns:
```json
{"v": 1, "subject": "literacy|english",
 "focus_stage": "word_build", "warmup_stage": "letter|null", "stretch_stage": "word_read|null",
 "start_difficulty": 1,
 "focus_checkpoints": ["L.G1.blend_no_matra", "..."],      // <= 4, built-in or teacher topics
 "target_sounds": ["म", "ि"],                              // <= 8, seeds st["weak_sounds"]
 "source": "teacher_override|level_check|board_gap|last_session|mastery|placement",
 "reason_en": "Level check on 24 Oct: reads letters, not yet words.",
 "reason_hi": "24 अक्टूबर की स्तर जाँच: अक्षर पढ़ लेता है, शब्द अभी नहीं।",
 "placement": false,                                     // true: no evidence, find the level first
 "override": null,                                       // {id, stage, note, until} when source is teacher_override
 "based_on_session": null}                               // id of the last session used, if any
```
Choosing `focus_stage`, first match wins:
1. **Teacher override**: active `HomeFocus` row for (child, subject) whose `until` is today or later.
2. **Level check** (latest `LevelCheck` for the subject, at most 45 days old). `level_key` is the highest
   level PASSED, so the focus is the next step:
   `beginner→letter, letter→word_build, word→sentence_build, sentence→reading, story→reading`
   (`story` also sets `start_difficulty = 3`: paragraphs and comprehension).
3. **Board gap**: the child's group on the board (`ledger.build_groups` for the subject); the gap
   checkpoint's stage via `stage_checkpoints(lang, stage)`.
4. **Mastery**: the lowest stage that is not secure (same test as today's `start_stage`, but return
   that stage itself, not one below).
5. **Placement**: no evidence at all for this subject → `placement = true`, provisional focus
   `word_read`.

Then **last session** (tracking): if the child's latest ENDED session in the same `lang` is newer than
the evidence used in 1–4 and its `report.outcome.next_focus_stage` is set, use that instead
(`source = "last_session"`, `based_on_session = id`) — except a teacher override always wins.

`warmup_stage` = one below focus (null at `letter`); `stretch_stage` = one above (null at `reading`).
`focus_checkpoints`: the focus stage's checkpoints that are in the class syllabus (`topics_for`
logic) and not `secure` for the child, the board-gap checkpoint first; fall back to all the stage's
checkpoints. `target_sounds`: the last session's `state.weak_sounds` (same lang), most recent first.
`reason_*`: one short sentence each, from the source (dates as "24 Oct" / "24 अक्टूबर").

## 2. The session flow (owner: Backend) — `services/voice_session.py`

`start()` calls `plan_session` and stores `st["plan"] = plan`, `st["phase"]`,
`st["focus_stage"]` (may change once), `st["focus_log"] = []` (bools, judged focus items),
`st["moves_up"] = 0`. `st["weak_sounds"]` starts from `plan.target_sounds`. Topics for item
generation in the focus stage use `plan.focus_checkpoints` (custom topics still added).

Phases (`st["phase"]`): `placement` → `warmup` → `focus` → `stretch` → `focus` … until time is up.
- **placement** (only when `plan.placement`): probe 2 items at `word_read`; both succeed (first_try or
  after_retry) → probe the stage above, else probe the stage below; stop when the direction reverses or
  the ladder ends (at most 3 probes, about 2 minutes). Focus = the lowest probed stage not passed (or
  `reading` if everything passed). At most 2 tries per placement item. Evidence is written as usual.
  Then set `plan.focus_stage/warmup/stretch`, `plan.source="placement"`, reasons ("Saathi checked the
  level first: …").
- **warmup**: 2 items at `warmup_stage`, difficulty 1 (skipped when null).
- **focus**: the main phase. Difficulty adapts inside the stage exactly as today (2 in a row →
  harder, a miss → easier). **No more stage climbing on 3-in-a-row.**
  - **Mastered** = at least 8 judged focus items and >= 80% success over the last 10. On mastery, if
    `moves_up == 0` and a stage above exists: move the focus up one stage (`moves_up = 1`,
    `stage_changed`, cheer). Never more than one move up per session; after that, stretch with
    difficulty inside the new focus.
  - **Support**: 3 fails in a row at difficulty 1 → drop one stage (support), and return to the focus
    after 3 successes there. A drop is not a level change in the outcome.
- **stretch**: when `remaining_s <= 240` and the focus was not mastered and `stretch_stage` exists:
  3 items at `stretch_stage`, difficulty 1; then back to focus for the remaining time.

`session_view` and every turn response add (additive): `"phase"`, `"focus_stage"`, and in
`session_view` also `"plan"` (the plan dict). Existing `stage`/`stage_changed` keep their meaning
(`stage` = the stage of the current item).

**Outcome** (computed at `end`, stored in `report["outcome"]`, also `report["plan"] = st["plan"]`):
```json
{"focus_stage": "word_build", "focus_items": 14, "focus_accuracy": 0.86, "mastered": true,
 "moved_up_to": "word_read|null", "stretch_stage": "word_read|null", "stretch_items": 3,
 "stretch_correct": 3, "next_focus_stage": "word_read", "next_reason_en": "...", "next_reason_hi": "..."}
```
`next_focus_stage`: the stage moved up to, else stretch stage if all stretch items succeeded, else
the same focus. `summary()` rows add `focus_stage`, `mastered`, `next_focus_stage`, `plan_source`.

## 3. Teacher override and tracking (owner: Backend)

New table (append to `models/tables.py`):
```python
class HomeFocus(Base):
    __tablename__ = "home_focus"
    id, school_id FK schools.id (index), child_id FK children.id (index),
    subject String(16), stage String(20), checkpoint_ids JSON default list,
    note String(200) nullable, created_by Integer nullable, created_at DateTime,
    until Date, active Boolean default True
```
`seed()`'s reset branch and both `DELETE /children/{id}/data` and `/classes/{id}/data` delete these
rows; add `"home_focus"` to `SCHOOL_LINKED` in `tests/test_reseed.py`.

Teacher routes (tenant-checked with `owned_child`), in `api/voice.py`:
- `GET /v1/children/{child_id}/home_focus?subject=literacy|english` →
  `{"subject", "plan": <plan_session preview for the next session, lang "en" for english else the
  parent's content language or "hi">, "override": {id, stage, checkpoint_ids, note, until}|null,
  "history": [{"session_id", "date", "lang", "focus_stage", "focus_accuracy", "mastered",
  "next_focus_stage", "plan_source"} ... up to 8, newest first]}`
- `PUT /v1/children/{child_id}/home_focus` body `{subject, stage, checkpoint_ids?: [], note?: str<=200,
  days?: 1..30 (default 7)}` → deactivates any active row, writes a new one, returns the GET body.
  422 for an unknown stage/subject or a checkpoint not in the content.
- `DELETE /v1/children/{child_id}/home_focus?subject=` → deactivates; returns the GET body.

Parent route: `GET /v1/parent/voice/plan?lang=<code>` → the plan preview for the parent's child
(same dict as §1), for the "Today's practice" card before starting.

**Demo seed** (bump `SEED_VERSION`): roll 12 (the demo parent child) gets 2 ended Hindi sessions over
the last week with plans and outcomes (first at `word_build`, mastered; second at `word_read`, not yet
mastered), so the history shows a trend and the next plan is `word_read` from `last_session`.
One other 2A child gets an active teacher override (e.g. English `letter`, note "Practise letter sounds
this week"). Seeded sessions need only the fields the report/summary/history read (state, report, a
few turns are optional).

Tests (fresh SQLite): each plan source and its precedence; level mapping; placement probe path
(up and down); mastery move up once only; support drop and return; stretch at the end;
outcome/next_focus; override CRUD + tenant isolation + 422s; plan preview route; reseed and delete
routes remove `home_focus`; the old climb test updated.

## 4. Parent app (owner: Flutter-Parent) — `apps/parent/lib` only

- Before starting (`voice_session_screen.dart` pre-start view): a **"Today's practice"** card from
  `GET /v1/parent/voice/plan?lang=` — focus stage label (`voiceStageLabel`), the reason in the app
  language (`reason_en`/`reason_hi`, `pick`-style), and when `placement` is true:
  "Saathi will first find the right level (about 2 minutes)." When the teacher set it: "Set by the
  teacher" + note. Hide the card if the call fails.
- During the session: the ladder widget highlights the **focus** stage (`focus_stage`), and a small
  phase chip: Warm-up / Practice / Challenge / Finding the level. Cheer "new level" only when
  `stage_changed` and the new `focus_stage` is higher than the old `focus_stage` (not on support
  drops or stretch items).
- Report screen: a "Focus" line: stage, accuracy, mastered or not, "Next time: <stage>".
- Strings via `tr()`/`trf()`; don't regenerate translation tables (the Lead does that after merge).
  `flutter analyze` clean; `flutter test` passes.

## 5. Teacher app (owner: Flutter-Teacher) — `apps/teacher/lib` only

- `widgets/voice_sessions_card.dart` (shown on the child screen for literacy and English): a
  **"Home practice focus"** header from `GET /v1/children/{id}/home_focus?subject=` — next session's
  focus stage + reason, "Set by you until 7 Nov" when overridden; buttons **Change** (bottom sheet:
  pick one of the 5 stages with `voiceStageLabel`, optional note, 7/14 days → `PUT`) and **Back to
  automatic** (`DELETE`). Under it, the history as a compact trend (date · focus stage · accuracy ·
  ✓ mastered → next). Filter the session list to the subject (English sessions for `english`, others
  for `literacy`) using `lang`.
- `screens/voice_report_screen.dart`: a "Focus" section from `report.plan` and `report.outcome`
  (source/reason, focus accuracy, mastered, moved up, stretch result, next focus).
- Writes need the network: on failure show the normal error snackbar; reads may use the cache.
- Strings via `tr()`/`trf()`; don't regenerate translation tables. `flutter analyze` clean; `flutter test`.
