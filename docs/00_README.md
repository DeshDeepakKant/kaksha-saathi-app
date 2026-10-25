# Kaksha Saathi — Technical Documentation Set

**Input:** the "Final Problem & Solution" spec + hackathon guidelines, evaluation guidance, challenge key messages and the 2026 India AI for Education compendium.
**Status:** designed **and built**. The working code is in this repository — see the root
[`README.md`](../README.md) for setup, demo credentials, screenshots and the offline matrix.

| Where | What |
|---|---|
| `backend/` | FastAPI API: mastery engine, grouping, plans, AI orchestration, speech, parent session harness |
| `apps/teacher/`, `apps/parent/` | The two Flutter apps (Android + Web) |
| `content/` | competency graph, reviewed activity library, practice items, probes |
| `evals/` | runnable harnesses + golden sets; current numbers in [EVAL_RESULTS.md](EVAL_RESULTS.md) |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | 3-minute video storyboard |
| [DEPLOY.md](DEPLOY.md) | freezing the demo for evaluation |
| [user_inputs.md](user_inputs.md) | the feedback log the submission asks for |

**Scope:** Both apps (Teacher + Parent), a shared backend, AI pipelines, data model, prompt design,
evaluation / guardrails, connectivity strategy, DPDP-aligned child-data handling, and the build plan
with acceptance criteria.

---

## How the documents fit together

| # | Document | What it answers | Primary readers |
|---|---|---|---|
| 01 | [Technical Report](01_TECHNICAL_REPORT.md) | What we're building, why, what's hard, what the risks are, what must change vs. the spec | Judges, mentors, team |
| 02 | [Architecture](02_ARCHITECTURE.md) | Services, deployment, data flow, AI orchestration, model choices, offline/sync design | Engineers, tech mentor, judges |
| 03 | [Domain & Design](03_DOMAIN_AND_DESIGN.md) | Curriculum graph, checkpoints, evidence→mastery rules, grouping algorithm, parent-session design, UX for both apps, data model | Engineers, education mentor, design |
| 04 | [AI Specification](04_AI_SPECIFICATION.md) | Every AI call: input, output schema, model, prompt strategy, guardrails, failure behaviour, cost | Engineers, AI mentor, judges |
| 05 | [Evaluation Plan](05_EVALUATION_PLAN.md) | Golden sets, metrics, offline harness, pilot protocol, judging-metric mapping | Engineers, education mentor |
| 06 | [Build Plan](06_BUILD_PLAN.md) | Day-by-day plan to 1 Nov, backlog, team split, definition of done, submission checklist | Team |
| 07 | [Risks & Decisions](07_RISKS_AND_DECISIONS.md) | Risk register, open decisions with recommendations, spec-interpretation disputes | Whole team |

Suggested reading order for a newcomer: **01 → 03 (sections 1–3) → 02 → run the app (README) → 06**.

---

## The design in one page

Kaksha Saathi keeps **one child-level learning map** that both apps read and write.

```
TEACHER APP                                                  PARENT APP
─────────                                                    ──────────
Roadmap builder (index photo → editable checklist)           Roster-child → daily voice tutor
Assessment capture:                                          Progress + history (voice-first)
  • written work photo → per-question correctness            Homework "proof" (photo/audio)
  • classroom voice → pronunciation/reading evidence
  • tap checklist / teacher voice note
        │                                                            ▲
        └───────────────►  EVIDENCE  ◄──────────── home practice evidence
                             │   (append-only, every row = child × checkpoint × result × source)
                             ▼
                    MASTERY ENGINE (deterministic code)
                    EMA of evidence → status (not_started / needs_intervention / needs_practice / on_track)
                             │
              ┌──────────────┴───────────────┐
              ▼                              ▼
      GROUPING (code) + INTERVENTION   PRACTICE TARGETING (code)
      (Claude picks from reviewed      → "next 3 things to practise"
       activity library + rubric copy)
              │                              │
              ▼                              ▼
      Classroom board / action card    Daily 30-min tutor session
      → intervention → REASSESS        (Claude dialogues; code judges accuracy,
              │                         coverage, exit rules)
              └──────────────► new evidence ◄──────────────────────┘
```

**Design principles**

1. **AI extracts and explains; code decides and counts.** Mastery status, grouping, correctness numbers, WCPM and pronunciation scores come from deterministic code. Claude reads messy inputs (notes, photos, speech transcripts), proposes interpretations the teacher can override, picks interventions from a human-reviewed library, and writes the copy for both apps.
2. **Every AI output is a proposal with a human confirm step.** The teacher confirms roadmap structure, assessment results, voice assessments and interventions. Auto-accepted paths exist only after measured accuracy on the eval set.
3. **Works on a ₹8–15k Android phone with 2G/no signal.** Teacher capture works offline (queued). Parent sessions run from a downloaded pack, with a **tap fallback** when the AI is unreachable.
4. **Child data minimisation by construction.** First name + roll number only. No photos of faces, no stored audio, no birth dates. Names are stripped before tutor calls (the tutor uses spoken given names only because it must address the child — this is logged and consented).
5. **The roadmap is built once and reused.** One index photo per class-subject, reviewed once, serves 30 children and is shared across sections where the syllabus is the same.

---

## What has changed from `Kaksha_Saathi_Final_Problem_and_Solution.md`

These are deliberate, evidence-driven revisions — see [07_RISKS_AND_DECISIONS.md](07_RISKS_AND_DECISIONS.md) §3 for the reasoning.

| Spec says | Build says | Why |
|---|---|---|
| Parent app has a 30-minute voice AI tutor conversation | Parent "30-minute session" is a **structured activity sequence** of 6–10 short activities, AI-led, with code-controlled progress and exit rules | Long free-form child↔AI conversation is pedagogically and technically risky (child-safe guardrails, cost, drift). A structured session is safer, measurable and cheaper. |
| Teacher app provides a full curriculum map from an index photo | Photo produces a **draft** checklist (chapters → checkpoints); teacher edits and confirms. Competency prerequisites come from a pre-built, mentor-reviewed graph (NIPUN Bharat), not from the photo | Index pages rarely name sub-concepts. Prerequisite edges must be trusted, not guessed. |
| Parent app gets "the student's current priority" from the teacher app | Confirmed gaps are the primary source; **daily session evidence can also create practice flags** so a child keeps practising even if the teacher hasn't confirmed yet | Home practice must not stall waiting for a teacher update. |
| Home practice feeds "reassessment" | Home evidence is recorded with `source=home` and **does not move a checklist item above "needs practice"** without teacher confirmation | Prevents sycophantic/unreliable AI grading from inflating school-side status. |
| Parent app sees "sessions, subjects, activities, progress" | Parent sees **effort + what was practised + practice streak**; accuracy trend is hidden behind a "view detail" for the teacher only | Keeps parent app non-competitive and simple. |

---

## Out of scope for the 1 November build

- Multi-school / multi-teacher shared rosters, school SSO (single teacher account with invite code).
- Offline handwriting *recognition* of student notebooks (photo analysis is online-only).
- Other Indian languages beyond **Hindi** (numeracy content is language-neutral; architecture is language-tagged so Marathi/Assamese can be added).
- OCR of the *textbook index in regional scripts beyond Hindi* (Hindi index supported; others typed manually).
- District/CRP roll-up dashboards.
- Play Store distribution (web + APK link only).

---

## Glossary

| Term | Meaning |
|---|---|
| **Checkpoint** | A single assessable learning sub-goal, e.g. "2-digit subtraction with borrowing", "reads words with आ/इ matras". The unit everything is tracked against. |
| **Roadmap** | Ordered list of checkpoints for a class + subject, organized into chapters. |
| **Evidence** | One row: child × checkpoint × result × source × date. The raw fact. |
| **Mastery status** | Derived status per child × checkpoint: `not_started`, `needs_intervention`, `needs_practice`, `on_track`. |
| **Learning profile** | A child's roadmap with all statuses + history. |
| **Gap** | A checkpoint whose status is `needs_intervention` or `needs_practice` and whose prerequisites are on track. |
| **Group** | Students with the same top gap in a subject — the classroom's unit of intervention. |
| **Intervention** | A reviewed classroom activity (from the library) + steps + reassessment question, for one group. |
| **Practice item** | A short home activity (word list, pronunciation prompt, number task) in the child's daily session. |
| **Probe** | A quick assessment to separate two hypotheses (e.g. concept vs. language). |
| **NIPUN Bharat** | MoE (2021) foundational literacy & numeracy mission with grade-level Lakshyas — anchor for our competency graph. |
