# Kaksha Saathi: hackathon build rules

Two Flutter apps (`apps/teacher`, `apps/parent`) on one FastAPI backend (`backend/`), sharing one
child-level learning map. Submission deadline: **1 Nov 2026, 11:59 PM IST**. Read `README.md` for the
loop and `docs/` for the design; this file is how to work in the repo.

The AWS guidance in `/home/anya/CLAUDE.md` still applies on top of this file.

## Working style

- **Ship a working MVP and a polished demo.** The core flow is: class board → group plan → add
  evidence (tap / voice note / photo) → board and child profile update → parent practice session.
  Anything that does not serve that flow or the 3-minute demo waits.
- **Make reasonable decisions and keep going.** Don't ask about choices a sensible default settles;
  note the decision in one line. Ask only when the answer changes scope or touches something
  outward-facing or irreversible.
- **Keep the app runnable at all times.** Run `flutter analyze` and the backend tests after every
  meaningful change; build to the phone often. Don't leave a half-finished change on the main line.
- **Follow the existing architecture and conventions** (below). Match the surrounding code's style,
  naming and comment density. No new frameworks or state-management libraries.

## Parallel agents

Use 5–6 agents only when the work splits cleanly; for a small change, do it directly.
Brief each agent with the goal, the files it owns, and the contract it must keep. Agents work in
isolated worktrees (`isolation: "worktree"`) so changes merge cleanly.

| Role | Owns | Does not touch |
|---|---|---|
| **Lead** | `content/`, `docs/`, `README.md`, API contracts, merging, final demo script | feature code owned by others |
| **Flutter UI** | `apps/teacher/lib`, `apps/parent/lib` (screens, widgets, theme, `l10n.dart`) | `backend/` |
| **Backend/API** | `backend/app/api`, `models`, `services`, `db.py`, `seed.py` | prompts, Flutter |
| **AI** | `backend/app/ai` (prompts, schemas, features, rules), `evals/` | API routes, Flutter |
| **Integrations** | `backend/app/speech`, TTS/record plugins, Android manifests, `deploy/`, `docker-compose.yml`, `Makefile` | business logic |
| **QA** | `backend/tests`, `evals/` runs, `flutter analyze`, device testing (adb) | production code; reports bugs to the owner |

Rules for agents:
- Change an API payload **additively** (add fields, don't rename or remove). Tell the Lead when a
  contract changes so the Flutter side can follow.
- One agent per file at a time. If two roles need the same file, the Lead sequences them.
- Report back with what changed, how it was verified, and what is still broken. Don't claim a
  fix without running it.

## Architecture and conventions

- **AI reads messy input and writes language; code decides.** Mastery status, grouping, counts,
  arithmetic checks and pronunciation scores are deterministic (`backend/app/services`,
  `speech/scorer.py`). Every AI output is a *proposal* the teacher confirms, and every AI path has
  a deterministic fallback so the app works with no key and no network.
- **Claude calls** go through `backend/app/ai/llm.py`; model ids come from `config.py` (never
  hard-code one in a prompt). Prompts live in `backend/app/ai/prompts/*.vN.md` and are versioned.
  Planner output may only pick activities from the reviewed library in `content/`.
- **Language.** UI text uses `tr('English', 'हिन्दी')` from `lib/l10n.dart`; English is the default.
  `apps/teacher/lib/l10n.dart` and `apps/parent/lib/l10n.dart` are identical copies, so edit one and copy it.
  Lesson names use `cpTitle(map)`, other server fields use `pick(map, 'base')`. Classroom content
  (activity steps, probe questions, practice words, tutor speech) stays Hindi. Never put `tr()`
  in a `static const` or a default parameter; it can't be const.
- **Backend:** FastAPI + SQLAlchemy 2 + Pydantic 2. Routes in `api/teacher.py` and `api/parent.py`,
  all under `/v1`, tenant-scoped by JWT. SQLite by default, Postgres via `DATABASE_URL`.
- **Flutter:** plain `StatefulWidget` + `FutureBuilder`, one `Api` singleton per app
  (`lib/api.dart`) with an offline cache fallback, theme tokens in `lib/theme.dart` (`Ks`).
- **Content** (`content/*.json`) is reviewed learning material. Edit it deliberately; checkpoint
  ids are referenced everywhere.
- **Children are fictional in demo data.** Store only first name, roll number and learning
  evidence. Child names never go to the planner (it sees roll numbers).

## Commands

```bash
make setup                                   # backend venv + deps
make api                                     # API on :8000 (serves built web apps too)
make test                                    # ~940 backend tests on a fresh DB (rm backend/kaksha_dev.db), no API key needed
make eval                                    # deterministic evals
cd apps/teacher && flutter analyze           # likewise apps/parent
```

Phone over USB (backend must be running on :8000):

```bash
adb reverse tcp:8000 tcp:8000
cd apps/teacher && flutter build apk --debug --dart-define=API_BASE=http://localhost:8000
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Demo logins: teacher school code `DEMO`, PIN `1234`; parent `DEMO`, roll `12`, phone `9876500000`,
PIN `0000`. Debug manifests allow cleartext HTTP for the tunnel; release builds must use HTTPS.

## Secrets: never expose or commit

- API keys (`ANTHROPIC_API_KEY`, `SARVAM_API_KEY`), `JWT_SECRET`, keystores and `.env` files
  never go in code, docs, screenshots, logs, commit messages or chat output.
- Keys come from the environment or `backend/.env` (gitignored). `backend/.env.example` holds
  **names only, with empty values**.
- Before any commit or push, check `git status` and `git diff --cached` for secrets. If a key is
  ever exposed, say so immediately so it can be rotated.
- Built APKs in `dist/` and web bundles in `deploy/web/` are artefacts; don't commit them.
