# 07 · Risks & Decisions

---

## 1. Risk register

Scoring: Likelihood (L) and Impact (I) on a 1–5 scale; Score = L × I. Anything ≥ 12 needs an owner and a built mitigation (not a slide).

| ID | Risk | L | I | Score | Mitigation (built, not aspirational) | Fallback if mitigation fails |
|---|---|---|---|---|---|---|
| R1 | Child speech recognition too poor in noisy classrooms → unreliable pronunciation evidence | 4 | 5 | 20 | Score only against known targets; ASR confidence gating; low-quality ⇒ "retake", never guess; teacher confirms | Tap-based checkpoints (matra/word-order via taps) for the same concept |
| R2 | Notebook photo misread → wrong profile | 3 | 5 | 15 | Arithmetic recompute in code; per-question confidence; always teacher-confirmed; `?` chips; retake guidance | Manual per-question ✓/✗ on the photo |
| R3 | Teacher confirmation burden → abandonment | 4 | 4 | 16 | Tap checklist as zero-AI path; every AI path ≤ 2 min; proposals pre-filled; offline; no new forms | Ship tap-first; AI is an accelerator only |
| R4 | Roadmap photo doesn't map to checkpoints | 3 | 3 | 9 | Draft-only; code matching + template fallback; teacher edit | Grade template start |
| R5 | Planner produces unusable plans | 3 | 4 | 12 | Closed library; validator; rubric eval; template fallback | Always-available template plans |
| R6 | Home sessions not used (parents busy / low literacy) | 3 | 4 | 12 | Voice-first, 2 taps, no install (PWA), offline pack, audio instructions, milestone audio nudge | Teacher-led in-class practice using the same items |
| R7 | Scope overrun; features half-done at deadline | 4 | 5 | 20 | P0/P1/P2 plan; feature freeze Day 8 14:00; evaluators only see the frozen build | Cut P2; hide incomplete screens |
| R8 | DPDP / child-data compliance gap | 2 | 5 | 10 | Minimisation, consent flow, deletion/export, no audio retention, face-blocking, no behavioural tracking | Remove parent app from demo if consent flow incomplete; never collect unconsented data |
| R9 | Demo fails during judging (API/network/LLM outage) | 3 | 4 | 12 | Cached plan + pre-generated demo pack; local docker-compose; recorded 3-min video fallback; `ai_degraded` UI | Video |
| R10 | Multilingual child misdiagnosed (language vs. concept) | 3 | 4 | 12 | Probe (P2); tutor language setting; teacher can mark "language barrier" chip | Explicit "not assessed — language" state |
| R11 | Cost blow-up during evaluation | 2 | 3 | 6 | Per-school daily budget cap; Haiku for extraction; caching; turn caps | Switch to pack mode |
| R12 | Annotation/eval not ready in time (no credible numbers) | 3 | 4 | 12 | Domain member starts labelling Day 1; 20-item minimum per set early; live guardrail counters as secondary evidence | Report live edit/reject rates + usability |
| R13 | Speech provider rate limits / outage | 2 | 4 | 8 | Provider interface + Google STT fallback; retry with backoff; typed/tap paths | Tap only |
| R14 | Prompt injection via notebook text/children's speech | 2 | 4 | 8 | Data-delimited prompts; injection suite; no tool access from extraction calls | Reviewer catches on confirm screen |
| R15 | Model/prompt drift degrades quality | 2 | 4 | 8 | Pinned model IDs; versioned prompts; eval gate on PRs | Revert prompt |
| R16 | Sibling/duplicate names (two "Rahul"s) | 3 | 3 | 9 | Roll numbers in roster; ambiguous matches resolved by teacher; evidence always shows roll | Teacher picks by photo/roll |
| R17 | Device compatibility (old Android, no mic permission) | 3 | 3 | 9 | Flutter minSdk policy; graceful permission denial → tap paths; test on emulator profiles | Web app |
| R18 | Hindi UI strings unfinished / unclear | 3 | 3 | 9 | Domain member writes copy Day 1–2; teacher review of screenshots | Bilingual labels |
| R19 | Privacy concern from teachers (fear of monitoring) | 3 | 4 | 12 | No teacher scoring; data owned by teacher; in-app privacy note; never a "teacher effectiveness" metric | Local-only mode discussed in roadmap (not built) |

---

## 2. Decisions (with recommendation)

| ID | Decision | Recommendation | Owner | Needed by |
|---|---|---|---|---|
| D1 | Hosting | One small VM + managed Postgres + S3-compatible store, docker-compose for local. Not serverless-only (long ASR/LLM chains, pgvector). | Eng | Day 1 |
| D2 | Speech provider | Sarvam AI primary (Hindi ASR/TTS), Google STT fallback behind an interface. | Eng | Day 1 |
| D3 | Language scope | Hindi UI + Hindi literacy checkpoints + language-neutral numeracy. Tag everything with `language`. | Product | Day 1 |
| D4 | Roster input | Manual/paste list first; CSV optional; attendance-register photo OCR is P2/cut. | Eng | Day 1 |
| D5 | Parent app form | PWA (Flutter Web) + installable; no Play Store. | Product | Day 1 |
| D6 | Activity library source | Team-authored templates + state handbook excerpts (TEJASVI/NCERT/Diksha), mentor-reviewed; runtime selects only reviewed items. | Education | rolling |
| D7 | Competency graph | Adapt the existing NIPUN-anchored graph; mentor review of prereq edges and misconception taxonomy. | Education | Day 2 |
| D8 | Home evidence weight | Capped at `needs_practice` (ADR-3); teacher confirmation needed for higher. | Product | Day 1 |
| D9 | Consent model | Paper form signed by parent, recorded by teacher + in-app parent confirmation at first session. | Product | Day 2 |
| D10 | Demo child/home history | Seed 3 weeks of realistic history for demo class; label as fictional in README. | Eng | Day 3 |
| D11 | Teacher confirmation default | Default-accept with visible "AI" chip; auto-accept only for high-confidence + arithmetic-verified numeracy items (config flag, off by default). | Product | Day 4 |
| D12 | Group size policy | 3–10 target; > 12 → whole-class note; < 3 merged within chapter only. | Education | Day 4 |

---

## 3. Interpretation notes / disputes with the spec

These are points where the "Final Problem & Solution" is silent, ambiguous, or where a straight reading creates risk. We choose the safer, more buildable option and state it.

| # | Spec text | Issue | Our resolution |
|---|---|---|---|
| I1 | "The AI tutor acts as a personal learning companion for approximately 30 minutes" | Open-ended 30-min child↔LLM chat is unsafe and expensive; also hard to evaluate. | Structured harness of 6–10 activities ≈ 25–30 min; AI writes language, code controls path and stop rules. |
| I2 | "The system converts [the index photo] into a structured learning roadmap" | Index pages list chapters, not sub-concepts; prerequisite edges can't be inferred from a photo. | Photo → draft of chapters/topics; checkpoint granularity and prerequisites from the reviewed NIPUN-anchored graph; teacher confirms. |
| I3 | "The teacher can also update the information through voice commands" | Free-form voice commands are unreliable (name ambiguity, accents). | Voice *notes* → structured proposals → confirm. Not command execution. |
| I4 | Statuses "Needs intervention / Improving / On track" (plus ✗/⚠/✓ in profile) | Four+ symbols in spec (✓ ⚠ ✗ and three words) map inconsistently. | Canonical: `not_started`, `needs_intervention`, `needs_practice`, `on_track`, plus `improving` flag. UI shows ✓ ⚠ ✗ · and a ↑ arrow. |
| I5 | "The AI listens to the interaction and evaluates the student's response" | Listening to the *teacher's prompt + student answer* in a noisy room; also privacy of other children's voices. | Short, targeted clips with known target words; keyterm-boosted ASR + scorer; others' speech filtered; teacher confirms. |
| I6 | "If a student is absent, no false progress is recorded" | Absence must be *recorded* to distinguish "absent" from "not assessed". | Separate `attendance` note in notes/tap; absence is evidence-free but visible. |
| I7 | Parent app shows "progress over time" | Numeric accuracy trends can demotivate or mislead parents. | Show effort + areas practised + areas to practise; trend hidden. |
| I8 | "Home practice results feed back" | AI-judged home answers are less reliable than teacher-confirmed school evidence. | Home evidence capped at `needs_practice` without teacher confirmation. |
| I9 | "Generate level-specific assignments or worksheets… may not have a printer" | Printing and worksheet generation is a different product. | Plan cards with *blackboard script*, copy-in-notebook steps, and a share image; paper generation is out of scope. |
| I10 | "Maintain progression/history" | Unbounded history is a data burden / privacy issue. | 14-day timeline in UI; full history retained server-side until class deletion; exportable. |
| I11 | Two learning dimensions (text/numeric, voice/language) | Written work of a language subject (copying, dictation) is *text* evidence; voice evidence matters for both dimensions in literacy. | Dimensions are per checkpoint (`assess_via`), not per subject. Numeracy can also have oral counting checkpoints. |
| I12 | "Group students with similar learning gaps" | Naïve grouping by the latest failed topic creates churn. | Prerequisite-root grouping + stability rules (banner on change; pin for a day). |

---

## 4. Open questions for the education mentor

1. Are our NIPUN-anchored prerequisite edges correct for the Jharkhand/UP textbooks used in the pilot schools? (graph review)
2. Is "borrowing" correctly separated from "place value" in our graph, or should it be one node with two misconception tags?
3. For Hindi literacy, what is the right order between "word formation" and "reading with matras"? (Our graph: `blend_no_matra` → `matra_basic` → `read_matra_words`.)
4. Is a 3–10 child group realistic given classroom noise and space? Should we lower the upper bound?
5. Which 12 activities are the highest-value for the demo (used most often in Grade 2/3)?
6. Are our probe scripts pedagogically sound for the concept-vs-language check?
7. What should the teacher-facing wording be for "needs intervention" so it is non-judgemental in Hindi?

---

## 5. Assumptions

- Teachers can spend ≤ 2 minutes per assessment while the class is occupied (e.g., during independent work).
- The school allows phone use in class for teaching purposes during the pilot.
- Parents/guardians are available to give consent at enrollment (paper) and a phone number exists for one parent/guardian.
- The demo/evaluation environment can reach Anthropic and Sarvam APIs during the evaluation window from the host region.
- Team has Flutter + Python experience; Claude credits cover eval + demo usage.
