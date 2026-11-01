# कक्षा साथी · Kaksha Saathi

**Where every child is, and what to do today.** A teacher app and a parent app for Grades 1–3 that
share one child-level learning map. The teacher captures evidence in seconds (tap, voice note or a
notebook photo), the app groups children by their real learning gap and writes today's plan, and the
parent's phone practises with the child at exactly that level through **Saathi**, a voice tutor.

AI for Foundational Learning Hackathon · Team **anya** · build-stage submission.

## Try it

| | Link | Login (all children are fictional) |
|---|---|---|
| Android APKs | [GitHub release `v1.0-submission`](https://github.com/DeshDeepakKant/kaksha-saathi-app/releases/tag/v1.0-submission) | Teacher: school code `DEMO`, PIN `1234`. Parent: school code `DEMO`, roll `12`, phone `9876500000`, PIN `0000`. Install steps in [`submission/INSTALL_STEPS.md`](submission/INSTALL_STEPS.md) |

**Five sample inputs** ([full steps and what you should see](submission/SAMPLE_INPUTS.md)):

1. **Voice note (teacher):** "आज उधार वाला घटाव कराया। मीना को उधार समझ नहीं आया। अर्जुन ने सही किया। प्रिया नहीं आई।" → one card per child with the quoted words → Confirm → the board updates.
2. **Notebook photo (teacher):** [`submission/sample_notebook_page.png`](submission/sample_notebook_page.png) → the AI reads five sums, code re-does the arithmetic and flags `52 − 28 = 36` and `63 − 27 = 46` as wrong.
3. **Tap check, then offline:** mark the class in a few taps; in airplane mode the board still opens and the check waits in an outbox until the phone reconnects.
4. **Parent voice session:** roll 12 → Start voice session → हिन्दी → read words aloud with Saathi → a session report with the exact sounds to practise.
5. **Home focus:** the teacher sets "Reading words" for कविता in English → the parent's next session follows it.

## Screens

<table>
<tr>
<td align="center"><img src="docs/screenshots/01_teacher_login.jpg" width="200"><br>Teacher login</td>
<td align="center"><img src="docs/screenshots/02_class_board.jpg" width="200"><br>Class board: absent, follow-ups, groups</td>
<td align="center"><img src="docs/screenshots/03_syllabus.jpg" width="200"><br>Syllabus progress</td>
<td align="center"><img src="docs/screenshots/04_syllabus_import.jpg" width="200"><br>Syllabus from textbook photos</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/05_group_plan.jpg" width="200"><br>Today's plan for a group</td>
<td align="center"><img src="docs/screenshots/06_photo_ai_read.jpg" width="200"><br>Notebook photo: what the AI read</td>
<td align="center"><img src="docs/screenshots/07_photo_teacher_fixed.jpg" width="200"><br>The teacher corrects, then confirms</td>
<td align="center"><img src="docs/screenshots/08_board_child_moved.jpg" width="200"><br>Board: a child moves group</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/09_voice_note_result.jpg" width="200"><br>Voice note: what the AI understood</td>
<td align="center"><img src="docs/screenshots/10_tap_check.jpg" width="200"><br>Tap check, no AI</td>
<td align="center"><img src="docs/screenshots/11_offline_outbox.jpg" width="200"><br>Offline: saved board and outbox</td>
<td align="center"><img src="docs/screenshots/12_child_profile.jpg" width="200"><br>A child's learning map</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/13_home_focus_set.jpg" width="200"><br>The teacher sets the home focus</td>
<td align="center"><img src="docs/screenshots/14_did_it_work.jpg" width="200"><br>Did the group activity work?</td>
<td align="center"><img src="docs/screenshots/15_level_check.jpg" width="200"><br>Quick level check</td>
<td align="center"><img src="docs/screenshots/16_settings_ai_ledger.jpg" width="200"><br>Settings and AI suggestion ledger</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/17_learning_languages.jpg" width="200"><br>Learning languages</td>
<td align="center"><img src="docs/screenshots/18_parent_login.jpg" width="200"><br>Parent login</td>
<td align="center"><img src="docs/screenshots/19_parent_home.jpg" width="200"><br>Parent home: this week at school</td>
<td align="center"><img src="docs/screenshots/20_parent_catch_up.jpg" width="200"><br>Teacher noticed: a 5-minute catch-up</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/21_learning_journey.jpg" width="200"><br>The child's learning journey</td>
<td align="center"><img src="docs/screenshots/22_weekly_summary.jpg" width="200"><br>Weekly summary (share on WhatsApp)</td>
<td align="center"><img src="docs/screenshots/23_session_language.jpg" width="200"><br>Saathi: today's practice and language</td>
<td align="center"><img src="docs/screenshots/24_session_warmup.jpg" width="200"><br>Warm-up: join the sounds</td>
</tr>
<tr>
<td align="center"><img src="docs/screenshots/25_session_read_word.jpg" width="200"><br>Read this word</td>
<td align="center"><img src="docs/screenshots/26_session_report.jpg" width="200"><br>Session report</td>
<td align="center"><img src="docs/screenshots/27_session_report_details.jpg" width="200"><br>Sounds to practise, where it was hard</td>
<td align="center"><img src="docs/screenshots/28_teacher_sees_session.jpg" width="200"><br>Back on the teacher's map</td>
</tr>
</table>

---

## How the loop works

```mermaid
flowchart TD
    A["1. Syllabus<br/>textbook photos or a book name<br/>become a draft map"] --> B["2. Evidence<br/>tap list, voice note, notebook photo,<br/>reading check, level check"]
    B --> C{"3. Teacher confirms<br/>what the AI understood"}
    C -- "edit or reject" --> B
    C -- "confirm" --> D["4. Mastery engine<br/>code: status per lesson"]
    D --> E["5. Grouping<br/>code: children who share a gap"]
    E --> F["6. Today's plan<br/>Claude picks from the reviewed library,<br/>code validates, template fallback"]
    F --> G["7. Follow-ups<br/>re-check, not moving, missed,<br/>did it work?"]
    G --> H["8. Home practice<br/>parent app and Saathi voice session<br/>at the level code chose"]
    H --> I["9. Session report<br/>back into the same map"]
    I --> D
```

**Design rule: AI proposes, code decides, the teacher confirms.** AI reads messy input (speech,
handwriting, mixed Hindi and English) and writes language. Code decides mastery status, groups,
counts, arithmetic and pronunciation scores. Every AI output is a proposal the teacher can edit or
reject, and every AI path has a deterministic fallback, so the app keeps working with no key and no
network.

### Teacher app
- **Class board:** who is absent, follow-ups, and groups of children to teach together, per subject
  (Maths, Hindi, English).
- **Evidence in seconds:** a tap checklist (no AI), a voice note in any mix of languages, a notebook
  photo (the AI reads each sum, code re-checks the arithmetic), a reading check and a step-by-step
  level check.
- **Today's plan** for each group: materials, steps, what to write on the board and a quick re-check,
  chosen from the reviewed library, with a Hindi read-aloud.
- **Child profile:** progress over time, what needs attention, the full map, and the home practice
  focus the teacher can set for Saathi.
- **Syllabus:** map chapters from textbook photos or the book name; the teacher confirms the list.
- **Settings:** app language and learning language (23 languages: English and 22 Indian languages),
  voice service, an AI suggestion ledger (shown, confirmed, edited, rejected, and cost), and a child's
  data download or delete.
- **Works offline:** the board opens from the last saved copy and tap checks wait in an outbox.

### Parent app
- This week at school, what the teacher noticed, a 5-minute catch-up activity, the learning journey
  and a weekly summary to share on WhatsApp.
- **Saathi voice sessions** (up to 30 minutes) in 11 spoken languages: a warm-up, practice at the
  child's level, hints and retries. Every word is scored by code. The report shows the exact sounds
  to practise and the next focus, and the teacher sees it on the child's profile.

---

## System design

```mermaid
flowchart LR
    T["Teacher app<br/>Flutter, Android and web<br/>offline cache and outbox"]
    P["Parent app<br/>Flutter, Android and web<br/>Saathi voice sessions"]
    subgraph Render["Render: one Docker web service"]
        API["FastAPI under /v1<br/>JWT login, every route<br/>scoped to one school"]
        ENG["Deterministic engine<br/>mastery, grouping, follow-ups,<br/>scoring, reviewed content"]
        GW["AI gateway<br/>JSON schema, validator,<br/>one retry, daily budget, call log"]
        SP["Speech router<br/>Gnani first, Sarvam second"]
    end
    DB[("Neon Postgres")]
    CL["Anthropic Claude<br/>Haiku 4.5, Sonnet 5.5, Sonnet 5"]
    GN["Gnani<br/>prisma-v3.0, timbre-v3.0"]
    SV["Sarvam<br/>saaras:v3, bulbul:v3"]
    T --> API
    P --> API
    API --> ENG
    API --> GW
    API --> SP
    ENG --> DB
    GW --> CL
    SP --> GN
    SP --> SV
```

Claude reads messy input and writes language. Code decides status, groups, counts, arithmetic and
scores. With no API keys the same routes fall back to keyword rules, the template planner and the
reviewed item bank.

## Workflows

### A teacher's day: voice note to plan

```mermaid
sequenceDiagram
    autonumber
    actor Teacher
    participant App as Teacher app
    participant API as FastAPI
    participant Speech as Speech router
    participant AI as Claude via AI gateway
    participant Eng as Mastery engine
    participant DB as Postgres
    Teacher->>App: speaks a note after class
    App->>API: POST /classes/ID/captures/voice
    API->>Speech: transcribe the audio
    Speech-->>API: transcript
    API->>AI: read the note into per child results
    AI-->>API: proposals with the quoted words
    API-->>App: proposal chips, nothing saved yet
    Teacher->>App: edits or confirms
    App->>API: POST /captures/ID/confirm
    API->>Eng: add evidence, recompute status
    Eng->>DB: save evidence and status
    App->>API: POST /classes/ID/plans
    API->>Eng: group children who share a gap
    API->>AI: pick one reviewed activity per group
    AI-->>API: plan
    API->>API: validate against the library, else template plan
    API-->>App: today's plan
    Note over App,API: With no network, taps wait in an outbox and sync later
```

### A child's evening: Saathi voice session

```mermaid
sequenceDiagram
    autonumber
    actor Parent
    actor Child
    participant App as Parent app
    participant API as FastAPI
    participant Eng as Engine
    participant Speech as Speech router
    participant AI as Claude via AI gateway
    Parent->>App: signs in, picks a language, starts a session
    App->>API: POST /parent/voice/sessions
    API->>Eng: choose the level from the teacher's evidence or home focus
    API-->>App: first item and Saathi's line
    App->>API: POST /speech/tts
    API->>Speech: text to speech
    Speech-->>App: audio, Saathi speaks
    loop until time is up or the parent stops
        Child->>App: answers aloud
        App->>API: POST /parent/voice/sessions/ID/turn
        API->>Speech: transcribe the answer
        API->>Eng: score the answer in code
        API->>AI: safety check and a short reply
        API-->>App: result, hint or next item
    end
    App->>API: POST /parent/voice/sessions/ID/end
    API->>AI: write the report text
    API-->>App: session report
    Note over API: The teacher sees the report on the child's profile
```

---

## External AI services and where keys are needed

Model ids live in `backend/app/config.py` and can be changed with `MODEL_*` environment variables;
prompts never hard-code a model. All Claude calls go through `backend/app/ai/llm.py`, and prompts are
versioned in `backend/app/ai/prompts/`.

| Service | Model (default) | Used for | Key |
|---|---|---|---|
| Anthropic Claude | `claude-haiku-4-5-20251001` (`MODEL_EXTRACT`) | reading teacher voice/typed notes, syllabus drafts, reading-check judging, the parent safety check, Saathi's turn-by-turn replies and open-answer checks, session report text, machine translation of short classroom texts | `ANTHROPIC_API_KEY` |
| Anthropic Claude | `claude-sonnet-5-5` (`MODEL_PHOTO`) | reading notebook photos (handwriting, tick marks) | `ANTHROPIC_API_KEY` |
| Anthropic Claude | `claude-sonnet-5` (`MODEL_PLAN`) | today's group plans (only activities from `content/`) | `ANTHROPIC_API_KEY` |
| Anthropic Claude | `claude-sonnet-5` (`MODEL_TUTOR`) | Saathi's practice items and the parent's weekly summary | `ANTHROPIC_API_KEY` |
| Anthropic Claude with server-side web search | `claude-sonnet-5` (`MODEL_BOOK`), tool `web_search_20260209` | mapping textbook chapters to lessons (`BOOK_WEB_SEARCH=false` turns the search off) | `ANTHROPIC_API_KEY` |
| Gnani Vachana (default voice service) | Prisma `prisma-v3.0` (speech-to-text), Timbre `timbre-v3.0` (text-to-speech) | teacher voice notes, the child's speech in Saathi sessions, Saathi's voice; 10 languages | `GNANI_API_KEY` |
| Sarvam AI (backup, and languages Gnani lacks) | `saaras:v3` (speech-to-text), `bulbul:v3` (text-to-speech) | the same; speech-to-text in all 23 languages, voice in 11 | `SARVAM_API_KEY` |

The speech router tries the teacher's chosen service first, then the other one, skipping any provider
without a key or without the language.

**With no keys at all** the app still runs: keyword rules read notes, the template planner writes
plans, tap capture always works, Saathi uses the reviewed item bank and templated lines,
speech-to-text returns nothing (type instead) and the phone's own voice reads text aloud. A per-school
daily AI budget (`DAILY_BUDGET_INR_PER_SCHOOL`, default ₹250) switches to the same fallbacks when it
runs out.

---

## Run locally

Requirements: Python 3.12; Flutter 3.x only to rebuild the apps.

```bash
make setup        # backend venv + dependencies
make api          # API on http://localhost:8000; seeds the demo school on first boot
```

Open http://localhost:8000 for a landing page with both web apps and the API docs (`/docs`). Keys are
optional: copy [`backend/.env.example`](backend/.env.example) to `backend/.env` and fill in what you
have. Never commit `.env`.

Other ways to run:

```bash
docker compose up --build                     # API + Postgres
make seed                                     # reset the demo school
make web                                      # rebuild both Flutter web apps into deploy/web/
cd apps/teacher && flutter build apk --release --dart-define=API_BASE=https://your-host   # likewise apps/parent
```

### Tests and evals

```bash
rm -f backend/kaksha_dev.db && make test   # backend tests on a fresh database, no API key needed
make eval         # deterministic evals: note extraction, planner, reading scorer
```

Backend suite: **940 passed, 2 expected failures** (run on 1 Nov 2026 against a fresh database). It
covers the mastery rules, prerequisite gap finding, the arithmetic override, tenant isolation, the
speech router, voice sessions, the parent safety path and the English subject.

Development-set eval results (details in [`docs/EVAL_RESULTS.md`](docs/EVAL_RESULTS.md), raw JSON in
`evals/reports/`):

| Harness | Result |
|---|---|
| Notes extraction (rules fallback) | precision 1.00 · recall 1.00 · F1 1.00 on 12 notes |
| Planner (template) | 6/6 structurally valid scenarios, all within the 25-minute budget |
| Reading scorer | 20/20 labelled items, κ 1.00 |

---

## Low connectivity and low-cost phones

| Feature | Offline | Notes |
|---|---|---|
| Teacher login (after the first success) | ✅ | token cached |
| Board, plan, child profiles | ✅ | last saved copy; a banner says so |
| Tap checklist | ✅ | saved on the phone and sent on reconnect (outbox) |
| Voice note | ⚠️ | needs the network to transcribe; a typed note works the same way |
| Notebook photo reading | ❌ | needs Claude; use the tap checklist |
| Parent voice session | ❌ | needs the network for speech and Saathi's replies; the app says so and offers Try again |
| Plans with no AI | ✅ | the template planner runs on the server |
| Hindi read-aloud | ✅ | phone voice on Android, browser speech on the web |

Android 7.0 or newer (minSdk 24). Tested on a Moto g64 (Android 15). No child device is needed.

---

## Privacy

- Stored per child: **first name, roll number and learning evidence**. No surname, date of birth,
  address or photo of the child. All children in this repo and the demo are fictional.
- **Audio is not stored.** It is sent for transcription or scoring and dropped; transcripts are kept as
  text with the evidence.
- **Notebook photos are not stored.** The image is read in memory and only the per-question result is
  saved. The app asks for "Notebook only, no faces", and the model flags a face or extra content
  (`face_or_extra_present`).
- The parent's phone number is stored only as a keyed hash, and the parent sets a PIN after a consent
  step.
- Child names are never sent to the planner; it sees roll numbers.
- `DELETE /v1/children/{id}/data` removes a child's evidence, attendance, level checks and home focus;
  `DELETE /v1/classes/{id}/data` clears a class.
- No advertising, no behavioural tracking, no scoring of teachers.

---

## Repository map

| Path | What |
|---|---|
| `backend/` | FastAPI service: mastery engine, grouping, plan templates, AI features, speech, API (`/v1`, JWT, tenant-scoped) |
| `content/` | Learning content: competency graph, activity library, practice items, probes, voice bank |
| `apps/teacher/`, `apps/parent/` | Flutter apps (Android and web) |
| `evals/` | Golden sets and runnable eval harnesses |
| `deploy/web/` | Built web apps and the landing page, served by the API |
| `submission/` | Sample inputs, a sample notebook page, APK install steps |
| `docs/` | Design set (technical report, architecture, domain, AI spec, eval plan, risks), API contracts, screenshots |

## License

Code: [MIT](LICENSE).
