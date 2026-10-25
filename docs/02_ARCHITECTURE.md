# 02 · Architecture

> System architecture, AI orchestration, deployment, sync and security for Kaksha Saathi.
> The layer structure follows the hackathon's tech-flow guidance: **Input → Context → LLM reasoning → Guardrails + checks → Output**, plus memory and low-connectivity fallbacks.

---

## 1. Architecture principles

1. **AI is in services, not in the UI.** All model calls sit behind one orchestrator so they can be validated, logged, rate-limited, cached and swapped.
2. **Deterministic where it matters.** Mastery, grouping, correctness scores, coverage and cost are computed by code. Model output is always validated against schemas and domain constraints.
3. **One evidence pipeline, many entry points.** Every capture path (photo, voice, tap, home session) ends in the same `evidence` table.
4. **Offline-first clients.** The teacher app never blocks on the network. The parent app localises at pack download.
5. **Stateless API, stateful datastore.** API instances can scale horizontally; all state lives in Postgres and object storage.
6. **Fail closed on child safety, fail open on availability.** If a safety filter trips, no output is shown. If the LLM is down, the teacher gets a deterministic fallback plan, not an error.

---

## 2. Layered data-flow (mirrors the hackathon's evaluation diagram)

```
┌──────────────────────── INPUT ────────────────────────┐
│ Teacher app:                                      │
│  • Voice note (M4A, hi/en mixed, ≤60 s)           │──▶ Sarvam ASR (saaras) ──▶ transcript
│  • Notebook photo (≤ 2 MB, JPEG)                  │──▶ Object store → Claude vision
│  • Classroom voice clip (≤ 20 s, target word known)│──▶ ASR + acoustic scorer (deterministic)
│  • Tap checklist / manual status                  │──▶ (no AI)
│  • Textbook index photo                           │──▶ Claude vision → roadmap DRAFT
│ Parent app:                                       │
│  • Child speech attempts (≤ 6 s each)             │──▶ ASR + scorer + Claude feedback
│  • Tap answers                                    │──▶ (no AI)
└────────────────────────────────────────────────────┘
                         │
┌─────────────────────── CONTEXT ──────────────────────┐
│ Per request, the orchestrator assembles:            │
│  • Roster (roll # → first name; names → {R12} tokens before planner calls)
│  • Roadmap for class × subject (checkpoints + prereqs)
│  • CompetencyState rows for the involved children
│  • Retrieved library activities for the implicated checkpoints (pgvector + exact checkpoint key)
│  • Retrieved curriculum snippets (NIPUN Lakshya, TEJASVI/NCERT handbook excerpts) with citations
│  • Pacing calendar (which chapter the class is on) – from roadmap ordering + teacher marks
└─────────────────────────────────────────────────────┘
                         │
┌────────────────── LLM REASONING (Claude) ────────────┐
│ Anthropic Messages API, structured output (JSON schema), prompt caching:
│  • claude-haiku-class  → note extraction, photo per-question extraction, roadmap draft
│  • claude-sonnet-class → intervention planning, tutor dialogue, home→teacher summary, misconception probing
│ All calls: temperature low, max_tokens bounded, system prompt versioned in repo (app/prompts/*.md)
└─────────────────────────────────────────────────────┘
                         │
┌────────────── GUARDRAILS + CHECKS (code + Claude) ───┐
│ 1. Schema validation (Pydantic)                       │
│ 2. Domain validation: child IDs ∈ roster; checkpoint IDs ∈ roadmap;
│    activity IDs ∈ reviewed library; times ∈ [0, duration]; group membership consistent
│ 3. Business rules: e.g., home evidence can't set on_track; <3 independent items ≠ "correct"
│ 4. Claude-based second pass only where needed (tutor safety, misconception plausibility)
│ 5. Retry-once with error message → deterministic fallback
│ 6. Human-in-the-loop: teacher confirm screen before evidence reaches mastery
│ 7. Logging: every call stored (model, tokens, latency, cost, prompt version, validation result)
└─────────────────────────────────────────────────────┘
                         │
┌──────────────────────── OUTPUT ──────────────────────┐
│ Teacher: confirmed evidence, child profile, class board (groups), intervention card, re-teach alerts
│ Parent: session transcript summary, what was practised, effort, next focus
│ Both: offline-ready cached versions
└─────────────────────────────────────────────────────┘
```

---

## 3. Components

| Component | Tech / Version | Responsibility |
|---|---|---|
| **Teacher app** | Flutter (Android primary; Web build for evaluators) | Onboarding, roadmap builder, capture (photo/voice/tap), confirm screen, class board, child profiles, history |
| **Parent app** | Flutter Web (mobile-first); installable PWA | Child login (parent-gated), daily session, history, progress |
| **API service** | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic | REST, auth, orchestration entry points, rate limits |
| **AI orchestration** | `ai_orchestrator/` Python module using Anthropic SDK | Prompt assembly, structured outputs, validation, retries, fallback, budgets, logging |
| **Speech service** | Sarvam AI (ASR `saaras:v4`, TTS `bulbul`), provider abstraction | Transcription with keyterm boosting (roster names, target words); TTS for parent app |
| **Pronunciation / reading scorer** | Python: normalization → alignment → constrained diff; optional phonemisation | Deterministic accuracy/omission/insertion scores vs. target text |
| **Mastery engine** | Pure Python | Evidence → status/confidence, prerequisite-aware gap detection |
| **Grouping engine** | Pure Python | Top-gap clustering, rule selection |
| **Content store** | JSON seeded into DB; versions in repo | Competency graph, activity library (reviewed flag), practice item bank, probe scripts, packs |
| **Database** | Postgres 16 (+ pgvector); SQLite for single-node dev | All state |
| **Object storage** | S3-compatible (local: MinIO in docker-compose) | Uploaded work photos, pre-generated packs. Explicit TTL (photos 7 days by default, teacher can delete) |
| **Cache / queue** | Redis (optional) / DB-backed outbox | Per-day idempotency, LLM cost budget, background jobs (photo analysis) |
| **Observability** | Structured JSON logs; LLM call table; `/metrics` (Prometheus format) | Debugging, cost, eval sampling |

> **Mobile build tooling reference:** this workspace is set up for Flutter. Teacher app targets Android with `record`, `connectivity_plus`, `dio`, `sqflite` (outbox), `flutter_tts` (offline Hindi read-aloud of plans). Parent app is a Flutter Web PWA with browser `MediaRecorder` (Chrome/Android) and tap fallbacks.

---

## 4. Deployment topology

### 4.1 Demo / evaluation (target for 1 Nov)

```
                 ┌────────── Cloudflare / DNS ──────────┐
                 ▼                                       ▼
        app.kakshasaathi.<domain>          parent.kakshasaathi.<domain>
        (static Flutter Web)               (static Flutter Web PWA)
                 │                                       │
                 └──────────────┬────────────────────────┘
                                ▼
                  api.kakshasaathi.<domain>  (FastAPI container, 1–2 vCPU, 1 GB)
                       │            │               │
                       ▼            ▼               ▼
                Postgres (managed or         Object storage       Redis (optional)
                container with volume)       (S3-compatible)
```

**Non-functional targets for the demo:** p95 API < 400 ms excluding AI; ASR < 3 s for a 20 s clip; photo analysis < 8 s; plan generation < 12 s; tutor turn < 2.5 s; 99% availability over the evaluation window; API frozen at submission.

**Hosting options (decision D1 in [07](07_RISKS_AND_DECISIONS.md)):**
- **A:** One small VM (2 vCPU / 4 GB) + managed Postgres + S3-compatible storage; docker-compose for API + web. Cheapest, full control, HTTPS via Caddy.
- **B:** Managed app platform (e.g., Fly.io / Render / Railway) for API + managed Postgres + S3.
- **C:** Vercel for the two web frontends + a managed DB — **not sufficient alone** because the API requires long-running Python services (ASR calls, LLM chains, background workers) and a persistent Postgres with pgvector; a serverless-only API would need restructuring. Use Vercel only as optional CDN for the web apps if convenient.

**Recommendation:** **A**, simplest to freeze and reproduce; no key-management or cold-start surprises during judging. Document a `docker-compose.yml` that runs the *entire* stack locally for evaluators.

### 4.2 Pilot (multi-school, later)

- API behind a load balancer, 2+ replicas, managed Postgres with PITR, object storage with lifecycle rules.
- Tenant isolation: every row carries `school_id`; Postgres Row-Level Security enabled; retrieval and prompts always filtered by tenant.
- Background workers (photo analysis, pack generation) via a simple job table + worker process (Celery/arq if needed).
- Backups: daily DB dump to object storage, 30-day retention.

---

## 5. AI orchestration design

### 5.1 Pipeline pattern

```
[Request] → validate input → build context (cheap, DB) → *precheck budget*
   → model call (structured output, cached system prompt)
   → parse & validate (Pydantic + domain checks)
        ├── valid → post-check (rules / Claude verifier if configured) → persist proposal → return to client
        └── invalid → retry once with the validation error appended as user message
                       └── still invalid → deterministic fallback → mark "ai_degraded": true
```

### 5.2 Model policy

| Use | Model class | Temperature | Max out | Prompt caching | Timeout / fallback |
|---|---|---|---|---|---|
| Note extraction | Haiku-class | 0 | 1.5k | system + competency index | 20 s → retry → rule-based empty proposal (teacher sees "couldn't read; use tap") |
| Photo analysis | Haiku-class (vision) | 0 | 4k | system + roadmap spec | 40 s → retry with downscaled image → manual entry |
| Roadmap draft | Haiku-class (vision) | 0.2 | 3k | system + graph summary | 60 s → manual roadmap |
| Intervention plan | Sonnet-class | 0.3 | 3k | system + activity library subset | 30 s → template plan |
| Tutor turn | Sonnet-class | 0.4 | 600 | system + session state | 3 s → canned supportive line + advance |
| Safety check (tutor) | Haiku-class | 0 | 200 | — | on any doubt, suppress |
| Misconception hypothesis | Sonnet-class | 0.2 | 1k | system | 30 s → none |

**Model IDs:** pinned to current Claude model IDs in [`04_AI_SPECIFICATION.md`](04_AI_SPECIFICATION.md) §2 and in a single `MODELS` constant so they can be updated without touching prompts. Use `messages.parse`-style structured output where available; otherwise tool-use with a single forced tool.

### 5.3 Cost controls

- Per-school daily budget (configurable; default ₹X) → when exhausted, only local/fallback paths run, parent tutor switches to pack mode.
- Prompt caching for the large, static parts (competency graph summary, activity library rules, tutor persona).
- Haiku class for all extraction; Sonnet only for planning/tutor.
- Idempotency keys on all POSTs so retries never double-charge.
- Per-call token and latency logged; a dashboard tile shows today's spend (also useful to judges).

### 5.4 Deterministic fallbacks

| Feature | Fallback |
|---|---|
| Teacher note → evidence | Teacher fills a 30-second tap checklist (same UI, pre-selected likely children based on note text search) |
| Photo → per-question evidence | Teacher marks each question ✓/✗ from the photo with big buttons |
| Plan | Template plan per gap type from the *reviewed* library (renderer only, no model) |
| Tutor | Downloadable "tap pack": listen (TTS) → tap correct picture/word → feedback; evidence synced later |
| Probe scripts | Pre-written probe scripts for the top 100 checkpoints |

---

## 6. Client architecture

### 6.1 Teacher app (Flutter)

```
lib/
  main.dart, app.dart              # routing, theme (large text, high contrast)
  core/ (api_client, outbox_queue, pack_store, auth, l10n)
  features/
    onboarding/   # login (school code + PIN), classes, roster import (CSV/typing/photo of attendance register later)
    roadmap/      # index photo → draft → edit → confirm (ReorderableListView)
    capture/      # note_voice, work_photo, class_voice, tap_checklist, teacher_note
    confirm/      # "What we understood" — editable chips per child/question
    classroom/    # groups board, intervention card, print/share (image), TTS read-aloud
    child/        # profile, checkpoint timeline, history chart, flags
    settings/     # language, privacy, export, delete class data, budget
```

**State:** Riverpod/BLoC (team choice). **Local DB:** SQLite with tables mirroring `roster`, `roadmap`, `pack` (activities/items), `outbox` (pending uploads). **Outbox:** every capture writes local row with `client_uuid`, uploaded on reconnection in FIFO; server is idempotent by `client_uuid`. **Photo flow:** compress to ≤ 2 MB before enqueue; retain locally until server confirms + TTL.

### 6.2 Parent app (Flutter Web PWA)

```
lib/
  features/
    parent_gate/   # invite code + child name → parent consent (scrollable, audible) → PIN
    home/          # today's session card, big "बोलिए / शुरू करें" button
    session/       # activity runner (see §3.4 of doc 03): prompt player, record button, feedback, progress dots
    history/       # list of sessions, areas still needing practice, streak
    settings/      # language, voice speed, privacy, delete data, consent pdf
```

- **Session pack download:** at parent-gate success and nightly, the app fetches a `SessionPack` JSON + audio assets (target words pronounced by TTS so the child hears a model pronunciation, ~0.5–2 MB).
- **Audio:** browser `MediaRecorder` where available; if unavailable (some browsers), the app uses tap activities only and tells the parent "speaking practice needs Chrome".
- **Offline:** service worker caches app shell + pack; sessions run locally; turns that need Claude (free-form feedback) are limited to a set of pre-generated feedback lines when offline.

---

## 7. Data flow scenarios (end-to-end)

### S1 — Teacher photographs a notebook page
1. App compresses, enqueues (offline ok). On upload, server stores photo, creates a `job`.
2. Job: Claude vision extracts `{grade, subject_guess, questions[]}`; the orchestrator maps each to the class roadmap (by operation/pattern) and to children (teacher selects child at capture).
3. Server computes per-question correctness only from the model's structured output + calibration rules (see doc 04 §4), feeds the mastery engine **as a proposal**, returns a confirm payload.
4. Teacher reviews (default all "accept"), fixes "52−28=36" if needed → `POST /confirm` → evidence committed → profiles and groups recompute.

### S2 — Classroom voice assessment
1. Teacher picks a child + a checkpoint (or picks "recommend next probe" → sees checkpoint + probe script + 3 target words).
2. Records child reading 3 words / answering 5 prompts. Uploads.
3. ASR with keyterms = target words + child name. Scorer aligns transcript to target list → per-word correct/omitted/mispronounced scores.
4. Claude maps the session to the checkpoint: which items produced evidence for which sub-skill; proposes misconception tags from a fixed taxonomy.
5. Teacher confirm (one screen: 3 words × ✓/✗ plus suggested status); commit.
6. If the child fails 3 sessions on the same checkpoint, a *probe* suggestion appears (P2).

### S3 — Morning plan
1. Teacher taps "आज की योजना" (today's plan). Server loads states, groups and pacing.
2. Grouping engine computes groups; for each, orchestrator calls planner with groups + 6–10 candidate activities (already filtered by code: reviewed, matching checkpoint, group size fit, ≤10 min, no materials unavailable).
3. Validator checks references/materials/time; failing plans → template.
4. Output: 2–4 group cards; each with activity steps, teacher script (Hindi), blackboard version, one reassessment question; TTS reads the summary aloud (offline).
5. Teacher marks "did it" per group (optional one tap) → prompt to record reassessment later.

### S4 — Child's home session
Described in [03 §5](03_DOMAIN_AND_DESIGN.md#5-parent-app--voice-tutor-design); wall-clock ~25–30 min, 6–10 activities, adaptive.

### S5 — Nightly consolidation
1. Jobs aggregate home evidence; compute "practice flags" (needs_practice on a checkpoint with low home accuracy over 3 sessions).
2. Generate parent-friendly weekly summary (text + TTS).
3. Generate teacher "home summary" line per child (only for children with ≥1 home session that day) on the class board.
4. Purge expired photos/audio per retention policy.

---

## 8. Security, privacy and DPDP alignment

| Concern | Design |
|---|---|
| **Consent** | Parent consent is collected through the teacher during roster onboarding (paper/photo form signed by parent; teacher marks consent in app with date; form template in repo). Parent app re-confirms with verifiable parental consent flow (parent's own mobile/PIN) before any session. Children cannot open the parent app without the parent PIN. |
| **Minimisation** | First name + roll number + class. No photos of faces (we refuse/exclude face regions in work photos — see §8.1), no DOB, no address, no phone in teacher app; parent phone stored only hash+salt for the parent's own login. |
| **Audio** | Classroom audio is processed for ASR/scoring and **not retained** after processing (raw deleted within 24 h; only derived transcript-based evidence retained if teacher confirms). Parent audio: processed per turn, not retained beyond the session (session transcript summary without audio kept). |
| **Photos** | Stored encrypted at rest; TTL default 7 days; teacher can delete immediately; export available. Photos are of work pages, not faces — UI guidance + an automatic face-presence detector (client-side ML Kit or server-side) that **blocks upload** with a "please retake the page only" message. |
| **Access control** | Teacher sees only own classes; parent sees only own child(ren); every DB query scoped by tenant/owner; JWT short-lived + refresh; invite codes rate-limited. |
| **Data localisation** | Host in Indian region if possible (ap-south-1 / in region of chosen host); LLM calls go to the Anthropic API. State this explicitly in the privacy notice and in the repo README. |
| **Export & deletion** | `GET /children/{id}/export` (JSON/PDF), `DELETE /children/{id}/data`, `DELETE /classes/{id}/data`; hard delete within 30 days, soft delete immediately. |
| **Logging** | No transcript text or child names in application logs; LLM logs store hashed child references. Model providers: confirm no-training / retention settings in use; note in privacy doc. |
| **Safety of tutor** | Scope-locked tutor (only learning), blocked topics list, self-harm/abuse detection → fixed supportive redirect + surface "tell your parent or teacher" card; no persona that pretends to be a friend; no data collection in conversation beyond learning evidence. |
| **Compliance note** | DPDP Rules 2025 impose verifiable parental consent and no behavioural tracking/targeted advertising for children. The system does neither; document it in the submission deck. |

### 8.1 Handling faces in work photos
- Client prompts "photograph only the notebook page".
- Server-side face detection (OpenCV Haar/DNN or a light model) → if a face area > threshold, return `photo_rejected_face` and the app re-prompts with a grid overlay.
- Photos are of pages; the teacher's thumb sometimes appears (fine).

---

## 9. Non-functional requirements

| Attribute | Requirement |
|---|---|
| **Performance** | p95: login 300 ms, tap checklist 200 ms, upload 1 s (excluding network), ASR 3 s for 20 s audio, photo analysis 8 s, plan 12 s, tutor turn 2.5 s |
| **Availability** | Demo: 99% during evaluation. Core reads (roster, profile, plan cache) must work when LLM/ASR providers are down |
| **Scalability** | 1 school = ~10 teachers × 5 classes × 35 children = 1,750 children; 1,000 schools is manageable with tenant-scoped Postgres + object storage. Target: 50k children/day home sessions with 2 API replicas + queue workers |
| **Offline** | Teacher: all capture + plan view + TTS offline; only AI processing waits. Parent: session works from pack, tap-fallback for AI |
| **Accessibility** | Large tap targets (≥ 56 dp), system font scaling, high contrast, TTS read-aloud in both apps, minimal text |
| **Localisation** | Hindi + English UI strings (Flutter l10n). Content language-tagged per checkpoint (hi, en, numeracy). |
| **Observability** | Every LLM call: `{id, feature, model, prompt_version, input_tokens, output_tokens, latency, cost, validation_status}`; error rates by feature; eval sampling |
| **Maintainability** | Prompts as versioned files; prompt changes require eval suite pass (doc 05); model IDs in one constant |

---

## 10. Technology choices and rationale

| Choice | Alternatives considered | Why |
|---|---|---|
| Flutter (both apps) | React Native, native Android | Single codebase; web build for evaluators (tech guidance prefers a web link); team already has Flutter experience (`flutter_project_workspace`) |
| FastAPI (Python) | Node/Express, Django | Fast to build; great SDK ergonomics for Anthropic + speech libs; Pydantic validation is central to guardrails |
| Anthropic Claude (required) | — | Hackathon requires Claude credits used; Sonnet for planning/tutor, Haiku for extraction |
| Sarvam AI for ASR/TTS | Google Chirp, Bhashini, Whisper | Strong Hindi (incl. code-mixed) ASR and natural Hindi TTS, straightforward API; provider abstraction means Bhashini can be added |
| Postgres + pgvector | SQLite, MongoDB | Relational integrity for evidence/roster/roadmap + vector RAG in one store; SQLite for dev |
| Reviewed JSON content library | Pure RAG, pure LLM generation | Quality + safety of pedagogy; RAG just retrieves what humans approved |
| Docker Compose for demo | Managed serverless | Freeze/reproduce complete environment; no cold starts on ASR/LLM chains |
| PDF/PNG generation client-side | Server PDF service | Teachers can share plans via WhatsApp as an image; avoids server deps |

---

## 11. Repository layout (target)

```
kaksha-saathi/
├── README.md                      # setup, run, demo accounts, external services, offline matrix
├── .env.example
├── docker-compose.yml             # db, api, web-teacher, web-parent, worker, minio
├── docs/                          # this documentation set (condensed) + demo script
├── backend/
│   ├── app/
│   │   ├── main.py, config.py
│   │   ├── api/                   # routers per feature
│   │   ├── models/                # SQLAlchemy tables + Pydantic schemas
│   │   ├── services/              # mastery.py, grouping.py, evidence.py, packs.py, retention.py
│   │   ├── ai/                    # orchestrator.py, prompts/*.md, validators.py, fallbacks.py, budget.py
│   │   ├── speech/                # asr.py, tts.py, scorer.py, providers/
│   │   └── seed/                  # demo school, fictional class, history
│   ├── migrations/                # Alembic
│   └── tests/                     # unit + integration + golden extraction (no API key required for CI core)
├── content/
│   ├── competency_graph.json      # checkpoints + prereqs (NIPUN-anchored, mentor-reviewed)
│   ├── activities.json            # reviewed activity library
│   ├── practice_items.json        # word lists, number tasks, pictures refs
│   ├── probes.json
│   └── curriculum_snippets/       # RAG sources with citations
├── evals/
│   ├── golden/                    # notes, photos, transcripts, tutor sessions, labels
│   ├── run_extraction.py, run_planner.py, run_tutor.py
│   └── reports/
├── apps/
│   ├── teacher/                   # Flutter
│   └── parent/                    # Flutter Web
└── deploy/                        # Caddyfile, compose overrides, backup scripts
```

---

## 12. Architecture decision records (short)

| ADR | Decision | Status |
|---|---|---|
| ADR-1 | Mastery computed in code, not by LLM | Accepted |
| ADR-2 | Planner constrained to reviewed activity library with template fallback | Accepted |
| ADR-3 | Home evidence cannot promote above `needs_practice` without teacher confirmation | Accepted |
| ADR-4 | Tutor is a harness-driven structured session, not open chat | Accepted |
| ADR-5 | Teacher app offline outbox with client-generated UUIDs; server idempotent | Accepted |
| ADR-6 | Photos TTL 7 days, audio never retained | Accepted |
| ADR-7 | Deploy as containers on one VM + managed Postgres for the demo | Accepted (see 07 D1) |
| ADR-8 | Hindi first; architecture language-tagged for extension | Accepted |
