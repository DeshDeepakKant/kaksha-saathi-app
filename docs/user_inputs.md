# User inputs and changes made (feedback log)

The hackathon asks for evidence that user feedback was collected and **incorporated**. Each row is one
piece of feedback, what changed because of it, and the commit that made the change.

**Where this feedback comes from.** So far it comes from the team's own use of the apps in both roles
(teacher and parent) on a real Android phone against the live server, and from the project lead's
reviews of each build. It is not from outside teachers or parents. Sessions with them are planned
below; when they happen they go in this same table.

| Date | Who (role, no names) | What they said or found | Change made | Where |
|---|---|---|---|---|
| 2026-10-30 | Team member testing as a parent, Moto g64, live server | With the network off the app showed a raw error with the server URL and no Retry; the word the child had to read was squeezed out of view while listening; the PIN keyboard did not submit; English lines were read with the Hindi voice; reports showed percentages | Friendly bilingual errors with a Retry; the item gets at least 40% of the screen; PIN submits; English read with an English voice; reports show counts | `934e4ee` |
| 2026-10-30 | Team member testing as a teacher, real phone | A notebook photo taken on the phone was read with the wrong image type and failed | The server now sends Claude the real image type, not the label on the upload | `69e5b20` |
| 2026-10-30 | Team member testing both apps on the phone | After a login expired, or came from another server, the apps showed "invalid token" or stale saved data | Any 401 now skips the offline copy and sends the user back to sign-in in both apps | `cbc3621` |
| 2026-10-30 | Team, checking the live deployment | The demo school failed to rebuild on the server (a database link blocked it) | Reseeding now removes the school's saved preferences first; regression test added | `5c845f1` |
| 2026-10-31 | Project lead, reviewing a build on the phone | "the demo credential still in ui" | The demo login details are gone from both login screens; new app icons and names in the same change | `f66164a` |
| 2026-10-31 | Project lead | "use gnani best model of each language as a default instead of sarvam, keep sarvam as backup or second choice" | Gnani is the default voice service, Sarvam second, per language; the setting is per user | `5a3fb39` |
| 2026-11-01 | Project lead | "use sonnet 5.5 for it" (reading notebook photos) | Photo reading now runs on Claude Sonnet 5.5; the AI gateway asks for the tool without forcing it, because that model rejects forced tool choice | `8f8ef5f` |
| 2026-11-01 | Project lead | Rename the apps "Kaksha Sathi" (teacher) and "Kaksha Sathi Parents" | Launcher names, web names, in-app names and translation tables changed | `3c178b1` |
| 2026-11-01 | Team member testing as a teacher, Moto g64, release APKs | In a photo of borrowing sums the AI marked 4 right answers wrong; the teacher corrected them before pressing Confirm | The correction path worked. The cause is logged: the arithmetic check skips a sum when the AI adds bracketed working. **Fix queued, not changed yet** | roadmap slide |
| 2026-11-01 | Same run | One offline screen showed a raw network error; the tutor once waited about 80 seconds; the cost ledger's budget-left figure did not update | Logged. **Fixes queued, not changed yet** | roadmap slide |

In the same run the in-app AI ledger showed 8 suggestions: 2 confirmed as they were, 3 edited by the
teacher and 0 rejected. The edits are what exposed the photo sum-check gap above.

## Planned prompts for the first sessions

1. Show the class board. *What would you do next, without reading the instructions?*
2. Which of the four capture paths would you actually use after class: voice note, photo, tap list, or nothing?
3. When the AI lists children, what would make you distrust it?
4. Open the plan card. *Could you run this tomorrow in 10 minutes? What is missing?*
5. The parent app: *would you open this at home? Who would press the buttons?*
6. Privacy: *what would you not want recorded about a child?*

Record: task success, time on task, which proposals were edited or rejected, and verbatim quotes.
The in-app counter (`GET /v1/ai_activity`) provides the edit/reject numbers without extra work.
