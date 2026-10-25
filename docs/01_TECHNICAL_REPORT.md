# 01 · Technical Report

> Kaksha Saathi — a continuous learning-gap and intervention system for Indian primary classrooms.
> Technical report for the Build stage (submission 1 Nov 2026). Design-only document.

---

## 1. Executive summary

**Problem.** A primary teacher in a low-fee or government school has 30–35 children, often across 2–3 grades, with intermittent attendance and varying home languages. Textbook pacing compels "teaching to the middle"; the teacher cannot tell *which* child is stuck on *which* sub-skill, nor keep that knowledge across days. Prior work (J-PAL's Teaching at the Right Level, ASER) shows that assessment and **grouping by level** matters, but assessment today is periodic, paper-based, and rarely turned into per-group action.

**Solution.** One system, two surfaces:
- **Teacher app (Android/web):** roadmap from an index photo → fast evidence capture (written-work photo, classroom voice, tap checklist, voice note) → an always-current per-child learning map → automatic classroom grouping → a concrete, reviewed intervention plan per group → reassessment.
- **Parent app (Android/web, voice-first):** the same learning map selects what the child practises at home; a structured, AI-led 30-minute voice tutor session; home evidence returns to the map.

**The technical bet.** The hard problems are (a) turning noisy, low-effort inputs into reliable structured evidence, (b) deciding mastery deterministically, and (c) generating interventions that are pedagogically sound for a 30-child group, not just plausible text. Kaksha Saathi resolves each with a different mechanism: **structured-output LLM extraction with teacher confirmation**, a **deterministic mastery engine over a prerequisite graph**, and a **grounded planner that can only choose from a human-reviewed activity library**, with code validation and a rule-based fallback. That is a *reasoning harness*, not a prompt — which is what the hackathon's tech guidance explicitly evaluates.

**What is genuinely novel.** Existing tools do one of: oral reading fluency ("PadhAI", DIBELS-style apps), lesson plans, home-learning WhatsApp bots (Rocket Learning), or class-level dashboards. None carries a **child-level, prerequisite-aware learning map across school days, classroom voice evidence and home practice**, and none turns that into **group interventions the same teacher can run the next period**. The closest competitor (education consultants' approach) is TaRL done by hand — which Kaksha Saathi operationalises for a single teacher's phone.

**Main risks.** Child speech accuracy in noisy classrooms; the teacher's confirmation burden (if too heavy, nobody uses it); scope (the spec describes a large system); and child-data compliance. Each has a designed response (§7).

---

## 2. The problem, as an engineering problem

### 2.1 What the teacher actually has (constraints)

| Constraint | Evidence | Implication for the design |
|---|---|---|
| Device: personal Android smartphone, often 2–4 GB RAM, Android 8–12 | BaSE 2025: 98% of teachers own smartphones | Android-first, light UI, no heavy on-device ML |
| Connectivity: 63.5% of schools have no internet (the teacher's data connection is intermittent) | BaSE 2025 | All capture works offline; AI steps are queued; parent sessions downloadable |
| Time: ~30–40 min of actual class time per section; 20–42% of teacher time on non-teaching work | CSF reports | Interaction budget for the teacher is **≤ 2 minutes per assessment**, ≤ 1 minute for the daily plan review |
| Existing load: daily attendance, exams, forms | Challenge key messages | No new *forms*. Evidence capture must reuse what the teacher already does (marking notebooks, asking a child to read). |
| Trust: teachers fear surveillance | UP digital-attendance protests (2024) | No scoring of teaching, no per-teacher dashboards, no mandatory daily entry; data is owned by the teacher (export/delete) |
| Privacy: child data under DPDP Act 2023 + DPDP Rules 2025 | Medianama / rules | Parent consent, verifiable parental consent for under-18s, purpose limitation, no photos of faces, no behavioural tracking, minimisation |

### 2.2 What the child's evidence looks like

- **Written work:** photograph of an open notebook page or a single exercise. Handwriting is a child's; page is sometimes rotated, shadowed, low-contrast pencil.
- **Classroom voice:** 5–20 s of a 6–9-year-old reading or answering, recorded on the teacher's phone with classroom noise, other children, the teacher's prompts mixed in.
- **Teacher taps/voice:** the teacher's own observations. Fast, subjective but trusted.
- **Home voice (parent app):** slightly cleaner but younger-child speech and background noise.

The system must handle *all four* as evidence for the same checkpoints, with source-dependent trust weights.

### 2.3 The core model

```
Roadmap (class × subject)  =  ordered checkpoints, each with prerequisites
Evidence (append-only)     =  {child, checkpoint, result ∈ {correct, partial, incorrect, unattempted},
                               misconception?, source ∈ {photo_work, class_voice, teacher_tap, teacher_note,
                               guided_probe, home_voice, home_tap}, confidence, at}
Mastery (derived)          =  f(evidence, recency, source weight)  →  status + confidence + history
Gap                        =  checkpoint not on-track AND prerequisites on-track  (foundational gap = walk
                               prereqs even if the prerequisites themselves show partial evidence)
Group                      =  students sharing the same top gap (subject-wise)
Intervention               =  reviewed activity(ies) + teacher script + blackboard version + reassessment item
```

Everything else in the product is a view over these five things.

---

## 3. System overview

```
┌────────────────────────┐        ┌──────────────────────────────┐        ┌─────────────────────────────┐
│ TEACHER APP            │        │ PARENT APP                   │        │ (out of scope)               │
│ Flutter · Android+Web  │        │ Flutter Web · Android webview│        │ CRP / school head view       │
└───────────┬────────────┘        └──────────────┬───────────────┘        └─────────────────────────────┘
            │ HTTPS (queued, offline outbox)     │ HTTPS + cached packs
            ▼                                    ▼
┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ API LAYER — FastAPI (Python 3.12)                                                                      │
│  auth · roster · roadmap · evidence · mastery · grouping · interventions · parent sessions · export   │
└───────────┬───────────────────────────────────────────────────────────────────────────────────────────┘
            │
  ┌─────────┴─────────────┬─────────────────────┬──────────────────────┬───────────────────────┐
  ▼                       ▼                     ▼                      ▼                       ▼
┌──────────────┐   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│ MASTERY      │   │ AI ORCHESTRATOR  │  │ SPEECH SERVICE   │  │ CONTENT (intl.       │  │ STORAGE          │
│ ENGINE       │   │ (Claude via      │  │ (Sarvam / Gemini │  │ library, reviewed)   │  │ Postgres + RLS   │
│ pure Python  │   │  Anthropic API)  │  │  native audio)   │  │ graph, activities,   │  │ pgvector (RAG)   │
│ + PrereqGraph│   │ structured out,  │  │ Indian-language  │  │ items, packs         │  │ Object store     │
│              │   │ validation,     │  │ ASR + scoring    │  │                      │  │ (photos TTL)     │
│              │   │ retries, cost    │  │ + TTS            │  │                      │  │ Audio: never kept │
└──────────────┘   └──────────────────┘  └──────────────────┘  └──────────────────────┘  └──────────────────┘
```

Full detail: [02_ARCHITECTURE.md](02_ARCHITECTURE.md).

---

## 4. AI usage map (what is AI, what is code)

| Function | Mechanism | Why not the other way |
|---|---|---|
| Roadmap from index photo | Claude vision → draft chapter/checkpoint tree (structure only) | OCR alone can't rank "Borrowing" under "Subtraction"; but the *prerequisites* come from our graph, not the model |
| Written-work analysis | Claude vision → per-question `{question, student_answer, correct?, misconception}` mapped to roadmap checkpoints | A child's handwriting + partial mapping needs semantic judgement (which checkpoint does this exercise belong to) |
| Classroom voice | ASR → Claude judges *which checkpoint* the transcript evidences → speech scorer (see below) scores pronunciation/fluency | Claude reading a raw transcript cannot hear pronunciation — that must be acoustic. Claude assigns meaning and maps to checkpoints. |
| Pronunciation / reading accuracy | Deterministic scorer against the known target text (grapheme/phoneme alignment when phonemisation available; constrained word-diff otherwise); Claude only *interprets* the score into evidence | LLM-based pronunciation judgement is inconsistent and unauditable |
| Teacher voice note | ASR → Claude → structured "I taught X; A absent; B struggled with Y" | Free text is what teachers produce |
| Guided probe scripts | Claude writes the probe questions; teacher reads them aloud | Personalised, cheap; human-delivered = safe |
| Mastery status | Deterministic EMA + rules over evidence | Reproducible, explainable to the teacher, no hallucination |
| Grouping | Deterministic clustering by top gap, prerequisite-aware | Explainable; model may group arbitrarily |
| Intervention plan | Claude **selects** from reviewed activity library + writes teacher script & blackboard version; code validates references, durations, group membership | Prevents invented activities; keeps pedagogy human-reviewed. **Fallback:** deterministic template plan per gap type |
| Parent session | **Harness** runs the activity sequence; Claude generates prompts, feedback, gentle corrections per activity; code decides correctness (ASR vs target text), coverage, retries, exits | Guardrails for child-safe dialogue; bounded cost; measurable outcomes |
| Parent → teacher summary | Claude writes a 3-line "what we practised at home" note in the teacher's terms | Teacher reads faster than raw logs |
| RAG grounding | pgvector over NIPUN Lakshyas, NCERT/TEJASVI handbook excerpts, reviewed activities | Grounded terminology + citation to source |

Full detail: [04_AI_SPECIFICATION.md](04_AI_SPECIFICATION.md).

---

## 5. Differentiators (positioning vs. existing tools)

| Existing category | Examples | What it does | What Kaksha Saathi adds |
|---|---|---|---|
| Oral reading fluency apps | PadhAI (compendium), ASER-style ORF tools, Fluency Tutor | Scores a child reading aloud | Learning *other* skills too (numeracy, matras, word formation) and feeding a persistent map that drives grouping and intervention |
| Home-learning bots | Rocket Learning, Chimple, Top Parent | Sends daily WhatsApp activities, tracks completion | Personalised to *this* child's confirmed school gap, with a voice tutor that listens and judges attempts, not just sends content |
| Level-based teaching | TaRL as implemented by Pratham | Teachers regroup children by level | Operates at the sub-skill/misconception granularity ("borrowing", not "subtraction"), across school *and* home, on one teacher's phone |
| Dashboards | Vidya Samiksha Kendra state dashboards | Aggregate data for officials | Child-and-teacher level; designed to be acted on by the person teaching tomorrow |
| Lesson-plan generators | Many LLMs apps | Generates a lesson plan | Generates the plan **for a specific group with a specific gap**, grounded in reviewed activities, then closes the loop with reassessment |

**The defensible core** is the evidence → mastery → gap → group → intervention → reassessment loop, which no single existing tool covers end-to-end.

---

## 6. Novel technical elements

1. **Source-weighted, confidence-aware mastery** (§ [03 §4](03_DOMAIN_AND_DESIGN.md)): not a simple correct/incorrect count. A confident photo analysis of five borrowing problems outweighs one uncertain classroom-voice read. Home evidence is capped below teacher confirmation.
2. **Prerequisite inference for foundational gaps**: if a child fails `borrow` and also fails `no_borrow`, the group is formed at `no_borrow` (or lower) — the *most foundational* failing point with passing prerequisites — not at the grade-level topic. This operationalises TaRL's core insight automatically.
3. **Constrained planner with deterministic fallback**: Claude never invents an activity; it maps a gap to reviewed library items and writes the teacher script. If the LLM fails or output is invalid, a template plan (written by the team, mentor-reviewed) is served. That makes the feature reliably available even offline.
4. **Listening tutor harness**: the parent session is a state machine (activity → prompt → child attempt → judge → feedback/retry → next) where Claude writes the *language* and the harness controls the *path* and *stop rules* — avoiding the failure modes of free-form child AI chat and bounding cost.
5. **Two-tier offline**: teacher capture is fully offline (outbox queue); parent sessions run from a pre-downloaded pack with a tap-only fallback if ASR/AI is unavailable, and sync evidence later.
6. **Built-in evaluation**: golden sets, kappa-based agreement with teachers, hallucination audits and a live "unverified AI proposals" counter in the teacher app — evaluation is a product feature, not a report.

---

## 7. Key risks and mitigations (summary)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Child ASR accuracy in noise is too low for pronunciation grading | High | Score only against *known* target words; show confidence; treat low-confidence as *unattempted* not *wrong*; teacher confirm; tap fallback at home; published eval numbers |
| R2 | Photo of a child's notebook is misread → wrong status | High | Teacher confirm screen with per-question edit; status changes only after confirmation; "needs review" state; no auto move to on_track |
| R3 | Teacher burden → abandonment | High | One-tap checklist as the default path; 2-minute photo flow; no extra testing; teacher can skip any AI suggestion |
| R4 | Parent home use is low (parents busy, low literacy) | Medium | Voice-first UI, 2-tap start, child can start after parent unlocks; weekly milestone nudge as an audio message, not text |
| R5 | Scope too large for 9 days | High | Phase plan (§[06](06_BUILD_PLAN.md)); P0 = teacher loop end-to-end; P1 = home session; P2 = probes; ship frozen on time |
| R6 | Child-data compliance (DPDP, verifiable parental consent) | High (legal) | Consent flow at onboarding via teacher with parent-signed form; data minimisation; deletion API; no audio retention; privacy note in both apps |
| R7 | LLM cost during demo/evaluation | Low | Haiku-class for extraction, Sonnet-class for planning/tutor; caching; caps per class/day; cost table in [04 §7](04_AI_SPECIFICATION.md) |
| R8 | Demo dependency on Anthropic API during judging | Medium | Cached demo pack with recorded AI outputs replayed through the real harness when offline; honest label "cached model output" |
| R9 | Syllabus mismatch across states/boards | Medium | Roadmap is editable; graph is NIPUN Bharat, any board can map onto it |
| R10 | Multilingual children (home language ≠ school language) misdiagnosed | Medium | Probe feature (P2): a short concept-vs-language check when a child fails repeatedly on a listening-heavy checkpoint; language-aware tutor |

Full register: [07_RISKS_AND_DECISIONS.md](07_RISKS_AND_DECISIONS.md).

---

## 8. Evaluation summary

| Layer | Method | Target |
|---|---|---|
| Extraction (notes, photos) | Golden set of 60+ teacher notes / 40+ notebook photos, double-annotated | Child-event F1 ≥ 0.90; wrong-child attribution ≤ 2% |
| Misconception tagging | Expert labels on 100 incorrect answers | Cohen's κ vs. education mentor ≥ 0.6 |
| Roadmap draft | 15 index photos × 3 subjects | ≥ 80% of checkpoints retained after teacher edit; no missing chapter |
| Planner | 40 gap scenarios checked by an education mentor | ≥ 90% plans use only appropriate library activities; 0 invalid references |
| Tutor | 25 simulated/real child sessions (incl. Hindi speakers, noise) | Correctness decisions agree with human rater ≥ 85%; 0 unsafe responses in red-team suite |
| End-to-end pilot | 3–5 teachers, 1 class each, ≥ 3 days (if possible), or usability session with teachers | Time-to-capture ≤ 2 min; teacher-reported usefulness ≥ 4/5; ≥ 80% plans rated "actionable" |

Details and data-collection plan: [05_EVALUATION_PLAN.md](05_EVALUATION_PLAN.md).

---

## 9. Deliverables for 1 November

- Hosted web demo (teacher + parent) with demo accounts and seeded fictional class.
- APK with install instructions (teacher app; mic recording).
- GitHub repo: no secrets; README; `.env.example`; 3–5 sample inputs (notes, notebook photos, audio clips, parent session).
- 3-minute video; deck with architecture layers, guardrails, offline story, user inputs/testing, roadmap, and this documentation set condensed.

---

## 10. Limitations (stated honestly)

- Tested in design/plan with education input; field validation pending teacher pilots.
- Hindi is the only fully supported language for voice checkpoints; numeracy is language-neutral; other scripts typed manually.
- Photo analysis is online-only.
- Pronunciation scoring uses word-level constraints; phoneme-level feedback quality depends on phonemisation availability for the language.
- Mastery thresholds are initial values calibrated on eval data, not long-term longitudinal study.
- No official integration with state systems in this build; roadmap for integration is in [06 §7](06_BUILD_PLAN.md).
