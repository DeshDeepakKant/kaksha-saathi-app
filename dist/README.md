# Build artefacts

| File | What |
|---|---|
| `kaksha-teacher.apk` | Teacher app, release build, `API_BASE=https://demo.kakshasaathi.in` |
| `kaksha-parent.apk` | Parent app, release build, same base |

Rebuild against your own host:

```bash
cd apps/teacher && flutter build apk --release --dart-define=API_BASE=https://your-host
cd apps/parent  && flutter build apk --release --dart-define=API_BASE=https://your-host
```

Install: allow "install unknown apps" for the file manager, then open the APK. Both apps need
`RECORD_AUDIO` for voice; without it they fall back to tap/typed input.
