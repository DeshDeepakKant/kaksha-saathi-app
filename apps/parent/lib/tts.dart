import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'speech_web.dart' if (dart.library.js_interop) 'speech_js.dart';

/// Saathi's voice for the voice session.
/// - Android: on-device TTS (hi-IN / en-IN; works offline once the voice is installed).
/// - Web: browser SpeechSynthesis through flutter_tts, falling back to the web/index.html bridge.
///
/// [say] completes when the line has been spoken (or was stopped), so the session can start the
/// mic only after Saathi stops talking. Nothing here ever throws.
class Speak {
  Speak._();

  static final _tts = FlutterTts();
  static bool _ready = false;
  static String? _voice;
  static Completer<void>? _current;
  // Completion/cancel events carry no id; only trust them once the current line has started,
  // so a late "cancelled" from the previous line cannot end the next one early.
  static bool _started = false;

  static Future<void> _init() async {
    if (_ready) return;
    _ready = true;
    try {
      await _tts.awaitSpeakCompletion(true);
      // flutter_tts rates differ per platform: ~0.45 on Android is a slow, clear pace for
      // children; the browser scale is 1.0 = normal.
      await _tts.setSpeechRate(kIsWeb ? 0.85 : 0.45);
      await _tts.setPitch(1.05);
      await _tts.setVolume(1.0);
      _tts.setStartHandler(() => _started = true);
      _tts.setErrorHandler((_) => _started ? _finish() : null);
      _tts.setCompletionHandler(() => _started ? _finish() : null);
      _tts.setCancelHandler(() => _started ? _finish() : null);
    } catch (_) {}
  }

  static void _finish() {
    final c = _current;
    if (c != null && !c.isCompleted) c.complete();
  }

  static String _code(String lang) => lang == 'en' ? 'en-IN' : 'hi-IN';

  /// Whether the device has a voice for [lang] (`hi` / `en`). Unknown counts as available.
  static Future<bool> hasVoice(String lang) async {
    if (kIsWeb) return true;
    try {
      await _init();
      final ok = await _tts
          .isLanguageAvailable(_code(lang))
          .timeout(const Duration(seconds: 3));
      return ok != false;
    } catch (_) {
      return true;
    }
  }

  /// Speaks [text] in [lang] (`hi` or `en`) and waits until it ends or [stop] is called.
  static Future<void> say(String text, [String lang = 'hi']) async {
    final t = text.trim();
    if (t.isEmpty) return;
    await stop();
    final done = Completer<void>();
    _current = done;
    // Never wait forever on an engine that does not report completion.
    final limit = Duration(milliseconds: 4000 + t.length * 140);
    try {
      await _init();
      final code = _code(lang);
      if (_voice != code) {
        await _tts.setLanguage(code);
        _voice = code;
      }
      if (done.isCompleted) return; // stopped while setting up
      _started = false;
      void end([_]) {
        if (!done.isCompleted) done.complete();
      }

      // On Android the future resolves when the line ends (awaitSpeakCompletion); on the web
      // it may resolve at once, so there the start/completion handlers decide.
      unawaited(_tts.speak(t).then((_) => kIsWeb ? null : end(), onError: end));
    } catch (_) {
      if (kIsWeb) speakOnWeb(t);
      // Give the fallback (or silence) roughly the time the line would take.
      await Future.any([
        done.future,
        Future.delayed(Duration(milliseconds: 600 + t.length * 70)),
      ]);
      if (!done.isCompleted) done.complete();
      return;
    }
    await done.future.timeout(limit, onTimeout: () {});
    if (identical(_current, done)) _current = null;
  }

  /// Stops speech now; a pending [say] completes.
  static Future<void> stop() async {
    _finish();
    _current = null;
    _started = false;
    try {
      await _tts.stop();
    } catch (_) {}
  }
}
