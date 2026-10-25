# Parent app (Flutter Web PWA + Android)

```bash
flutter pub get
flutter run -d chrome --dart-define=API_BASE=http://localhost:8000
flutter build web --release --base-href /parent/ --dart-define=API_BASE=https://your-host
flutter build apk --release --dart-define=API_BASE=https://your-host
```

Start `backend/` first; demo credentials are in the root README (code `DEMO`, roll `12`,
phone `9876500000`, PIN `0000`).

## Design rules

- The parent gate (phone + PIN) is the only way in; the child never sees an account screen.
- A session is a **harness-driven sequence** of 6–10 activities. The model writes one short line per
  turn; the app decides the path, judges each answer, and moves on after two attempts.
- No mic / no network ⇒ the same sequence continues: the model word is spoken aloud (browser TTS),
  the turn is marked *practised* (never *correct*), and evidence syncs later.
- Child-safety: the server classifies every utterance; distress or personal questions stop the
  activity and show a "tell a grown-up" card.

Files: `lib/screens/gate_screen.dart` (consent + login), `home_screen.dart` (focus + streak),
`session_screen.dart` (runner + offline mirror of the harness), `history_screen.dart`.
