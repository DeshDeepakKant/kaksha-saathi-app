# English as a built-in subject (like Hindi): contract (v1)

Goal: **English** becomes a third built-in subject next to Maths (`numeracy`) and Hindi (`literacy`):
subject key **`english`**, names ("English", "अंग्रेज़ी"), its own lesson nodes, template syllabus per grade,
activities, probes, level-check ladder, tips, voice-session practice, and **demo data everywhere the Hindi
and Maths demos have it** (board, follow-ups, "did it work", level check, child profiles, parent journey,
insights). Everything is for children learning English as a second language in classes 1–3.

Rules (all agents): see CLAUDE.md. Code decides status; reviewed content only; additive API changes; Hindi
and Maths behaviour, ids and demo data must not change (existing tests keep passing); no new frameworks;
UI text via tr()/trf(); child names fictional; keep the gitignored `backend/.env` out of everything.
English classroom content is written **in English** (it is the thing being taught); fields named `*_hi`
keep their convention "classroom-language text", so English activities store English in `steps_hi`,
`title_hi`, `materials_hi`, `blackboard_hi` and carry `"language": "en"`. Hindi text for the teacher's
Hindi UI goes in `title_hi` only where a `title_en` + `title_hi` pair already exists for graph nodes.

## Lesson nodes (competency_graph.json) — subject `english`, language `en`, `nipun_ref` generic
Grade 1: `E.G1.letter_names` (recognise A–Z, capital and small), `E.G1.letter_sounds` (say each letter's sound),
`E.G1.oral_vocab` (name common things: objects, colours, body parts), `E.G1.build_cvc` (join sounds into a
3-letter word: c-a-t → cat), `E.G1.read_cvc` (read simple 3-letter words), `E.G1.sight_words` (read common
words: is, the, my, and, to), `E.G1.read_short_sent` (read sentences of 3–5 words).
Grade 2: `E.G2.blends_digraphs` (sh, ch, th, bl, st, tr words), `E.G2.spell_words` (build and spell 4–5 letter
words), `E.G2.read_sentences` (read sentences smoothly), `E.G2.make_sentence` (make a sentence from given
words), `E.G2.simple_comp` (answer simple questions about a short text).
Grade 3: `E.G3.read_passage` (read a short passage with meaning), `E.G3.sentence_formation` (say/write
sentences using given words), `E.G3.word_types` (naming, doing, describing words), `E.G3.story_comp`
(understand a short story and tell it back).
Prerequisites: letter_names→letter_sounds→build_cvc→read_cvc→{sight_words, read_short_sent, blends_digraphs};
oral_vocab: none; build_cvc→spell_words; read_short_sent→read_sentences; {read_short_sent, oral_vocab}→
make_sentence; read_sentences→simple_comp; read_sentences→read_passage; make_sentence→{sentence_formation,
word_types}; {simple_comp, read_passage}→story_comp. Each node: `chapter`, `title_en`, `title_hi`,
`assess_via`, `item_types`, `misconceptions` (2–3 snake_case ids, e.g. confuses_b_d, confuses_p_q,
says_letter_name_not_sound, guesses_from_first_letter, skips_small_words), `nipun_ref`.

## Voice-session stage mapping for English (lang "en")
letter → `E.G1.letter_names` (say_sound items → `E.G1.letter_sounds`); word_build → G1 `E.G1.build_cvc`,
G2 `E.G2.spell_words`; word_read → G1 `E.G1.read_cvc`, G2 `E.G2.blends_digraphs`; sentence_build → G1/G2
`E.G2.make_sentence`, G3 `E.G3.sentence_formation`; reading → G1 `E.G1.read_short_sent`, G2
`E.G2.read_sentences`, G3 `E.G3.read_passage`. Every English item in content/voice_bank.json gets that
`checkpoint_id`.

## Level-check ladder (content/level_check.json → subjects.english)
Same shape as literacy, keys `letter`, `word`, `sentence`, `story`, checkpoints `E.G1.letter_names`,
`E.G1.read_cvc`, `E.G1.read_short_sent`, `E.G2.read_sentences`; items copied from reviewed English
voice-bank items (`from` ids); titles "English reading level"/"अंग्रेज़ी पढ़ने का स्तर".

## Owners
**Content agent** (only `content/**` and `backend/tests/test_english_content.py`): the 16 nodes above;
`activities.json` +9 English activities (`act_en_*`, `language:"en"`, each lists its `checkpoint_ids`, ≥1 per
grade-1/2/3 gap node, with `reassessment`); `probes.json` +5 (letter_names, letter_sounds, read_cvc,
read_short_sent, make_sentence); `practice_items.json` +English items for letter_names/read_cvc/read_short_sent;
`level_check.json` English ladder; `voice_bank.json` set `checkpoint_id` on every `lang:"en"` item per the
stage mapping; `misconception_tips.json` + `activity_home.json` entries (with both `_hi` and `_en` text)
for the English nodes/misconceptions, same schema as existing entries. Do not touch Hindi/Maths entries.
Run the existing content validators/tests; add tests that every English node has prerequisites in the
graph, activities cover every gap node, ladder checkpoints exist, voice-bank items have valid ids.
**Backend agent** (backend/app/**, backend/tests/**, docs/DEMO_SCRIPT.md): register `english`: BUILTIN_NAMES
(("English","अंग्रेज़ी")), ALIASES (english/angrezi → english), `content.subjects`, template roadmap per
grade (check `template_roadmap`), the reserved-key check for custom subjects, `subject_names`; everything
that special-cases `literacy` where English must behave the same (level_check ladder/`ladder_in`/`demo_seed`,
voice session `_syllabus`/stage→checkpoint mapping for lang "en" using the built-in subject instead of a
custom "english" subject — keep the old custom-subject path working if a school has one —, parent
insights/journey/tips for subject `english`, evidence from English voice sessions landing on `E.*` ids,
library/localization must not translate English-subject text and must fall back to `title_en` for missing
titles); the **demo seed** (`seed.py`, bump `SEED_VERSION`): English roadmaps for both classes; class 2A
English evidence with deliberate structure (groups at letter sounds / 3-letter words / sentences, a few on
track, two with little evidence, mixing teacher_tap, class_voice, photo_work, home sources); a **past English
group-session history** (plans + GroupSession + InterventionLog, like the borrowing story) so Follow-ups and
"Did it work?" show re-check / not moving / missed / not checked for English with activity ids `act_en_*`;
English level checks via `level_check.demo_seed`; class 3A light English history; the demo parent child
(roll 12): an English journey (letters learned over weeks, one celebration 3 days ago, an improving
moment) so the parent app's English tab has real content; keep all existing demo data unchanged. Tests for
all of it (fresh-database runs).
**Flutter agent** (apps/*/lib only, no backend): every hard-coded Maths/Hindi toggle, label, icon and title
gets English (`subject == 'english'`): teacher `board_screen.dart` (fallback list, labels, icon),
`level_check_screen.dart` (3-way toggle; start on the passed subject), `level_screen.dart`,
`outcomes_screen.dart`, `group_plan_screen.dart` title, `syllabus_screen.dart` defaults, `voice_report_screen.dart`
(subject for English sessions), `roster_screen.dart` entry; parent `journey_screen.dart` (3rd chip) and
`api_insights.dart` doc/usage. Labels: tr('English','अंग्रेज़ी'); icon `Icons.translate_rounded`. Add any new
UI strings through `tr()` and regenerate translations: `python3 tool/l10n_strings.py extract && python3
tool/l10n_translate.py` (ANTHROPIC_API_KEY is in the environment; copy tool/i18n/cache from
`/home/anya/.claude-squad/worktrees/anya/lang-provider/tool/i18n/cache` first so only new strings cost
anything); keep both l10n.dart copies identical. `flutter analyze` clean in both apps; `flutter test`.
