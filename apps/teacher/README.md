# Teacher app (Flutter: Android + Web)

```bash
flutter pub get
flutter run -d chrome --dart-define=API_BASE=http://localhost:8000
flutter run --dart-define=API_BASE=http://10.0.2.2:8000     # Android emulator → host
flutter build web --release --base-href /teacher/ --dart-define=API_BASE=https://your-host
flutter build apk --release --dart-define=API_BASE=https://your-host
```

| Screen | File | What it does |
|---|---|---|
| Login | `lib/screens/login_screen.dart` | school code + PIN; token cached for offline start |
| Board | `lib/screens/board_screen.dart` | today's groups, on-track, assessment-pending; subject tabs |
| Plan | `lib/screens/group_plan_screen.dart` | per-group activity, Hindi script, blackboard text, reassessment, TTS, "done" |
| Capture | `lib/widgets/capture_sheet.dart` | tap checklist (works offline), voice/typed note → chips → confirm |
| Child profile | `lib/screens/level_screen.dart` | status map, misconception hint, evidence timeline, 2-minute probe |
| Settings | `lib/screens/settings_screen.dart` | AI-proposal counters, content status, privacy, logout |

Offline: reads are cached with `offline: true`; captures that need the network say so. The mic uses
the `record` plugin (AAC on Android, Opus on web); without permission the app falls back to typing.
