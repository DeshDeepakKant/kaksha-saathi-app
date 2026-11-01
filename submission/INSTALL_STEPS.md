# Kaksha Saathi: Android apps and install steps

Two apps share one learning map. Both talk to the hosted server, so there is nothing to set up.

| File | Who uses it | Login |
|---|---|---|
| `KakshaSaathi-Teacher.apk` (about 60 MB) | Class teacher | School code `DEMO`, PIN `1234` |
| `KakshaSaathi-Parent.apk` (about 56 MB) | Parent at home | School code `DEMO`, roll `12`, phone `9876500000`, PIN `0000` |

Works on Android 7.0 or newer. Tested on a Moto g64 (Android 15).

## Install

1. On the Android phone, download the APK, either from this Drive folder or from the GitHub release
   https://github.com/DeshDeepakKant/kaksha-saathi-app/releases/tag/v1.0-submission
   (files `KakshaSaathi-Teacher.apk` and `KakshaSaathi-Parent.apk`).
2. Tap the downloaded file. If Android asks, tap **Settings** and turn on
   **Allow from this source** for your browser or Files app, then go back.
3. Tap **Install**. If Google Play Protect says the app is unknown, tap **More details → Install anyway**
   (the apps are not on the Play Store yet).
4. Open the app and log in with the details above.
5. When asked, allow the **microphone** (voice notes and Saathi sessions) and **photos/camera**
   (notebook photos). Nothing else is needed.

To try both sides on one phone, install both APKs; they are separate apps.

## Good to know

- The first request after a quiet spell can take up to a minute while the free server wakes up.
- The teacher app keeps working with no network: the board opens from the last saved copy and tap
  checks wait in an outbox until the phone is back online.
- AI features (voice note reading, photo reading, plans, Saathi's replies) need a connection. If the AI
  is unavailable or the daily AI budget runs out, the server falls back to rule-based plans and
  checks instead of failing. The parent voice session needs the phone to be online; without a
  network it says so and offers **Try again**.
- All children in the demo school are fictional.

See `SAMPLE_INPUTS.md` for five things to try, with what you should see.
