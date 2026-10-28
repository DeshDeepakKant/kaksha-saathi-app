# Parent insights: contract (school → home)

Five parent features built from the teacher app's data: **This week at school**, **Learning
journey**, **Tips for specific mistakes**, **Teacher noticed moments** (celebrations + absent-day
catch-up) and a **Weekly summary** (read aloud, shareable image).

Rules for every feature:
- Only the parent's own child. Never group names/labels ("weak group"), never classmates, never
  numeric scores, ranks or comparisons. Status words for parents: **learned**, **working on**,
  **next** (never "needs intervention").
- "Learned" comes from school evidence only (home evidence is already capped below on-track by the
  mastery ceiling; don't change that).
- Texts are deterministic templates + reviewed content (no runtime AI): fast, safe, free.
- Hindi first, English available: every text field comes as `*_hi` and `*_en`.

## Reviewed content (content agent)
- `content/misconception_tips.json`: one entry per misconception id in
  `content/competency_graph.json` (62 ids):
  `{"id", "checkpoint_ids": [..], "explain_hi", "explain_en", "game_hi", "game_en", "example", "reviewed": true}`
  `explain_*`: one plain sentence a parent understands (what the child does wrong).
  `game_*`: a 1-minute home game with household things, 1–2 sentences. `example`: short, e.g. "52 − 17 → 45".
- `content/activity_home.json`: 5-minute home version of each activity in `content/activities.json`:
  `{"id", "title_hi", "title_en", "materials_hi", "materials_en", "steps_hi": [<=3], "steps_en": [<=3], "minutes": 5}`.
- `backend/app/services/tips.py`: `get_tip(misconception_id) -> dict | None`,
  `home_version(activity_id) -> dict | None`, `all_tips() -> dict`.

## API (backend agent) — parent JWT, all `/v1`, router `backend/app/api/parent_insights.py`
| Route | Returns |
|---|---|
| `GET /parent/school_week` | `{class_topic: {checkpoint_id, chapter, title_hi, title_en, subject} or null, child_focus: {checkpoint_id, title_hi, title_en, subject, state} or null, line_hi, line_en, as_of}` |
| `GET /parent/journey?subject=numeracy` | `{subject, grade, milestones: [{checkpoint_id, chapter, title_hi, title_en, nipun_ref, state: learned/working/next/later}], counts: {learned, working, total}, celebrations: [{checkpoint_id, title_hi, title_en, at, line_hi, line_en}], growth: [{week_end, learned}]}` |
| `GET /parent/tips` | `{tips: [{misconception, checkpoint_id, title_hi, title_en, explain_hi, explain_en, game_hi, game_en, example, seen_at}]}` (max 3) |
| `GET /parent/moments` | `{moments: [celebration or catch_up]}` — celebration `{kind:"celebration", checkpoint_id, title_hi, title_en, at, line_hi, line_en}`; catch_up `{kind:"catch_up", day, class_did_hi, class_did_en, activity: {id, title_hi, title_en, materials_hi, materials_en, steps_hi, steps_en, minutes} or null, line_hi, line_en}` |
| `GET /parent/weekly` | `{week_start, week_end, practice_days, voice_sessions, voice_minutes, learned: [{title_hi, title_en}], working_on: [...], next: [...], tip: tip or null, line_hi, line_en}` |

Definitions:
- **class_topic**: what the class is learning this week = the checkpoint with the most school
  evidence for this class in the last 7 days (teacher taps/notes/photos/probes); tie or none → the
  most common checkpoint in the class's latest plans; else null.
- **child_focus**: the child's group checkpoint in the latest plan for the class (shown as a topic,
  never as a group), else the child's most foundational gap from school evidence (`mastery.find_gap`).
- **journey milestones**: the class roadmap for the subject (template fallback), roadmap order.
  learned = on_track; working = needs_practice / needs_intervention; next = the first 2 not-started
  after the last learned/working one; later = the rest.
- **celebrations**: checkpoints that became on_track within the last 14 days (compare statuses with
  `ledger.child_statuses(..., before=<14 days ago>)`), plus "getting better" moves from
  needs_intervention to needs_practice within 7 days (moments only).
- **growth**: learned count at each of the last 6 week-ends.
- **tips**: `Evidence.misconception` on the child's school evidence in the last 30 days whose
  checkpoint isn't learned yet; newest first; max 3; one per misconception.
- **catch_up**: a school day in the last 3 days when the child was marked absent; what the class did
  = that day's plan (first group's activity; `home_version` for the 5-minute version) or class_topic.
- **weekly**: Monday–Sunday of the current school week (IST, `ledger.school_today()`); practice days
  = distinct days with a voice session or home session.

## Parent app (two UI agents)
- Home (`home_screen.dart`): a "This week at school" card with a read-aloud button; "Teacher
  noticed" moment cards (celebration with ⭐, gentle catch-up card); up to 3 tip cards; buttons to
  the Journey and Weekly screens. Existing voice-session card stays.
- `JourneyScreen()` (`screens/journey_screen.dart`): subject switch, milestone path with stars,
  celebrations, growth line. `WeeklyScreen()` (`screens/weekly_screen.dart`): summary, read aloud,
  share as image (share_plus).
- Read-aloud via `Speak.say(text, lang)` from `lib/tts.dart`.
