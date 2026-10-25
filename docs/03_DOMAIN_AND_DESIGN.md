# 03 · Domain & Design

> The learning model, the mastery and grouping algorithms, the parent-session design, user experience for both apps, data model and API surface.
> This is where the product's pedagogy becomes software.

---

## 1. Learning model

### 1.1 Checkpoints

A **checkpoint** is the smallest unit the system tracks. It carries:

```json
{
  "id": "N.G2.sub_2digit_borrow",
  "subject": "numeracy",
  "grade": 2,
  "domain": "operations",
  "chapter": "Subtraction",               // for the teacher's view; comes from roadmap
  "title_hi": "दो-अंकीय घटाव (उधार के साथ)",
  "title_en": "2-digit subtraction with borrowing",
  "assess_via": ["photo_work", "class_voice", "teacher_tap"],
  "item_types": ["worked_problems", "read_aloud_not_applicable"],
  "misconceptions": ["borrow_from_wrong_column", "ignores_zero_borrow", "subtracts_smaller_from_larger"],
  "prereqs": ["N.G2.sub_2digit_no_borrow", "N.G2.place_value_99"],
  "nipun_ref": "Grade 2: subtracts numbers up to 99",
  "language": "numeracy"                     // or "hi", "en"
}
```

**Two sources of checkpoints:**
1. **The reviewed competency graph** (`content/competency_graph.json`): ~45–60 nodes for Grades 1–3 numeracy + Hindi literacy, with prerequisite edges, misconception taxonomy and NIPUN references. This is the *authority for prerequisite reasoning*. It is authored/adapted from the existing graph in the previous build and **must be reviewed by an education mentor** before pilot.
2. **The teacher's roadmap** for a class × subject: which checkpoints appear, in what chapter order, with teacher-added custom checkpoints for textbook topics not in the graph (marked `custom: true`, no prereqs unless the teacher links them).

### 1.2 Roadmap generation from the index photo

**Goal:** save the teacher 45 minutes of typing. **Not:** let the model invent the curriculum.

```
Index photo ──vision──▶ {chapters: [{title, subtopics: [...]}, ...]}   (structure only)
                        │
                        ▼
        Matching step (code + fuzzy + embeddings):
          each subtopic → nearest graph checkpoint(s) in the same subject/grade band
          unmatched → custom checkpoint (draft title from the photo)
                        │
                        ▼
        Draft roadmap (ordered as in the photo; prerequisites inherited from graph)
                        │
                        ▼
        Teacher review screen: reorder, rename, merge, drop, add; confirm
                        │
                        ▼
        Frozen roadmap version (immutable; new version if changed later)
```

**Guardrails:** the model output is validated (no empty chapters; every subtopic maps to ≥ 0 checkpoints; total checkpoints 5–60). If vision fails, the teacher builds the roadmap from the graph's chapter templates for the class grade (2-tap start).

**Reuse:** roadmap versions are stored per `(school, grade, subject, board)`. A teacher in Section B of the same grade imports Section A's reviewed roadmap with one tap.

---

## 2. Evidence model

```json
{
  "id": "ev_…",
  "child_id": 42,
  "checkpoint_id": "N.G2.sub_2digit_borrow",
  "result": "incorrect",                 // correct | partial | incorrect | unattempted
  "score": 0.25,                         // 0..1 continuous score when available (e.g. 1 of 4 items)
  "misconception": "subtracts_smaller_from_larger",   // optional; from fixed taxonomy
  "source": "photo_work",                // photo_work | class_voice | teacher_tap | teacher_note | guided_probe | home_voice | home_tap
  "confidence": 0.82,                    // model/scorer confidence; teacher entries = 1.0
  "session_id": "as_…",                  // groups evidence from one capture
  "at": "2026-10-29T09:40:00+05:30",
  "status": "confirmed"                  // proposed | confirmed | rejected
}
```

**Rules**
- Only `confirmed` evidence affects mastery. `proposed` rows exist between AI output and teacher confirmation; they expire after 72 h.
- `rejected` is retained for eval (what the model got wrong) but has no effect.
- Every row is append-only. Corrections are new rows with `supersedes: ev_…`. This gives a full history and audit trail.
- **Source weights** (initial, tunable in eval):

| Source | Weight | Rationale |
|---|---|---|
| `teacher_tap` (explicit per-child judgement) | 1.0 | Direct observation with teacher's confidence |
| `guided_probe` (teacher-delivered probe) | 1.0 | Controlled test |
| `photo_work` confirmed (≥ 3 independent items) | 0.9 | Objective, multiple items |
| `photo_work` confirmed (< 3 items) | 0.7 | Less evidence |
| `class_voice` confirmed | 0.8 | Noisy acoustic setting |
| `teacher_note` confirmed | 0.7 | Informal remark |
| `home_voice` (code-judged) | 0.5 | Different setting; AI-judged |
| `home_tap` | 0.4 | Self/parent-selected |

---

## 3. Mastery engine (deterministic)

### 3.1 Per-evidence "value"

```
v(result) = correct → 1.0 ;  partial → 0.5 ;  incorrect → 0.0 ;  unattempted → (excluded)
w = source_weight × confidence
```

### 3.2 Status computation

```
E = confirmed evidence for (child, checkpoint), most recent first
E_r = evidence within the last 21 days (window, per checkpoint type)
if |E| = 0                                       → not_started
score = Σ (v_i · w_i · decay_i) / Σ (w_i · decay_i)     decay_i = exp(-age_days / 14)
evidence_volume = Σ w_i (within window)
if evidence_volume < 0.8                         → not_started            (too little evidence)
if score ≥ 0.75 AND latest result = correct AND latest ≥ 2 evidences agree → on_track
if score < 0.35 OR (latest result = incorrect and score < 0.5)            → needs_intervention
else                                                                      → needs_practice
```

**Additional rules**
- **Recency override:** if the 2 most recent confirmed evidences (any source) are `incorrect`, status is at most `needs_practice` regardless of recent good scores (intervention happened → shown as improving only via new reassessment).
- **Progress state:** `improving` is a *flag* (trend slope > 0 over last 3 evidences after an intervention) shown alongside status, not a status value. (Spec's "Before → Improving → On Track" is modelled as status + improvement flag.)
- **Home ceiling:** home-only evidence can raise a status at most to `needs_practice` (never `on_track`). See ADR-3.
- **Absence:** no evidence is invented for absent children. A child with no confirmed evidence that day keeps their prior status — the profile shows "not assessed today" (see §6.2).
- **Confidence** per (child, checkpoint) = 1 − exp(−evidence_volume) — drives UI: low confidence items display a "?" and prompt the teacher to check.

### 3.3 Gap detection with prerequisites

For each child × subject:

```
failing = checkpoints with status in {needs_intervention}   (and needs_practice as secondary)
for each f in failing:
    walk prereqs (DFS) collecting the lowest "root" r where
       r is failing OR r has partial/incorrect evidence, AND
       all prereqs of r are NOT failing
    gap = r if found else f
priority(gap) = 1 (needs_intervention root) / 2 (needs_practice root)
              × grade_weight (lower grade prerequisite = more foundational)
              × recency   (recent evidence weighs more)
```

**Example:** Child fails `N.G2.sub_2digit_borrow` (incorrect). `N.G2.sub_2digit_no_borrow` is also `needs_intervention`. → Root gap = `no_borrow` (or lower if `N.G1.sub_single` also fails). The group is formed at the **foundational** point, not at the grade-level topic — this is the TaRL insight encoded as an algorithm.

**Probe suggestion:** if a gap persists for ≥ 3 sessions across ≥ 2 weeks, or the child fails a listening-heavy checkpoint while passing similar written checkpoints, suggest a language-vs-concept probe (P2 feature, [04 §6](04_AI_SPECIFICATION.md)).

---

## 4. Grouping engine

### 4.1 Algorithm

```
for subject in subjects(class):
    candidates = children with a root gap in subject
    key(child) = (gap.checkpoint_id, gap.priority)
    groups = children grouped by key, sorted by (priority, checkpoint.sort_order)
    // merge small groups at the same checkpoint family (same chapter) when < 3,
    // never merge across different root concepts with different interventions
    groups = merge_small(groups, min_size=3, same_chapter_only=True)
    // split groups > 12 for blackboard feasibility? No — pedagogically keep together; UI marks
    on_track = children with no root gap
    unassessed = children with too little evidence (show as "assess first" list, not a group)
```

- Group size target 3–10. Groups > 12 flagged "whole-class re-teach likely" (a systemic gap — the plan becomes a whole-class activity and the teacher sees this as a signal).
- **Stability:** groups are computed per day, but the UI shows changes since yesterday ("Rahul moved from Group 2 to On Track") and never renames groups overnight without a banner.
- **Dynamic movement:** movement is automatic after confirmed reassessment evidence; teacher can pin a child to a group for a day (e.g., they'll be absent).

### 4.2 UI output

```
कक्षा 2A — आज की स्थिति (30 बच्चे)
┌───────────────────────────────┐
│ समूह 1 · उधार का घटाव  (5)    │  [योजना देखें]  [भेजें]        ← intervention card
│ समूह 2 · पहाड़े 2–5    (4)    │  [योजना देखें]
│ समूह 3 · स्थानीय मान   (3)    │  [योजना देखें]
│ आधार निर्धारण बाकी (6)        │  [3-टैप चेक]                   ← unassessed children
│ अपनी गति पर (12)              │  [मज़ा कार्य]                  ← enrichment, optional
└───────────────────────────────┘
```

---

## 5. Parent app — voice tutor design

### 5.1 What the parent app is and isn't

- **Is:** a 25–30 minute daily structured practice session, in the child's language, with a friendly voice, that focuses on the child's top confirmed gaps (and flags from home evidence), plus a tiny bit of enrichment.
- **Isn't:** a free chatbot, a homework solver, an assessment that changes school records, a screen-time trap (no infinite scroll, no rewards economy).

### 5.2 Session structure (harness state machine)

```
START → GREET (child name, plan for today, 1 line)
  → for each of 6–10 activities (ordered by priority: gaps first, then maintenance, then enrichment):
       INTRO      (Claude: 1–2 short sentences; TTS plays)
       PROMPT     (fixed item from pack: word / picture / number; TTS model pronunciation)
       ATTEMPT    (child speaks ≤ 6 s, or taps)
       JUDGE      (code: ASR vs target → correct/close/wrong; Claude only for feedback text)
       FEEDBACK   (Claude: short, warm, specific: "Almost! In 'कमल' the 'म' is soft.")
       retry?     (up to 2 retries if judged wrong; after 2 → record difficulty, move on — never stuck, never punishing)
       RECORD EVIDENCE (per attempt; wrong evidence only after 2 attempts today)
  → MINI-CHECK (2–3 items across today's focus; no inference for correctness that the code can't judge)
  → WRAP (Claude: 2-line summary, one thing to tell the teacher, encouragement; TTS)
  → SYNC (send evidence + transcript summary when online; session stored locally)
```

**Timing budget:** ~2–3 min/activity × 8 + greet/wrap ≈ 25–30 min. The UI shows a soft timer; the child can stop after each activity.

**Adaptive within session:** if the child answers the first 2 items of an activity correctly, skip the 3rd and 4th; if 2 wrong, add a scaffolded easier version (same concept, easier item) from the pack.

### 5.3 Activity types and content bank

| Type | Code judges | Example | Offline? |
|---|---|---|---|
| Say the word (reading) | word-diff against target | Model says "कमल"; child reads it | ✅ with cached audio |
| Match picture ↔ word | tap (no speech) | 4 pictures, child taps | ✅ |
| Build the word (word formation) | ASR word match / tap syllables | Hear "कमल", tap क + म + ल in order | ✅ tap |
| Say the number / count | number normalization | "12" → "बारह" | ✅ |
| Solve & say | exact number match | "23 + 5 = ?" | ✅ |
| Multiple choice maths | tap | visual options | ✅ |
| Free retell (enrichment) | Claude only (not scored for mastery) | "Sun told a story..." | ❌ needs Claude (skip offline) |

Content bank: `practice_items.json` — per checkpoint, 10–20 items with word/number target, distractors/pictures (SVG/emoji/line art assets), difficulty tier, and optional hint. Items are **human-reviewed** and generated offline by a batch job from Claude + human edit pass (see [04 §6](04_AI_SPECIFICATION.md)).

### 5.4 Child-safety design

- Tutor persona: "साथी दीदी / Saathi" — a patient helper. Fixed system prompt with hard rules: no personal questions beyond learning, no asking for address/phone/photo, no opinions on people, no stories outside learning, never claim to be a person, never shame mistakes.
- **Moderation inputs:** every child transcript passes a Haiku-class classifier; if distress/abuse self-disclosure detected → no model continuation, play a fixed "किसी बड़े को बताइए" (tell a grown-up) card, flag to parent summary (no other viewing).
- **Output filter:** model output validated for length, vocabulary band (declared age band), blocked-topic list; out-of-scope → fixed fallback line.
- **Time limit:** session ends at ≤ 30 min or when activity list is done; parent PIN screen to close.

---

## 6. Teacher experience design

### 6.1 Primary flows (target taps/time)

| Flow | Steps | Target |
|---|---|---|
| Onboard class | Login → school code + PIN → choose class from pre-registered (or add 30 names from a list/CSV) → done | 5 min once |
| Build roadmap | Photo of index → review draft (default accept) → confirm | 3 min per subject, once |
| Capture notebook | Tap child → 📷 → take photo → AI analysis (wait ≤ 8 s) → confirm (tick/untick) → saved | ≤ 90 s |
| Capture classroom voice | Tap child → 🎤 → app shows target words → record 10–20 s → ASR/judge → confirm 3 ticks | ≤ 60 s |
| Quick notes (after class, voice) | 🎤 note ("आज उधार कराया…") → transcript → chips of children/status → confirm | ≤ 45 s |
| Tap checklist (zero AI) | Tap child → checkpoint list → tap ✓/⚠/✗ | ≤ 20 s |
| Today's plan | Tap "आज की योजना" → 2–4 group cards → tap one → activity steps + script + blackboard text → listen (TTS) | ≤ 2 min |
| Reassess | From the group card → "फिर से जाँचें" → tap/photograph/say → results update groups | ≤ 60 s |

### 6.2 Child profile screen

- Header: name, roll, class; **"आज मूल्यांकन नहीं हुआ"** if the day has no evidence (absent / not assessed — visually distinct from "not started").
- Subject tabs (गणित / हिंदी). Each shows chapters collapsed; checkpoints with status chips: ✓ on track, ⚠ needs practice, ✗ needs intervention, · not started, ? low confidence.
- Timeline: last 14 days of evidence (dots by source), interventions done, reassessments.
- "Beliefs" section: `Could be`: misconception chips (e.g. "subtracts smaller from larger") with the evidence that supports them; each chip has "Ask in class" → generates a 20-second probe script.
- Buttons: "ध्यान दें" flag, "घर पर अभ्यास भेजें" (prioritises this checkpoint for home sessions), "प्रोफ़ाइल निर्यात" (export).

### 6.3 Language and tone

- All UI strings in Hindi first (English toggle). Reading level: simple. Icon + short label everywhere.
- AI output is written in a warm, concrete, teacher voice; it never says "the AI thinks"; it says "राहुल को उधार वाला घटाव अभी कठिन लग रहा है — यह गतिविधि आज़माएँ" (Rahul is finding borrowing hard — try this activity).
- Every AI proposal shows a subtle "AI" chip and an "edit" affordance.

---

## 7. Data model

### 7.1 Entities

```
school(id, name, region_code, created_at)
teacher(id, school_id, name, phone_hash, pin_hash, role, created_at)
class(id, school_id, teacher_id, grade, section, label, subject_ids[], roadmap_version_ids[])
child(id, class_id, roll_no, first_name, name_alt_script?, consent_on, consent_source, consent_by, created_at)
                                                              └─ e.g. 'paper_form_photo_2026-10-20'
roadmap_version(id, school_id, grade, subject, board, version, created_by, reviewed_by_teacher, confirmed_at, source ('photo'|'template'|'import')) 
roadmap_item(id, roadmap_version_id, chapter, position, checkpoint_id, custom_title?, custom_prereqs[])
checkpoint(id, subject, grade, domain, chapter_default, title_hi, title_en, prereqs[], misconceptions[], nipun_ref, assess_via[], language, reviewed)
activity(id, checkpoint_ids[], chapter_ctx, mode, title_hi, materials_hi, steps_hi[], duration_min, blackboard_hi, reassessment_item, source_doc, page, reviewed, language)
practice_item(id, checkpoint_id, type, target, distractors[], asset_ref, difficulty, language, reviewed)
evidence(id, child_id, checkpoint_id, result, score, misconception, source, confidence, session_id, at, status, supersedes_id?, created_by)
capture_session(id, teacher_id, class_id, kind ('photo'|'class_voice'|'note'|'probe'|'tap'), input_ref, created_at, ai_status, fallback_used)
ai_call(id, feature, model, prompt_version, input_tokens, output_tokens, latency_ms, cost_inr, validation_status, ref_session_id, school_id, created_at)
plan(id, class_id, subject, for_date, groups jsonb, status, generated_by ('ai'|'fallback'), created_at)
intervention_log(id, plan_id, group_key, activity_id, done_at, teacher_note?, reassessed_at?)
probe(id, child_id, checkpoint_id, script_hi, items jsonb, result jsonb)
```
Parent side:
```
parent_account(id, child_ids[], auth (phone_hash + pin), consent_at, language, created_at)
session(id, child_id, pack_id, started_at, ended_at, activities_done, offline, transcript_summary_hi, evidence_count)
session_turn(id, session_id, activity_ref, attempt_no, transcript_redacted, judged ('correct'|'close'|'wrong'), feedback_hi, at)
pack(id, child_id, for_date, jsonb, audio_refs[], generated_at)
```
Tenancy:
```
all rows carry school_id (denormalised where necessary); Postgres RLS policies on school_id + ownership
```

### 7.2 Indexing / integrity

- Unique `(class_id, roll_no)`; unique `(school_id, grade, subject, board, version)` for roadmaps.
- `evidence(child_id, checkpoint_id, at DESC)`, `evidence(session_id)`.
- Foreign keys everywhere; checkpoint IDs in evidence validated against a roadmap version the class has.
- `roadmap_version` immutable once confirmed; edits create a new version; evidence points to the checkpoint ID (stable across versions).

### 7.3 Retention

| Data | Retention |
|---|---|
| Raw photos | 7 days (school-configurable 1–30); face-blocked at upload |
| Classroom audio | deleted within 24 h (job); only transcript-derived evidence |
| Parent session audio | deleted within 24 h; transcript summary kept (no raw transcript except 7 days for debug, redacted names) |
| Evidence, statuses, plans | until class deletion |
| AI call logs | 90 days (no child names; hashed refs) |

---

## 8. API surface (REST, JSON; all under `/v1`, JWT bearer, tenant-scoped)

### Teacher
```
POST   /auth/login                  {school_code, pin, device_id}            → token, teacher
GET    /classes                     → classes, consent status
POST   /classes/{id}/children       {first_name, roll_no, consent_source}
GET    /classes/{id}/roster
POST   /roadmaps                    multipart photo | {template: true, grade, subject} → draft
POST   /roadmaps/{id}/confirm       {items:[{chapter, checkpoint_id|custom_title, position}]}
GET    /roadmaps/{class_id}/{subject}
POST   /captures/note               multipart audio | {text} → proposed evidence + chips
POST   /captures/photo              multipart image, child_id → proposed per-question evidence
POST   /captures/voice              multipart audio, child_id, checkpoint_id, target_items[] → scores + proposed evidence
POST   /captures/tap                {child_id, items:[{checkpoint_id, result, misconception?}]} → committed evidence
GET    /captures/{id}/status        → processing | ready | failed | fallback
POST   /evidence/confirm            {capture_id, accepted:[evidence_drafts], rejected:[]} → committed
POST   /plans                       {class_id, subject, for_date} → plan (cached)
GET    /plans/latest/{class_id}
POST   /plans/{id}/groups/{key}/done      (optional intervention log)
POST   /children/{id}/export  · GET /children/{id}/profile · GET /children/{id}/history
DELETE /children/{id}/data · DELETE /classes/{id}/data
```

### Parent
```
POST   /parent/consent              {invite_code, child_roll, parent_phone, consent: true}
POST   /parent/auth                 {phone, pin}
GET    /parent/child                → child, focus areas (friendly), streak
GET    /parent/pack?date=           → session pack (json + audio urls)
POST   /parent/sessions             → {session_id, plan}
POST   /parent/sessions/{id}/turn   multipart audio | {tap_answer, activity_ref, attempt_no} → {judged, feedback, tts_url?, next}
POST   /parent/sessions/{id}/end    {summary}
GET    /parent/history
DELETE /parent/child/data
```

### Ops
```
GET  /healthz  /readyz   GET /metrics   GET /cost/today (teacher-visible)
```

---

## 9. Seeded demo content

- **Demo school** `DEMO` with teacher `asha` (PIN 1234) and classes 2A (30 children), 3A (28 children).
- **Fictional names**; roll numbers; consent recorded.
- **Roadmaps** for 2A numeracy + Hindi (confirmed), so evaluations start on the main loop.
- **Three weeks of history** generated by the team (realistic mix) so profiles, groups and trends are visible.
- **Demo inputs** in `evals/golden/demo/`: 5 notes in Hindi, 5 notebook photos, 5 classroom clips, 3 parent sessions.
- **Parent demo child:** Rahul (roll 12) with a downloaded pack, so the parent flow is 2 taps from the start.

---

## 10. Design system notes

- Palette: warm, low-glare; large type (16 sp body, 20 sp+ headings); one primary action per screen.
- Materials: status colours are redundant with icons/shapes (✓ ⚠ ✗ ?) and never colour-only.
- Charts (progress): dot-timeline rather than complex graphs; parent app avoids numeric scores, uses faces/labels.
- Illustrations/icons from open sets (e.g., Material Symbols) only; no clip-art of children.
- Motion: minimal; loading states must explain what's happening ("फ़ोटो पढ़ी जा रही है — 5 सेकंड").
- Print/share: intervention card rendered to a WhatsApp-friendly PNG (A4 or 9:16).
