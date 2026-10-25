# 04 · AI Specification

> Every AI and speech call in the system: purpose, inputs, output schema, model, prompting strategy, guardrails, failure behaviour, and cost.
> Rule of thumb throughout: **Claude where language understanding/generation is needed; deterministic code where correctness, scoring, or counting is needed.**

---

## 1. AI call inventory

| ID | Feature | Where | Model class | Deterministic check after | Fallback |
|---|---|---|---|---|---|
| A1 | Voice-note → evidence | Teacher, end of class | Haiku | roster match, checkpoint ∈ roadmap | tap checklist |
| A2 | Written-work photo → per-question evidence | Teacher | Haiku (vision) | arithmetic re-check in code; checkpoint mapping | manual per-question ✓/✗ |
| A3 | Classroom-voice → checkpoint evidence | Teacher | ASR + scorer, then Haiku | acoustic scores rule over model | tap checklist |
| A4 | Index photo → roadmap draft | Teacher, once | Haiku (vision) | structure validation; checkpoint matching | grade template |
| A5 | Guided probe script | Teacher (P2) | Sonnet | item count, checkpoint coverage, item validity | pre-written probes |
| A6 | Misconception hypothesis | Teacher profile | Sonnet | only from fixed taxonomy; requires ≥2 supporting evidences | no hypothesis shown |
| A7 | Intervention plan | Teacher, morning | Sonnet | activity IDs ∈ reviewed library, ≤ 10 min, group members consistent | template plan |
| A8 | Home → teacher summary | Teacher, class board | Sonnet | ≤ 3 lines; only facts from session | template line |
| A9 | Tutor turn dialogue | Parent | Sonnet | code judges correctness; safety filter | canned lines |
| A10 | Tutor safety classifier | Parent | Haiku | tri-state; any doubt → safe redirect | redirect |
| A11 | Batch: generate practice items | Offline authoring | Sonnet | human review + auto validity checks | — |
| A12 | Batch: generate probe scripts & activity drafts | Offline authoring | Sonnet | mentor review | — |
| A13 | RAG embeddings | All | Embedding model/API | — | lexical fallback |

---

## 2. Models (pinned)

| Class | Model | Why | Approx. pricing assumption used for cost table |
|---|---|---|---|
| Haiku | `claude-haiku-5-5` (latest Haiku Claude) | High volume, short, schema-bound extraction | ~$1 / Mtok in, ~$5 / Mtok out |
| Sonnet | `claude-sonnet-5-5` (latest Sonnet Claude) | Multi-constraint planning, tutor dialogue | ~$3 / Mtok in, ~$15 / Mtok out |

**Rule:** one `MODELS` dict in `backend/app/ai/config.py`; never hard-coded in prompts. Any model change must re-run the eval suite ([05](05_EVALUATION_PLAN.md)). Prompt caching enabled for system blocks ≥ 1,024 tokens.

**Speech**
| Purpose | Provider | Notes |
|---|---|---|
| ASR (Hindi, code-mixed, read-aloud) | Sarvam AI (streaming/batch) | Provide `keyterms` = target words + child's first name + roster names for note calls |
| TTS (model pronunciations, plan read-aloud) | Sarvam TTS (cache audio per word) | Child-directed voice; speed 0.9 |
| Pron. scoring | In-house scorer (§5) | No reliance on proprietary pronunciation scores |

> Fallback provider: Google Speech-to-Text (hi-IN) via the same `ASRProvider` interface if Sarvam rate-limits or fails; keep the interface narrow (`transcribe(audio, language, keyterms) -> {text, words[{w, start, end, conf}]}`).

---

## 3. Prompt engineering standards

1. **Personas are narrow.** Each prompt has one job. No "do everything" prompts.
2. **Schemas are explicit and typed.** Output is JSON conforming to a Pydantic model; the schema is included in the request. One retry includes the validation error.
3. **Enumerations, not free choice.** Checkpoint IDs, misconception IDs, activity IDs, result values come from closed lists supplied in context.
4. **Names are tokens.** The planner and any batch call receives `{R12}` instead of names; the server fills names after validation. Extraction (A1–A3) needs first names to resolve who was mentioned — it receives only first names, from the roster, and nothing else about the child.
5. **Evidence must cite.** Every extracted claim carries the source text span (note) or question item (photo) it came from. The confirm UI shows "from: 'मीना को उधार समझ नहीं आया'".
6. **Hedge language is required** where uncertainty exists (`confidence` per item). The model may output `null` rather than guess.
7. **No numbers computed by the model.** The model may *read* a number written in the notebook; all arithmetic comparisons, aggregation and scores are code.
8. **Versioned prompts.** `backend/app/ai/prompts/{feature}.v{n}.md` + a `PROMPTS` registry with the version flowing into every `ai_call` row.
9. **Language:** prompts are in English; outputs are requested in Hindi (teacher/child-facing) with numeric IDs. The model is told to use the state's school terminology where provided (glossary block).

---

## 4. Feature specifications

### A1 · Voice note → evidence

**Input:** transcript (from Sarvam), roster `[{roll, first_name}]`, roadmap checkpoints `[{id, title_hi, chapter, prereqs_snippet}]`, today's date.
**Output schema:**
```json
{
  "taught": [{"checkpoint_id": "N.G2.sub_2digit_borrow", "evidence_kind": "whole_class_taught"}],
  "children": [
    {"roll": 12, "name_match": "राजकुमार", "status": "absent"},
    {"roll": 7,  "name_match": "मीना", "checkpoint_id": "N.G2.sub_2digit_borrow",
     "result": "incorrect", "misconception": "borrow_from_wrong_column",
     "quote": "मीना को उधार समझ नहीं आया", "confidence": 0.8},
    {"roll": 3,  "checkpoint_id": "N.G2.sub_2digit_borrow", "result": "correct",
     "quote": "अर्जुन ने सब सवाल खुद किए", "confidence": 0.7}
  ],
  "unresolved": [{"name_match": "सूरज", "reason": "no_roster_match|ambiguous"}]
}
```
**Code checks:** resolve `name_match` (rapidfuzz + roster) — ambiguous → must be chosen by teacher; `checkpoint_id` ∈ roadmap of this class+subject; `result` enum; `quote` non-empty for any child claim; absent children create no evidence.
**Output to teacher:** chips — "मीना: उधार — कठिन? [हाँ][नहीं]", "अर्जुन: सही ✓".
**Cost:** ~1.5k in / 300 out → ≈ $0.003.

### A2 · Written-work photo → per-question evidence

**Input:** image (≤ 2 MB, page only), child, roadmap checkpoints with `item_types`, subject.
**Output schema:**
```json
{
  "page": {"grade_guess": 2, "subject_guess": "numeracy", "legible": true},
  "questions": [
    {"idx": 1, "printed": "52 − 28 =", "student_answer": "36", "student_work_visible": true,
     "checkpoint_id": "N.G2.sub_2digit_borrow", "self_verdict": "incorrect",
     "mistake_pattern": "smaller_minus_larger", "confidence": 0.9},
    {"idx": 2, "printed": "34 + 25 =", "student_answer": "59", "checkpoint_id": "N.G2.add_2digit_carry",
     "self_verdict": "correct", "confidence": 0.95}
  ],
  "page_confidence": 0.87,
  "unreadable": [3]
}
```
**Code checks (critical):**
- If `printed` and `student_answer` parse as an arithmetic expression, **recompute in Python**. If the model's verdict disagrees with arithmetic, arithmetic wins and the disagreement is logged.
- If arithmetic cannot be parsed, keep `self_verdict` but confidence is multiplied by 0.8 and the item is shown with a ? chip.
- If `page_confidence < 0.6` or `legible=false` → return "please retake" with guidance (hold phone above page, good light), no auto evidence.
- Grade/subject mismatch with roster → warn teacher.
**Aggregation to evidence:** per checkpoint, score = correct_items / items; result = correct if score ≥ 0.8, partial if ≥ 0.4, else incorrect; confidence = mean(item conf) × min(1, items/3).
**Cost:** ~2k in (image tokens) / 800 out → ≈ $0.006.

### A3 · Classroom voice → checkpoint evidence

**Goal:** separate *acoustic* pronunciation from *language* comprehension, and turn both into evidence.

```
Teacher picks: child, checkpoint (or "recommend"), target items (words to read, or prompts+expected answers)
Audio ──▶ Sarvam ASR (keyterms = targets + name) ──▶ transcript + word timings
Transcript + audio features ──▶ Deterministic scorer (§5) ──▶ per-item {correct|close|wrong|omitted, score, detail}
Scores + checkpoint ──▶ Claude (Haiku) ──▶ {checkpoint verdict, misconception?, confidence, quote}
   (Claude does NOT re-score pronunciation; it maps the session to what the checkpoint tests,
    e.g., "child read 'कलम' for 'कमल' — matra/letter-order confusion → L.G1.vyanjan vs L.G1.matra_basic")
Teacher confirm ──▶ evidence
```
**Output schema:** `{checkpoint_id, result, misconception?, confidence, per_item:[{item, judged, note_hi}], note_for_teacher_hi}`.
**Guardrails:**
- If ASR confidence for most words < 0.5 or SNR estimate is very low → return `low_audio_quality`; the app re-prompts for a quieter take; **no evidence** is proposed.
- Never propose `on_track` from a single noisy clip; max evidence weight at 0.8.

### A4 · Index photo → roadmap draft

**Input:** image of contents/index page, subject, grade.
**Output schema:** `{chapters:[{title_hi, subtopics:[{text, kind:"topic"|"question"|"page_ref"}]}], confidence, notes}`
**Code:** drop page refs; merge duplicates; map to graph checkpoints (same subject, grade ±1) with fuzzy+embedding similarity; unmatched → custom drafts. Validate 5–60 checkpoints, ≥ 2 chapters.
**Cost:** ~1.8k in / 1k out → ≈ $0.007 (once per class-subject).

### A5 · Guided probe script (P2)

**Input:** child's recent evidence on a checkpoint, misconception candidates, probe type (`concept_vs_language`, `misconception_check`).
**Output:** `{intro_hi, items:[{ask_hi, expected, pass_if}], pass_rule, what_it_tells_teacher_hi}` — max 5 items, each ≤ 1 sentence, using only vocabulary from the checkpoint's grade band.
**Code checks:** items count; vocabulary check against a grade-level word list (allow target words); route only to checkpoints with a probe template.
**Cost:** ~1.2k in / 500 out ≈ $0.002.

### A6 · Misconception hypothesis

**Input:** last 6 evidences for (child, checkpoint) with quotes; misconception taxonomy of the checkpoint.
**Output:** `{hypotheses:[{misconception_id, summary_hi, evidence_refs:[ids], confidence}]}` — requires ≥ 2 evidence refs; empty if not.
**Code checks:** ids in taxonomy; every ref exists and is incorrect/partial; confidence capped at 0.7 unless ≥ 4 refs.
**Cost:** ≈ $0.003.

### A7 · Intervention plan (the flagship call)

**Input:**
- Class context: grade, subject, number of children, today.
- Groups (computed by code): `[{key, checkpoint_id, children:[{R..}], size, priority_band}]`.
- **Candidate activities per group** (code-filtered from the reviewed library): id, title_hi, steps_hi, materials_hi, duration, blackboard, reassessment_item — only reviewed items, matching checkpoint or adjacent prereq, ≤ 10 min each.
- Pacing note (chapter the class is on).
- Constraints: total teacher time ≤ 25 min for all groups; one activity per group by default; must not require a printer; blackboard version mandatory.

**Output schema:**
```json
{
  "subject": "numeracy",
  "date": "2026-10-29",
  "groups": [
    {"key": "N.G2.sub_2digit_borrow",
     "activity_id": "act_borrow_sticks",
     "why_hi": "इन बच्चों ने उधार लेने पर गलती की — सींकों से दिखाएँ।",
     "teacher_script_hi": "पहले 52 − 28 बोर्ड पर लिखें...</br>",
     "time_min": 8,
     "order": 1,
     "reassessment": {"ask_hi": "63 − 27 = ?", "expected": "36"}
    }
  ],
  "whole_class_note_hi": "आधार निर्धारण बाकी बच्चों से 3 सवाल पूछें।",
  "today_observation_to_collect_hi": "..."
}
```
**Validator (`plan_rules.py`):**
1. Every `activity_id` ∈ candidates for that group (not just the library).
2. `time_min` ≤ activity duration; Σ time ≤ 25.
3. `reassessment.expected` must be verified for arithmetic in code.
4. `teacher_script_hi` length ≤ 600 chars; language = Hindi; no numbers that contradict the activity steps (regex check of numbers vs. steps).
5. Every group in input must appear exactly once.
→ On failure: retry once with the validator errors; then **template plan**.

**Template plan (fallback):** for each gap type in the taxonomy, a hand-authored, mentor-reviewed activity + script (e.g., borrowing with sticks) stored in `content/templates/`. Deterministic merge into the same output schema. This means the flagship feature is *always* available, even offline.

**Cost:** ~4k in / 1.2k out → ≈ $0.03 per plan (once/twice a day per class).

### A8 · Home → teacher summary

**Input:** last night's session facts (activities, judged outcomes, focus) for one child. **Output:** ≤ 3 lines Hindi, e.g. "राहुल ने घर पर 8 गतिविधियाँ कीं। 'कमल' जैसे शब्दों में मात्रा अभी कठिन है — कक्षा में एक बार दोहराएँ।"
**Code checks:** no scores shown; ≤ 3 lines; facts limited to session data (no extrapolation); template fallback per activity type.

### A9–A10 · Parent tutor session (see [03 §5](03_DOMAIN_AND_DESIGN.md#5-parent-app--voice-tutor-design))

**Harness controls the path.** Claude's role per activity:
1. `INTRO` — rewrite the pack's fixed intro with today's focus (≤ 30 words).
2. `FEEDBACK` — given `{target, child_transcript, judged, attempt_no}`, produce one warm sentence + one concrete hint (Hindi, grade 1–2 vocabulary).
3. `WRAP` — 2 sentences.

**Turn I/O:**
```
POST /parent/sessions/{id}/turn   audio(turn)
server: ASR → judge(turn, activity) → if wrong and attempt<2: Claude FEEDBACK (with hint) → TTS
                                    if correct: Claude praise (short) → next activity prompt (fixed text + TTS)
                                    if attempt=2 wrong: Claude gentle comfort → record → next
```
**Prompt rules:** child persona, ≤ 2 sentences, grade-1 vocabulary band, no questions about self/family/location, blocklisted topics (violence, relationships, money, other media/ads), never evaluate the child as a person ("तुम कमज़ोर हो" forbidden), no English words unless the item is English.
**Safety A10:** classify each child transcript for distress/abuse/grooming signals → any trigger ⇒ fixed card + parent alert in session summary; classifier failures ⇒ safe path.
**Cost per session:** ~8 activities × 2 Claude turns × (0.8k in / 80 out) + ASR ≈ $0.01–0.02 in Claude + ASR/TTS per-minute. Cap: 60 Claude turns/session.

### A11–A12 · Offline authoring (batch, not in app)

- **Practice items:** per checkpoint, generate 15 candidate items (target, 3 distractors, picture suggestion, difficulty tier) → auto-validate (target ∈ word list / arithmetic correctness / distractor ≠ target) → human edit pass → `reviewed=true`.
- **Probe scripts** and **activity drafts**: generated from NIPUN Lakshya + handbook snippets (RAG) → education mentor review → `reviewed=true`.
- Generated content is **never** trusted at runtime unless `reviewed=true`.

### A13 · RAG

- Corpus: NIPUN Bharat Lakshya text, TEJASVI/NCERT teacher-handbook excerpts (Hindi + English), the reviewed activity library, the competency graph descriptions.
- Index: pgvector with chunk ~400 tokens, metadata `{source_doc, page, subject, grade, language}`.
- Retrieval: hybrid (BM25 lexical + vector) filtered by subject/grade; top-6 into planner & misconception calls; each snippet carries `source_doc, page` so the plan can show "स्रोत: NIPUN Lakshya" / "Activity from TEJASVI p.42".
- Embedding model: a multilingual embedding model hosted by the provider or a local small multilingual model (e.g., a sentence-transformers multilingual model) — chosen in build based on eval of lexical recall on Hindi checkpoint titles.

---

## 5. Pronunciation & reading scorer (deterministic)

**Input:** transcript with word timings (ASR), target text (words or number words), language.
**Steps:**
1. **Normalise** both: Devanagari normalisation (NFC, nukta handling, common spelling variants), digits → number words (hi), filler-word removal.
2. **Align**: token-level sequence alignment (Wagner–Fischer / `Levenshtein` with custom cost) between expected tokens and transcript tokens; map words by position.
3. **Score per item:**
   - `correct` — aligned to an expected token, normalised string equality (or high similarity ≥ 0.9 if ASR spelling noise is likely), ASR confidence ≥ threshold.
   - `close` — similarity 0.6–0.9 (e.g. a matra error: "कलम" vs "कमल") → flagged with the differing graphemes.
   - `wrong` — low similarity or wrong word.
   - `omitted` / `inserted` — from alignment.
4. **Optional phoneme layer:** if a Devanagari G2P is available (e.g., indic-tools / espeak-ng hi), compare phoneme sequences to report *which sound* (स/श, न/ण, short/long vowel, aspirated/unaspirated) — used only as a hint to the teacher, never as the verdict.
5. **Fluency (for longer reading):** WCPM from word timings; self-correction detection from repeated tokens.
**Calibration:** thresholds are set on the eval set against human ratings; thresholds stored as config with version.
**Why not LLM-as-judge for pronunciation:** inconsistent, no timing, unverifiable; an LLM reading a transcript cannot hear a mispronounced word if ASR "corrects" it — so ASR confidence and constrained targets matter more than model cleverness.

---

## 6. Batch content generation (offline jobs)

| Job | Input | Output | Human gate |
|---|---|---|---|
| Practice item generation | checkpoint + word list + sample items | candidates | Teacher/mentor review |
| Activity drafts | handbook snippet + checkpoint | activities | Education mentor review |
| Probe scripts | checkpoint family | scripts | Education mentor review |
| Misconception taxonomy expansion | failures from eval | candidates | Mentor review |

Runtime never generates new activities or items; it only selects, orders and explains.

---

## 7. Cost model (per active class per day)

| Call | Count/day | Unit cost | Daily |
|---|---|---|---|
| A1 note | 1 | $0.003 | $0.003 |
| A2 photo | 3 | $0.006 | $0.018 |
| A3 voice | 3 | $0.004 + ASR $0.002 | $0.018 |
| A7 plan | 1 | $0.03 | $0.030 |
| A6 hypothesis | 2 | $0.003 | $0.006 |
| A8 summary | 2 | $0.002 | $0.004 |
| **Teacher subtotal** | | | **≈ $0.08/day/class (≈ ₹7)** |
| A9 tutor (per child session) | 30–60 turns | $0.010–0.020 | $0.015/child/day |

**Monthly estimate:** 1 school, 10 classes, 300 children, 20 school days: teacher ≈ $16 + home sessions (if 100 children × 15 days) ≈ $22 ⇒ **≈ $38/school/month + ASR/TTS**. With prompt caching, target ≤ 60% of this. Budget guards: per-school daily cap, admission-control queue, and a visible "AI budget" setting.

---

## 8. AI-specific guardrails summary

| Risk | Guardrail |
|---|---|
| Wrong child attribution | Roster-constrained names; fuzzy match with ambiguity → teacher picks; wrong-attribution metric in eval |
| Wrong arithmetic | Code recomputation overrides the model on all numeric verdicts; reassessment answers arithmetic-verified |
| Hallucinated activities | Closed library; validator; template fallback; "reviewed" flag |
| Hallucinated curriculum | Roadmap needs teacher confirm; graph edges are human-authored |
| Over-easy confirmation | Home evidence capped; recency rules; no auto on_track from one session |
| Tutor unsafe output | A10 classifier, output validator, fixed fallback lines, red-team suite in CI |
| Private data in prompts | Tokenised names for planner; no surnames/DOB/photos of faces; no child location |
| Model drift / outage | Model pinned; `ai_degraded` flag; deterministic fallbacks; cached plan |
| Prompt injection through OCR/ASR text | All user text is treated as data, wrapped in delimiters, and the model is instructed that page text/transcripts are quoted content, not instructions; injection test suite |
