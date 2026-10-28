# 30-minute voice learning session: contract

A child talks with Saathi for about 30 minutes. Saathi climbs a reading ladder, adapts every next
question to the last answer, gives up to 5 tries per question with growing hints, keeps a live
transcript, and ends with a report that the parent and teacher apps both show.

Principles (from CLAUDE.md): **code judges, Claude talks.** Right/wrong on reading and word
building is deterministic (`app/speech/assess.py`). Claude generates fresh questions within the
class syllabus (validated by code, with a reviewed fallback bank), writes Saathi's hints and the
report narrative, and only *refines* the judgement of open answers (sentence making, comprehension).
Every AI path has a deterministic fallback so the session runs with no key. Child names never go
to the model (use `{name}` placeholders, filled in by code).

Shared constants and shapes: `backend/app/services/voice_types.py` (STAGES, KINDS, MAX_ATTEMPTS=5,
TARGET_MINUTES=30, STAGE_CHECKPOINTS, Assessment).

## Ladder
`letter` → `word_build` → `word_read` → `sentence_build` → `reading` (short sentences, then a
paragraph followed by 1–2 comprehension questions). Same ladder for Hindi (`hi`) and English (`en`).

## Item (dict)
```
{"id": str, "stage": STAGE, "kind": KIND, "lang": "hi"|"en", "checkpoint_id": str|None,
 "prompt": str,                       # what Saathi says to ask it (may contain {name})
 "display": {"text": str?,            # big text to read (letter / word / sentence / paragraph)
             "tiles": [str]?,         # build_word: the pieces to blend, e.g. ["क","म","ल"]
             "words": [str]?,         # make_sentence: words to use
             "question": str?},       # answer_question
 "target": str|None,                  # what counts as right (None for make_sentence)
 "accept": [str],                     # extra accepted readings/answers
 "required_words": [str],             # make_sentence
 "keywords": [str],                   # answer_question fallback check
 "max_record_s": int,                 # letter 4, word 5, sentence 8, paragraph 30, answers 10
 "difficulty": 1|2|3, "source": "ai"|"bank",
 "followups": [item]}                 # read_paragraph -> its answer_question items
```

## Python interfaces
`app/speech/assess.py` (assessment agent)
- `assess_reading(target, transcript, lang, duration_s=None) -> Assessment` (letters, words,
  sentences, paragraphs; per-word statuses, grapheme-level errors like `श→स`, missing matra; wcpm
  for paragraphs). Empty transcript -> `silent`.
- `assess_word_build(target_word, transcript, lang, accept=()) -> Assessment`
- `assess_sentence_build(required_words, transcript, lang) -> Assessment` (code check: words used,
  >= 3 words; Claude may refine via `voice_tutor.evaluate_open`)
- `assess_answer(keywords, transcript, lang, accept=()) -> Assessment` (fallback for comprehension)
- `assess_item(item, transcript, duration_s=None) -> Assessment` (dispatch by kind)

`app/services/voice_report.py` (assessment agent)
- `build_report(*, lang, started_at, ended_at, turns: list[dict], items: dict[str, dict], content) -> dict`
  deterministic report (schema below, `narrative` empty).

`app/ai/voice_tutor.py` (AI agent)
- `generate_items(db, *, school_id, lang, grade, stage, topics, avoid, weak_sounds, n=6) -> (list[item], "ai"|"bank")`
  `topics` = `[{checkpoint_id, title_hi, title_en, custom}]` from the class syllabus; validated,
  safety-filtered, falls back to `content/voice_bank.json` via `app/services/voice_bank.py`.
- `tutor_line(db, *, school_id, lang, situation, item, assessment, attempt) -> (text, "ai"|"fallback")`
  situations: `greet, intro_item, praise, retry_hint, move_on, stage_up, stage_down, break, silent, wrap_up`.
  Hints escalate with `attempt` (1..5): repeat, model it, break into sounds, say it together, last try.
  Templated for speed; Claude only where it adds value (specific hint from `assessment.errors`, stage
  changes). Must stay short (<= 2 sentences), kind, child-friendly, in `lang`.
- `evaluate_open(db, *, school_id, lang, item, transcript, code: Assessment) -> Assessment` (refines
  make_sentence / answer_question; returns `code` unchanged on any failure).
- `write_narrative(db, *, school_id, lang, report) -> (dict, "ai"|"fallback")` -> the `narrative`
  and `next_steps` fields below.

`app/services/voice_session.py` (session agent): the engine. Owns state, adaptivity, attempts,
timer, transcript, evidence, report assembly; calls the three modules above.

## Adaptivity rules (engine)
- Start one stage below the child's lowest non-on-track literacy checkpoint (warm-up), at least `letter`.
- `correct` on try 1 or 2 counts as a success. 2 successes in a row in a stage -> harder item, 3 -> next stage.
- Not correct -> same item again with the next hint, up to 5 tries; `close` is encouraged ("almost").
- After 5 tries -> move on, record the exact difficulty (item, heard, errors), give an easier item next.
  2 failed items in a row -> step down a stage (never below `letter`).
- `silent` (nothing heard / ASR failed) does not use a try; after 3 silent turns in a row Saathi checks in.
- Weak sounds/letters seen in errors are fed to `generate_items(weak_sounds=...)` so practice targets them.
- A short break line at ~15 min; wrap-up at 30 min (or when the parent ends). Items are generated in
  batches per stage and refilled before they run out, so a turn never waits on generation if avoidable.
- Every finished item writes one Evidence row for its checkpoint (`source="home_voice"`, correct on
  try 1–2, partial on 3–5, incorrect after 5). Never for `silent`.
- Child speech goes through `features.classify_child_input` for open answers; distress/personal ->
  the existing safety redirect, logged on the session.

## HTTP API (router `app/api/voice.py`, all `/v1`)
Parent (parent JWT):
| Route | Body | Returns |
|---|---|---|
| `POST /parent/voice/sessions` | `{lang:"hi"|"en"}` | `Session` |
| `POST /parent/voice/sessions/{id}/turn` | multipart: `meta` JSON `{item_id, client_turn_id, transcript?: str, duration_s?: float}`, optional `audio` (WAV) | `Turn` |
| `POST /parent/voice/sessions/{id}/skip` | `{item_id}` | `Turn` (move on without judging; recorded as skipped) |
| `POST /parent/voice/sessions/{id}/end` | `{reason?: "time_up"|"parent_stop"}` | `Report` |
| `GET /parent/voice/sessions` | | `[{id, lang, started_at, minutes, items, accuracy, highest_stage, status}]` |
| `GET /parent/voice/sessions/{id}` | | `{session: Session, report: Report|null}` |

Teacher (teacher JWT, tenant-checked):
| `GET /children/{child_id}/voice_sessions` | | same list as above |
| `GET /voice_sessions/{id}` | | `{session: Session, report: Report|null}` |

`Session` = `{id, lang, status:"active"|"ended", started_at, elapsed_s, target_minutes, stage,
 item: Item|null, attempt, transcript: [Line], tutor: {text, lang}}`
`Line` = `{role:"tutor"|"child", text, at, item_id?, verdict?, words?: [{target,heard,status}]}`
`Turn` = `{verdict, score, heard, words, errors, attempt, attempts_left, tutor:{text, lang},
 next_item: Item|null (same id when retrying), stage, stage_changed, elapsed_s, remaining_s,
 done (true when time is up), transcript_append: [Line], safety_flag?: str, asr: "asr"|"provided"|"silent"|"failed"}`
`Report` = 
```
{"session_id", "lang", "minutes", "items_attempted", "first_try", "after_retry", "failed", "skipped",
 "accuracy", "highest_stage", "stages": [{stage, attempted, correct, failed}],
 "strengths": [{en, hi}], "weaknesses": [{en, hi}],
 "mistakes": [{item, stage, heard, attempts, errors: [str]}],
 "difficult_words": [str], "difficult_sounds": [{sound, confused_with, count}],
 "topics_attention": [{checkpoint_id, title_hi, title_en, reason_en, reason_hi}],
 "fluency": {"wcpm": float|null, "paragraphs": int},
 "narrative": {"parent_hi", "parent_en", "teacher_en", "teacher_hi"}, "narrative_status": "ai"|"fallback",
 "next_steps": {"hi": [str], "en": [str]}}
```
Item `target`/`accept`/`keywords` are never sent to the app for `build_word`, `answer_question`
(the child must not see the answer); reading items show `display.text` (the thing to read).

## Apps
- Parent app: "30-minute voice session with Saathi" card on Home -> language choice -> session
  screen (TTS speaks Saathi, auto-listens with end-of-speech detection, big display of the current
  item, live transcript, timer, pause/stop) -> report screen; past sessions list.
- Teacher app: child profile gets a "Voice sessions" card -> report screen with transcript.
