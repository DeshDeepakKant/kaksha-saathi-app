import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'api.dart';
import 'speech_web.dart' if (dart.library.js_interop) 'speech_js.dart';

/// Saathi's voice.
/// - First the server voice (`POST /v1/speech/tts`, the parent's voice service), played with
///   audioplayers. Recent lines are kept in memory, so a replay is instant.
/// - When the server can't speak the language (204), is older than that endpoint (404), or is
///   unreachable: the phone's voice via flutter_tts (Android on-device TTS, browser
///   SpeechSynthesis on the web, then the web/index.html bridge).
///
/// [say] completes when the line has been spoken (or was stopped), so the session can start the
/// mic only after Saathi stops talking. Nothing here ever throws.
class Speak {
  Speak._();

  static final _tts = FlutterTts();
  static final _player = AudioPlayer();
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
    try {
      _player.onPlayerComplete.listen((_) => _finish());
    } catch (_) {}
  }

  static void _finish() {
    final c = _current;
    if (c != null && !c.isCompleted) c.complete();
  }

  /// Phone-voice (BCP-47) code for one of our language codes: `en` → en-IN, `or` → or-IN,
  /// `mr` → mr-IN, …; empty means Hindi.
  static String bcp47(String lang) => lang.isEmpty ? 'hi-IN' : '$lang-IN';
  static String _code(String lang) => bcp47(lang);

  // ---- server voice

  static final _cache = <String, ({Uint8List audio, String? mime})>{};
  // Per language, after a 204 or a failure.
  static final _skipUntil = <String, DateTime>{};
  static bool _serverMissing = false; // the server has no /v1/speech/tts

  static bool _serverLikely(String lang) {
    if (!Api.i.signedIn || _serverMissing) return false;
    final until = _skipUntil[lang];
    return until == null || DateTime.now().isAfter(until);
  }

  static Future<({Uint8List audio, String? mime})?> _serverAudio(
    String t,
    String lang,
  ) async {
    if (!_serverLikely(lang)) return null;
    final key = '${Api.i.prefs?['voice_provider'] ?? ''}|$lang|$t';
    final hit = _cache.remove(key);
    if (hit != null) return _cache[key] = hit;
    final r = await Api.i.speechTts(t, lang);
    final now = DateTime.now();
    switch (r.status) {
      case 200:
        final v = (audio: r.audio!, mime: r.mime);
        _cache[key] = v;
        if (_cache.length > 24) _cache.remove(_cache.keys.first);
        return v;
      case 404 || 405:
        _serverMissing = true;
      case 204:
        // No voice service speaks it now; look again later (settings may change).
        _skipUntil[lang] = now.add(const Duration(minutes: 10));
      case 401:
        break;
      default:
        _skipUntil[lang] = now.add(const Duration(minutes: 1));
    }
    return null;
  }

  /// Whether Saathi can speak [lang]: the server voice is expected to work, or the phone has a
  /// voice for it. Unknown counts as available.
  static Future<bool> hasVoice(String lang) async {
    if (kIsWeb || _serverLikely(lang)) return true;
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

  /// Speaks [text] in [lang] (any content language code, e.g. `hi`, `en`, `mr`) and waits until
  /// it ends or [stop] is called.
  static Future<void> say(String text, [String lang = 'hi']) async {
    final t = text.trim();
    if (t.isEmpty) return;
    await stop();
    final done = Completer<void>();
    _current = done;
    await _init();
    final audio = await _serverAudio(t, lang);
    if (done.isCompleted) return; // stopped while fetching
    if (audio != null) {
      try {
        await _player.play(BytesSource(audio.audio, mimeType: audio.mime));
        await done.future.timeout(
          Duration(milliseconds: 8000 + t.length * 200),
          onTimeout: () {},
        );
        if (identical(_current, done)) _current = null;
        return;
      } catch (_) {
        if (done.isCompleted) return;
        // Unplayable audio: the phone's voice below.
      }
    }
    // Never wait forever on an engine that does not report completion.
    final limit = Duration(milliseconds: 4000 + t.length * 140);
    try {
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
    try {
      await _player.stop();
    } catch (_) {}
  }
}
