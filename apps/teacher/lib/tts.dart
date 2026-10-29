import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'api.dart';
import 'l10n.dart';

/// Read-aloud for plans and probes, in the learning language.
/// - First the server voice (`POST /v1/speech/tts`, the teacher's voice service), played with
///   audioplayers. Recent lines are kept in memory, so a replay is instant.
/// - When the server can't speak the language (204), is older than that endpoint (404), or is
///   unreachable: the phone's voice. Android: on-device TTS via flutter_tts (offline once the
///   voice is installed). Web: browser SpeechSynthesis (via the channel in web/index.html).
class Speak {
  static final _tts = FlutterTts();
  static final _player = AudioPlayer();
  static bool _init = false;
  static String? _voice;
  // A newer say() or stop() abandons an older one still fetching.
  static int _gen = 0;

  /// Phone-voice (BCP-47) code for one of our language codes: `en` → en-IN, `or` → or-IN,
  /// `mr` → mr-IN, …; empty means Hindi.
  static String bcp47(String lang) => lang.isEmpty ? 'hi-IN' : '$lang-IN';

  /// Speaks [text] in [lang] (default: the learning language, `ContentLang.code`).
  static Future<void> say(String text, [String? lang]) async {
    final t = text.trim();
    if (t.isEmpty) return;
    final l = lang ?? ContentLang.code.value;
    final g = ++_gen;
    await _stopAll();
    final audio = await _serverAudio(t, l);
    if (g != _gen) return;
    if (audio != null) {
      try {
        await _player.play(BytesSource(audio.audio, mimeType: audio.mime));
        return;
      } catch (_) {
        // Unplayable audio: the phone's voice below.
      }
    }
    if (!_init) {
      _init = true;
      try {
        await _tts.setSpeechRate(0.42);
        await _tts.setPitch(1.0);
        _tts.setErrorHandler((_) {});
      } catch (_) {}
    }
    try {
      final code = bcp47(l);
      if (_voice != code) {
        await _tts.setLanguage(code);
        _voice = code;
      }
      await _tts.speak(t);
    } catch (_) {
      try {
        SystemChannels.platform.invokeMethod('KakshaSpeak', t);
      } catch (_) {}
    }
  }

  /// Stops whatever is being read aloud.
  static Future<void> stop() async {
    _gen++;
    await _stopAll();
  }

  static Future<void> _stopAll() async {
    try {
      await _tts.stop();
    } catch (_) {}
    try {
      await _player.stop();
    } catch (_) {}
  }

  // ---- server voice

  static final _cache = <String, ({Uint8List audio, String? mime})>{};
  // Per language, after a 204 or a failure.
  static final _skipUntil = <String, DateTime>{};
  static bool _serverMissing = false; // the server has no /v1/speech/tts

  static Future<({Uint8List audio, String? mime})?> _serverAudio(
    String t,
    String lang,
  ) async {
    if (!Api.i.loggedIn || _serverMissing) return null;
    final until = _skipUntil[lang];
    if (until != null && DateTime.now().isBefore(until)) return null;
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
}
