# 3-minute demo script (for the submission video)

Record against the frozen deployment. Have a second tab with the seeded demo data open in case
you need to restart. Times are cumulative.

| Time | Screen | Say / do |
|---|---|---|
| 0:00–0:15 | Landing page | "One teacher, 30 children, three grades. She knows the syllabus — not where each child actually is. Kaksha Saathi keeps that map and turns it into tomorrow's lesson." |
| 0:15–0:35 | Teacher → board | "She opens her class. No new test: today's groups are already computed from evidence she collected during teaching." Point at the three groups and the two children marked *assessment pending* (absent today). |
| 0:35–0:55 | Group card → plan | Open the **हासिल (carrying)** group. "Five children, one shared gap, eight minutes, materials she has, a blackboard line she can copy." Tap the speaker: Hindi read-aloud. |
| 0:55–1:20 | Capture → note | Back → **साक्ष्य जोड़ें** → voice tab → type (or speak) `आज उधार वाला घटाव कराया। मीना को उधार समझ नहीं आया। अर्जुन ने सही किया। प्रिया नहीं आई।` Show the chips: one absent, one struggling, one correct — each with the quoted words. "Nothing is saved until she confirms." |
| 1:20–1:35 | Confirm → board changed | Confirm. "Meena moves into the borrowing group; Arjun leaves it; Priya is marked absent, not weak." |
| 1:35–1:55 | Child profile | Open Meena. Show status chips, the misconception chip *"smaller minus larger"*, the timeline, and the **2-minute probe** button. "The probe uses a prepared script — the teacher only reads it aloud." |
| 1:55–2:10 | Work photo (optional) | Take a photo of a written subtraction page (have one ready). Show per-question verdicts and that `52 − 28 = 36` is computed by code, not by the model. |
| 2:10–2:35 | Parent app | Switch to the parent app. Sign in (DEMO / 12 / phone / 0000). Show the focus list derived from school evidence → start the session → the owl's line, the big mic, a tap question. "The AI writes the words; the app decides the path, judges the answer, and stops after two tries." |
| 2:35–2:50 | Offline | Turn the network off. Start a session from the cached pack. "No signal: same session, tap fallback, evidence syncs later." |
| 2:50–3:00 | Close | "Diagnosis, grouping, intervention, home practice, reassessment — one loop, one child-level map. Claude reads the messy evidence and writes the language; code decides the status. $0.08 per class per day." |

## English (30-second add-on, or swap in for the carrying beat)

English is the third subject next to Maths and Hindi, with its own lessons, activities and demo data. The teacher
app's subject toggle shows **Maths / Hindi / English** on the board, follow-ups, "Did it work?" and level check.
All numbers below are for the fictional class **2A** after a fresh seed (the live DEMO school rebuilds itself once
on the first boot after deploy); they come from the seed and do not change between runs.

| Where | Switch to English and show | The numbers |
|---|---|---|
| Board | Four groups, one per gap: **letter sounds** (rolls 3-6), **3-letter words** (7-11), **short sentences** (15-19), **blends and digraphs** (12, 20-22). "Same loop, a different subject." | 8 on track; 4 *assessment pending* (rolls 1-2 absent today, rolls 13-14 have no English check yet) |
| Follow-ups | **Rolls 3 and 4** are *stuck* on letter sounds (three lessons, still behind); **roll 10** *missed* the first 3-letter-words lesson; **rolls 6, 9-11 and 18-19** *need a re-check* after their last lesson; rolls 13-14 are *not checked* | recheck 6, stuck 2, missed 1, not checked 2 |
| Did it work? | Seven past lessons, every activity an `act_en_*` card. Open *letter sounds*: some children moved up, some did not, one was never re-checked. "It tells her which activity moved children." | 7 sessions, mix of up / same / not re-checked |
| Level check | English reading level (letters, words, sentences, story). | 18 of 30 checked, 11 moved up since the first week |
| Parent app (DEMO / **12** / 9876500000 / 0000), *Journey* tab, English chip | **Kavita**: letters, naming words, 3-letter words learned over a month (growth line goes 0 to 5 stars); **Letter sounds learned 3 days ago** is the celebration; Blends and digraphs is "getting better" with a home tip for the mistake. | 5 lessons learned, 1 in progress, next steps listed |
| Voice session | Start a session in **English**: Saathi practises the letter and word lessons; correct answers land on the child's English lessons (never the Hindi map). | |

Maths and Hindi demo data is unchanged; the parent's weekly summary and moments simply gain English entries.
Reset: `make seed`. English needs the English content files (`content/` English nodes); without them the app runs as before and the English demo is skipped.

## Things to have ready

- A photographed notebook page (subtraction with borrowing, one deliberate mistake).
- A quiet room if you demo real speech; otherwise use typed input (still fully functional).
- The reset command, in case the DB is messy: `make seed` (or delete `backend/kaksha_dev.db` and restart).
- A recorded backup of this exact run — the tech guidance asks for a 2–3 minute fallback video.

## What NOT to claim

- No learning-outcome numbers from a real classroom (none measured yet).
- Do not call the demo children real; say "fictional demo class".
- If a key is missing on the demo host, say "deterministic fallback" rather than implying model output.
