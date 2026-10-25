import 'dart:js_interop';

@JS('KakshaSpeak')
external void _kakshaSpeak(JSString text);

/// Uses the bridge defined in web/index.html (SpeechSynthesis, hi-IN).
void speakOnWeb(String text) {
  try {
    _kakshaSpeak(text.toJS);
  } catch (_) {}
}
