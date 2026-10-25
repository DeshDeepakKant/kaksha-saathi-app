# Evaluation results (current build)

Run date: 2026-10-24 · harnesses in `evals/` · raw JSON in `evals/reports/`.

```bash
cd backend
.venv/bin/python ../evals/run_extraction.py --mode rules
.venv/bin/python ../evals/run_planner.py
.venv/bin/python ../evals/run_scorer.py
.venv/bin/python -m pytest -q
```

## 1. Note extraction (deterministic fallback)

12 Hindi teacher notes, labels: absent rolls, per-child result + checkpoint.

| Metric | Value |
|---|---|
| Child-event precision | 1.00 |
| Child-event recall | 1.00 |
| Child-event F1 | 1.00 |
| Absence F1 | 1.00 |
| Wrong-child attributions | 0 |

**Reading this honestly.** This set was written by the team *and* the rules were tuned against it —
it demonstrates that the harness reports real errors (it caught two false positives and two
misses during development) but it is **not** a held-out estimate. The live Claude path
(`--mode live`) needs `ANTHROPIC_API_KEY`; it has not been scored against this set in this build.
Next step per `docs/05`: a held-out 30% + teacher-labelled notes.

## 2. Planner (template fallback)

6 scripted classroom scenarios (single group, foundation gap, literacy mix, single child,
all-on-track, whole class).

| Check | Result |
|---|---|
| Structurally valid plans | 6 / 6 |
| Every group appears exactly once | 6 / 6 |
| Activity exists in reviewed library and matches the checkpoint | 6 / 6 |
| Total time ≤ 25 minutes | 6 / 6 (max 25) |
| Reassessment question present for every group | 6 / 6 |

The harness caught a real defect on first run: three groups summed to 26 minutes. The template
planner now fits a budget and marks overflow groups as *deferred to tomorrow* with a note to the
teacher; the AI planner's validator rejects over-budget plans and falls back.

Mentor rubric (activity appropriateness, script clarity) is exported as CSV
(`evals/reports/planner-template-*-mentor-review.csv`) — **not yet scored**; that is an education
mentor task.

## 3. Reading scorer

20 human-labelled word-level items across letter, matra, word and number checkpoints.

| Metric | Value |
|---|---|
| Exact agreement | 1.00 |
| Cohen's κ | 1.00 |

The harness caught two real alignment defects: a later word could out-score the in-order word and
swallow the rest of the reading (κ 0.47 at that point), and single-letter confusions (स/श) scored 0
similarity. Both are fixed and covered by regression tests.

## 4. Test suite

`42 passed` — mastery rules (incl. home-evidence ceiling, recency override, evidence-volume gate),
prerequisite-root gap detection, grouping, template budgeting, arithmetic override, API flows
(note → confirm → board, voice low-quality path, planner fallback), parent session + safety
redirect, tenant isolation, data deletion.

## 5. What is still missing (and matters)

1. **Held-out extraction set + live-model numbers.**
2. **Mentor rubric scores** for plans and the competency graph edges.
3. **Teacher usability session** (task success, time-on-task, which proposals they edit) — the
   feedback log template is `docs/user_inputs.md` (to be filled during the pilot).
4. **Real child speech** (consented adult/child recordings) for the scorer calibration.
5. **Learning-outcome measurement** — not claimed anywhere in this build.
