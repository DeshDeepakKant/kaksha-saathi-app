# 06 · Build Plan

> From 24 October 2026 to submission on **1 November 2026, 11:59 PM IST** (≈ 9 working days), then final-stage refinement if selected.
> Principles: **vertical slices**, **P0 before P1 before P2**, **eval gates before ship**, **freeze early**, **rehearse the demo**.

---

## 1. Priorities

| Priority | Scope | Must work at submission |
|---|---|---|
| **P0 — Teacher loop (core)** | Login, class + roster, roadmap from photo/template + confirm, capture: note / photo / tap / voice, confirm screen, mastery engine, child profile, grouping, plan (AI + fallback), reassessment, export/delete | ✅ Yes |
| **P1 — Parent app** | Parent gate + consent, pack download, 8-activity voice session (Harness + A9), tap fallback, history, home → teacher summary | ✅ Yes (voice + tap fallback) |
| **P2 — Probes & polish** | Misconception hypotheses (A6), guided probes (A5), language-vs-concept probe, group-change banner, share PNG, TTS plan read-aloud | If time |
| **Cut** | multi-teacher school, other languages, CRP view, PDF exports, analytics dashboards | Not built |

---

## 2. Milestones

| Milestone | Date | Exit criteria |
|---|---|---|
| M0 — Design locked | 24 Oct (today) | This doc set agreed; decisions D1–D8 resolved |
| M1 — Skeleton + data model | 25 Oct | docker-compose runs; DB migrations; seed demo school/class/roster; login on web |
| M2 — Roadmap + capture (notes & tap) | 27 Oct | Teacher can build a roadmap and record evidence end-to-end by tap and voice note; mastery + profile screens live |
| M3 — Photo + voice + plan | 29 Oct | Notebook photo flow; classroom-voice flow; grouping; plan card with AI + template fallback; reassessment |
| M4 — Parent app | 31 Oct | Parent gate, pack, session (Harness + A9 + safety), history, teacher summary; seed packs for demo child |
| M5 — Freeze + eval + submission | 1 Nov | All eval reports committed; hosted URLs frozen; APK; video; deck; README; sample inputs; test credentials; final commit before 23:59 IST |
| M6 — Final stage (if selected) | 10–18 Nov | Field feedback, robustness, pilot, finalise deck and live-demo backup |

---

## 3. Day-by-day (2 developers, with a third for design/domain in parallel)

> Team size assumed 3–4 (hackathon rule). Adjust names later. A **domain/education member** writes content and labels concurrently from Day 1; they are the bottleneck for eval — start immediately.

### Day 1 — 25 Oct (Sat)
- Repo, CI (lint + unit tests), docker-compose (Postgres, API, MinIO, Caddy).
- DB schema + migrations for all P0 entities; seed demo school, 2 classes, 58 fictional children, consent flags.
- Flutter teacher app scaffold: theme, routing, login, roster list; parent app scaffold.
- Content: copy + adapt competency graph (NIPUN-anchored) from the previous build; **send it to education mentor for review**; begin authoring 12 core activities (borrowing, no-borrow, single-digit addition/sub, place value, tables, letter recognition, matras, word formation).
- Collect first golden notes (10) and photos (10).
- **Decide D1–D4** ([07](07_RISKS_AND_DECISIONS.md)).

### Day 2 — 26 Oct (Sun)
- Auth (JWT), class mgmt, roster import (typed/paste list; CSV optional).
- Mastery engine + unit tests (spec in [03 §3](03_DOMAIN_AND_DESIGN.md)); tap-checklist API + screen.
- Roadmap template path (from graph by grade) + roadmap review UI.
- Content: activity batch generation script (offline, A12) run for the 12 core + 6 next checkpoints; drafts queued for review.

### Day 3 — 27 Oct (Mon)
- **M2.** AI orchestrator skeleton + A1 voice-note extraction + Sarvam ASR adapter; confirm screen with chips; evidence committed → profile updates.
- Profile screen (status chips, timeline, low-confidence).
- Eval harness v1 for notes (20 labelled) → baseline F1.
- Roadmap frontend integration; group-change banner later.

### Day 4 — 28 Oct (Tue)
- A2 photo analysis + arithmetic override + retake guidance + confirm UI.
- A4 index photo → draft + matching step.
- Grouping engine + tests; class board UI (groups + unassessed + on-track).
- Content: photos golden set to 25; notes to 40.

### Day 5 — 29 Oct (Wed)
- **M3.** A7 planner + validator + template fallback; plan card UI (script, blackboard, TTS); intervention log ("did it").
- Reassessment flow (photo/tap/voice → confirm → status update → group movement).
- A3 classroom voice + scorer (word-diff, number normalisation); target selection UI (target words from the checkpoint's item bank).
- Eval: plans rubric export to mentor (20 scenarios).

### Day 6 — 30 Oct (Thu) — Parent app day 1
- Parent gate + consent + pack generation (`SessionPack`) + audio cache.
- Session runner: state machine, activity types (say word, match picture, word formation tap, number, solve & say, tap maths), record/judge/feedback, progress, stop rules.
- A9 tutor prompts v1 + A10 safety classifier; red-team v1.

### Day 7 — 31 Oct (Fri) — Parent app day 2 + hardening
- **M4.** Session end + summary + evidence sync; history; home→teacher summary (A8); teacher board shows "home" chips.
- Offline testing (airplane mode both apps); low-end Android testing (emulator 2 GB/RAM profile + a real device if available).
- Usability session 1 (2–3 teachers, remote) → fixes list.
- Evals: voice κ report; tutor persona report.

### Day 8 — 1 Nov (Sat morning/afternoon)
- **Freeze features at 14:00 IST.** Bug fixing, copy, Hindi strings, empty states only.
- Run full eval suite; commit report; export "AI proposals shown/edited/rejected" sample.
- Deploy to hosting; freeze deployment; **no commits after submission** (tech guidance).
- Record the 3-minute video on production deployment; write deck; README final check (`.env.example`, sample inputs, test credentials for both roles, offline matrix, services/keys list).
- **Submit by 20:00 IST** with buffer. Keep a local copy of the demo video.

### Day 9 — evening 1 Nov
- Buffer only. No feature work. Emergency fixes to deployment config only if judging requires (and note: evaluation uses frozen state).

---

## 4. Backlog (user stories, with acceptance criteria)

### Teacher
- **T-01 Login.** Given invite code + PIN → teacher sees classes. AC: works offline after first login; wrong PIN throttled.
- **T-02 Roster.** Teacher adds 30 children (name, roll). AC: duplicate roll blocked; consent checkbox per child with date; bulk paste.
- **T-03 Roadmap (photo).** Teacher photographs index → draft with chapters/subtopics → can rename/reorder/merge/delete → confirm. AC: failed vision → template path; confirmed roadmap immutable.
- **T-04 Tap checklist.** Teacher records ✓/⚠/✗ per child per checkpoint. AC: ≤ 20 s; offline; shows in profile immediately.
- **T-05 Voice note.** Teacher records a note; sees extracted chips; confirms. AC: absent children appear as absent, not wrong; ambiguous names require pick; ≤ 90 s.
- **T-06 Work photo.** Teacher photographs a page for a child; sees per-question verdicts; edits; confirms. AC: arithmetic overrides model; unreadable → retake; face detected → blocked.
- **T-07 Classroom voice.** Teacher picks a checkpoint + target items; records; sees per-word results; confirms. AC: low quality → retake, no evidence; ≤ 60 s.
- **T-08 Plan.** Teacher opens today's plan; sees 2–4 group cards; opens one; reads/hears activity + script + blackboard. AC: generated ≤ 12 s; offline shows cached/last plan; template fallback labelled.
- **T-09 Reassessment.** From a group card, quickly assess 1–3 children. AC: status improves and group changes with banner.
- **T-10 Profile.** Teacher sees status, history, misconception hypotheses, flags. AC: absent day distinguishable from not-started.
- **T-11 Privacy.** Teacher exports and deletes child/class data. AC: deletion confirmed; photos purged.

### Parent
- **P-01 Gate & consent.** Parent enters invite + child + phone, reads (and hears) consent, sets PIN. AC: no session without consent; child cannot open without PIN.
- **P-02 Start.** Child sees "आज का अभ्यास" with big button. AC: 2 taps from app open.
- **P-03 Session.** 6–10 activities; talk/tap; feedback after each attempt; ≤ 30 min. AC: after 2 wrong attempts moves on; works offline (tap mode); no unsafe line in red-team.
- **P-04 History.** Parent sees sessions, focus areas, streak. AC: no numeric scores shown by default.
- **P-05 Offline.** Pack downloaded; session completes offline; evidence syncs later. AC: no data lost.

---

## 5. Definition of done (each feature)

- Unit tests for code paths; integration test for API.
- Works on 2 GB Android emulator and Chrome mobile viewport.
- Hindi strings; empty/error/loading states.
- Logged (no PII), counted in analytics events (if consent).
- Eval gate passed for AI features; fallback path tested.
- Added to `docs/user_inputs.md` if it came from teacher feedback.

---

## 6. Quality and release process

- **Branching:** `main` protected; feature branches; PR review by the other developer.
- **CI:** lint, unit tests, extraction eval on fixtures (offline), safety suite, Flutter analyze/test.
- **Environments:** local (docker), staging (hosted), production (hosted, frozen for submission).
- **Secrets:** only in hosting env; `.env.example` lists names; no keys in repo; rotate after submission.
- **Data:** only fictional children in seed/demo.

---

## 7. Future roadmap (for the deck)

| Horizon | What |
|---|---|
| +1–3 months | Pilot with an NGO/school partner (2–3 schools), mentor review of graph and library, measure teacher time savings and reassessment movement; OTP/WhatsApp parent entry (one link, no install); Marathi/Assamese/Kannada content and ASR; offline on-device ASR experiment |
| +3–6 months | Multi-teacher schools, section sharing, teacher-authored activities with review workflow; state curriculum mapping (SCERT index pages); Diksha content ingestion |
| +6–12 months | CRP/head roll-up (anonymised patterns) feeding block reviews; integration with state student registry (UDISE+/SDMS) via APIs where permitted; outcome evaluation with an academic partner |
| Sustainability | Open-source core (hackathon incentive), government procurement via existing NIPUN/FLN portals, low per-class cost (~₹7/day compute + LLM) |

---

## 8. Submission checklist (from the tech guidance)

- [ ] Hosted web links (teacher, parent) reachable through the evaluation window; frozen
- [ ] APK + install steps (mic permission)
- [ ] Test credentials for every role (teacher, parent)
- [ ] README: setup, run locally, `.env.example`
- [ ] 3–5 sample inputs that show the system at its best (notes, photos, audio, parent session)
- [ ] Offline / low-network matrix stated
- [ ] External AI services and where keys are needed
- [ ] No secrets, no real personal data, no commits after deadline
- [ ] 3-minute video (YouTube unlisted/public)
- [ ] Deck with AI-usage layers, guardrails, offline design, user testing, roadmap
- [ ] Eval reports committed
