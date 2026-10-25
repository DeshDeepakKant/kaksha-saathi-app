import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// Hindi read-aloud for plans and probes.
/// - Web: browser SpeechSynthesis (via the injected channel in web/index.html).
/// - Android: on-device TTS (works offline once Hindi is installed) via flutter_tts.
class Speak {
  static final _tts = FlutterTts();
  static bool _init = false;

  static Future<void> say(String text) async {
    if (!_init) {
      _init = true;
      await _tts.setLanguage('hi-IN');
      await _tts.setSpeechRate(0.42);
      await _tts.setPitch(1.0);
      _tts.setErrorHandler((_) {});
    }
    try {
      await _tts.stop();
      await _tts.speak(text);
    } catch (_) {
      try {
        SystemChannels.platform.invokeMethod('KakshaSpeak', text);
      } catch (_) {}
    }
  }
}
