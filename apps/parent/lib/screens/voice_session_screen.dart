import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../api_voice.dart';
import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';
import '../voice_recorder.dart';
import '../widgets/voice_header.dart';
import '../widgets/voice_item_view.dart';
import '../widgets/voice_mic.dart';
import '../widgets/voice_transcript.dart';
import 'voice_report_screen.dart';

/// The 30-minute voice session (docs/voice_session_contract.md): Saathi speaks, the item is
/// shown big, the mic listens until the child stops talking, the answer is judged on the
/// server, and the loop continues by itself until time is up or the parent stops.
class VoiceSessionScreen extends StatefulWidget {
  const VoiceSessionScreen({super.key});
  @override
  State<VoiceSessionScreen> createState() => _VoiceSessionScreenState();
}

enum _Phase {
  choose,
  starting,
  startError,
  running,
  netError,
  micBlocked,
  safety,
  ending,
  endError,
}

/// One answer waiting for the server; kept until it is accepted so Retry resends the same
/// recording with the same id.
class _Pending {
  _Pending(this.itemId, {this.take, this.typed}) : turnId = newTurnId();
  final String itemId;
  final String turnId;
  final VoiceTake? take;
  final String? typed;
}

typedef _Cheer = ({String emoji, String text, Color fg, Color bg});

class _VoiceSessionScreenState extends State<VoiceSessionScreen> {
  final _rec = VoiceRecorder();

  _Phase _phase = _Phase.choose;
  VoiceMicState _mic = VoiceMicState.idle;
  // The learning language by default; the parent may pick another content language.
  String _lang = ContentLang.code.value;
  Object? _sid;
  Map<String, dynamic>? _item; // what the child answers next
  Map<String, dynamic>?
  _shown; // what is on screen (the answered item stays up briefly)
  List<Map<String, dynamic>> _shownWords = const [];
  int _try = 1;
  String _tutorText = '';
  String _tutorLang = 'hi';
  String? _stage;
  double _elapsedS = 0;
  DateTime _since = DateTime.now();
  int _targetMin = 30;
  bool _done = false;
  bool _paused = false;
  bool _busy = false;
  bool _safetyHold = false;
  bool _micDenied = false;
  String? _error;
  String _endReason = 'parent_stop';
  _Pending? _pending;
  final _lines = <Map<String, dynamic>>[];
  bool? _showTranscript;
  _Cheer? _cheer;
  int _cheerKey = 0;
  Timer? _cheerTimer;
  // Bumped to abandon an in-progress speak/listen step (pause, skip, replay, stop).
  int _gen = 0;

  static const _maxTries = 5;

  @override
  void initState() {
    super.initState();
    // Refresh the content-language list (the last copy shows at once).
    Api.i.languages().then((_) => _set(() {})).catchError((_) {});
  }

  /// Languages Saathi can teach in, the learning language first. Hindi and English when the
  /// server's list was never loaded.
  List<String> get _sessionLangs {
    final codes = <String>[
      for (final m
          in ((Api.i.languagesData?['content_languages'] as List?) ?? const [])
              .whereType<Map>())
        '${m['code']}',
    ];
    if (codes.isEmpty) codes.addAll(const ['hi', 'en']);
    final first = ContentLang.code.value;
    codes.remove(first);
    return [first, ...codes];
  }

  /// Native name of a language code (`मराठी`), from the server list or the app's own.
  static String _nativeName(String code) {
    for (final m
        in ((Api.i.languagesData?['content_languages'] as List?) ?? const [])
            .whereType<Map>()) {
      if (m['code'] == code && m['name_native'] != null) {
        return '${m['name_native']}';
      }
    }
    for (final l in appLanguages()) {
      if (l.code == code) return l.nativeName;
    }
    return code;
  }

  static String? _englishName(String code) {
    for (final l in appLanguages()) {
      if (l.code == code) return l.englishName;
    }
    return null;
  }

  @override
  void dispose() {
    _gen++;
    _cheerTimer?.cancel();
    Speak.stop();
    _rec.dispose();
    super.dispose();
  }

  void _set(VoidCallback f) {
    if (mounted) setState(f);
  }

  bool _live(int g) =>
      mounted && g == _gen && !_paused && _phase == _Phase.running;

  static Map<String, dynamic>? _map(dynamic v) =>
      v is Map ? v.cast<String, dynamic>() : null;

  static int _maxRecord(Map<String, dynamic> item) {
    final m = (item['max_record_s'] as num?)?.toInt();
    if (m != null && m > 0) return m;
    return switch (item['kind']) {
      'read_letter' || 'say_sound' => 4,
      'build_word' || 'read_word' => 5,
      'make_sentence' || 'read_sentence' => 8,
      'read_paragraph' => 30,
      _ => 10,
    };
  }

  // ---- session flow -------------------------------------------------------------------

  Future<void> _start(String lang) async {
    _lang = lang;
    _set(() {
      _phase = _Phase.starting;
      _error = null;
    });
    Map<String, dynamic> s;
    try {
      s = await Api.i.startVoice(lang);
    } catch (e) {
      _set(() {
        _phase = _Phase.startError;
        _error = voiceErrorText(e);
      });
      return;
    }
    if (!mounted) return;
    setState(() {
      _adoptSession(s);
      _phase = _Phase.running;
    });
    Speak.hasVoice(_tutorLang).then((ok) {
      if (!ok) {
        _toast(switch (_tutorLang) {
          'en' => tr(
            'No English (India) voice on this phone — read Saathi\'s words from the screen.',
            'इस फ़ोन पर अंग्रेज़ी आवाज़ नहीं है — साथी की बात स्क्रीन से पढ़कर सुनाइए।',
          ),
          'hi' => tr(
            'No Hindi voice on this phone — install it in Settings › Text-to-speech, or read Saathi\'s words aloud.',
            'इस फ़ोन पर हिंदी आवाज़ नहीं है — सेटिंग › टेक्स्ट-टू-स्पीच में डालें, या साथी की बात पढ़कर सुनाइए।',
          ),
          _ =>
            '${_nativeName(_tutorLang)}: ${tr('no voice for this language on this phone — install it in Settings › Text-to-speech, or read Saathi\'s words aloud.', 'इस भाषा की आवाज़ इस फ़ोन पर नहीं है — सेटिंग › टेक्स्ट-टू-स्पीच में डालें, या साथी की बात पढ़कर सुनाइए।')}',
        });
      }
    });
    _cycle();
  }

  /// Takes the server's view of the session (on start, and to resync after a stale turn).
  void _adoptSession(Map<String, dynamic> s) {
    final tutor = _map(s['tutor']);
    _sid = s['id'] ?? _sid;
    _tutorText = (tutor?['text'] ?? '').toString();
    _tutorLang = (tutor?['lang'] as String?) ?? _lang;
    _stage = (s['stage'] as String?) ?? _stage;
    _item = _map(s['item']);
    _shown = _item;
    _shownWords = const [];
    _try = ((s['attempt'] as num?)?.toInt() ?? 1).clamp(1, _maxTries);
    _elapsedS = (s['elapsed_s'] as num?)?.toDouble() ?? _elapsedS;
    _since = DateTime.now();
    _targetMin = (s['target_minutes'] as num?)?.toInt() ?? _targetMin;
    _done = s['done'] == true;
    _lines
      ..clear()
      ..addAll(
        ((s['transcript'] as List?) ?? const []).whereType<Map>().map(
          (l) => l.cast<String, dynamic>(),
        ),
      );
    if (_lines.isEmpty && _tutorText.isNotEmpty) {
      _lines.add({'role': 'tutor', 'text': _tutorText});
    }
  }

  /// Speak Saathi's line, show the item, listen, send. Re-entered after every answer.
  Future<void> _cycle({bool speak = true}) async {
    final g = ++_gen;
    if (!_live(g)) return;
    if (speak && _tutorText.isNotEmpty) {
      _set(() => _mic = VoiceMicState.talking);
      final talk = Speak.say(_tutorText, _tutorLang);
      if (_shown?['id'] != _item?['id']) {
        // Leave the answered item (with its coloured words) up for a moment, then move on.
        await Future.any([
          talk,
          Future<void>.delayed(const Duration(milliseconds: 1800)),
        ]);
        if (!_live(g)) return;
        _showCurrent();
      }
      await talk;
      if (!_live(g)) return;
    }
    _showCurrent();
    if (_safetyHold) {
      _set(() {
        _phase = _Phase.safety;
        _mic = VoiceMicState.idle;
      });
      return;
    }
    final item = _item;
    final overtime = VoiceClock.now(_elapsedS, _since) > _targetMin * 60 + 180;
    if (_done || item == null || overtime) {
      _finish('time_up');
      return;
    }
    _set(() => _mic = VoiceMicState.listening);
    VoiceTake? take;
    try {
      take = await _rec.listen(maxRecordS: _maxRecord(item));
    } on MicError catch (e) {
      if (!_live(g)) return;
      _set(() {
        _phase = _Phase.micBlocked;
        _micDenied = e.denied;
        _mic = VoiceMicState.idle;
      });
      return;
    }
    if (!_live(g) || take == null) return;
    _pending = _Pending((item['id'] ?? '').toString(), take: take);
    await _send();
  }

  void _showCurrent() {
    if (identical(_shown, _item)) return;
    _set(() {
      // A retry of the same item keeps its coloured words so the child sees what to fix.
      if (_shown?['id'] != _item?['id']) _shownWords = const [];
      _shown = _item;
    });
  }

  Future<void> _send() async {
    final p = _pending;
    final sid = _sid;
    if (p == null || sid == null) return;
    _set(() {
      _busy = true;
      _phase = _Phase.running;
      _error = null;
      _mic = VoiceMicState.thinking;
    });
    Map<String, dynamic> r;
    try {
      final wav = p.take?.wav;
      r = await Api.i.voiceTurn(
        sid,
        itemId: p.itemId,
        clientTurnId: p.turnId,
        audio: (wav == null || wav.isEmpty) ? null : wav,
        durationS: p.take?.durationS,
        transcript: p.typed,
      );
    } catch (e) {
      _busy = false;
      // 409: the server already moved past this item (e.g. a reply was lost); catch up.
      if (e is ApiError && e.status == 409 && await _resync()) return;
      if (_phase == _Phase.running) {
        _set(() {
          _phase = _Phase.netError;
          _error = voiceErrorText(e);
          _mic = VoiceMicState.idle;
        });
      }
      return;
    }
    _busy = false;
    if (identical(_pending, p)) _pending = null;
    if (!mounted || _phase != _Phase.running) return;
    _applyTurn(r);
    _continue();
  }

  Future<bool> _resync() async {
    final sid = _sid;
    if (sid == null) return false;
    try {
      final r = await Api.i.voiceSession(sid);
      final s = _map(r['session']);
      if (s == null || !mounted || _phase != _Phase.running) return false;
      _pending = null;
      setState(() => _adoptSession(s));
      _continue();
      return true;
    } catch (_) {
      return false;
    }
  }

  void _continue() {
    if (_paused) {
      _set(() => _mic = VoiceMicState.paused);
    } else if (_phase == _Phase.running) {
      _cycle();
    }
  }

  void _applyTurn(Map<String, dynamic> r) {
    final prevId = _item?['id'];
    final next = _map(r['next_item']);
    final words = voiceWords(r['words']);
    final verdict = r['verdict'] as String?;
    final tutor = _map(r['tutor']);
    final tutorText = (tutor?['text'] ?? '').toString();
    final append = ((r['transcript_append'] as List?) ?? const [])
        .whereType<Map>()
        .map((l) => l.cast<String, dynamic>())
        .toList();
    final prevStage = voiceStages.indexOf(_stage ?? '');
    final stage = (r['stage'] as String?) ?? _stage;
    final left = (r['attempts_left'] as num?)?.toInt();
    final attempt = (r['attempt'] as num?)?.toInt();
    final same = next != null && prevId != null && next['id'] == prevId;

    setState(() {
      if (append.isNotEmpty) {
        _lines.addAll(append);
      } else {
        if (verdict != null && verdict != 'skipped') {
          _lines.add({
            'role': 'child',
            'text': (r['heard'] ?? '').toString(),
            'verdict': verdict,
            'words': words,
          });
        }
        if (tutorText.isNotEmpty) {
          _lines.add({'role': 'tutor', 'text': tutorText});
        }
      }
      _tutorText = tutorText;
      _tutorLang = (tutor?['lang'] as String?) ?? _lang;
      if (words.isNotEmpty && _shown?['id'] == prevId) _shownWords = words;
      _item = next;
      // Next try number: from attempts_left when sent, else one more than the last attempt.
      _try = !same
          ? 1
          : (left != null ? _maxTries - left + 1 : (attempt ?? _try) + 1).clamp(
              1,
              _maxTries,
            );
      _stage = stage;
      final e = (r['elapsed_s'] as num?)?.toDouble();
      if (e != null) {
        _elapsedS = e;
        _since = DateTime.now();
      }
      _done = r['done'] == true;
      if (r['safety_flag'] != null) _safetyHold = true;
      _cheer = _cheerFor(
        verdict,
        stageUp:
            r['stage_changed'] == true &&
            voiceStages.indexOf(stage ?? '') > prevStage,
        stage: stage,
      );
      _cheerKey++;
    });
    final key = _cheerKey;
    _cheerTimer?.cancel();
    _cheerTimer = Timer(const Duration(milliseconds: 2400), () {
      if (key == _cheerKey) _set(() => _cheer = null);
    });
  }

  _Cheer? _cheerFor(String? verdict, {bool stageUp = false, String? stage}) {
    if (stageUp) {
      return (
        emoji: '⭐',
        text: trf(
          'New level: {voiceStageLabel}!',
          'नया स्तर: {voiceStageLabel}!', {'voiceStageLabel': voiceStageLabel(stage)},
        ),
        fg: Ks.green,
        bg: Ks.greenSoft,
      );
    }
    return switch (verdict) {
      'correct' => (
        emoji: '🎉',
        text: tr('Well done!', 'शाबाश!'),
        fg: Ks.green,
        bg: Ks.greenSoft,
      ),
      'close' => (
        emoji: '🙂',
        text: tr('Almost!', 'लगभग!'),
        fg: Ks.amber,
        bg: Ks.amberSoft,
      ),
      'wrong' => (
        emoji: '💪',
        text: tr('Let\'s try again', 'चलो, फिर से'),
        fg: Ks.amber,
        bg: Ks.amberSoft,
      ),
      'silent' => (
        emoji: '👂',
        text: tr('A little louder, please', 'थोड़ा ज़ोर से बोलो'),
        fg: Ks.muted,
        bg: Ks.card,
      ),
      _ => null,
    };
  }

  // ---- controls -------------------------------------------------------------------

  Future<void> _halt() async {
    _gen++;
    await Speak.stop();
    await _rec.cancel();
  }

  Future<void> _togglePause() async {
    if (_paused) {
      _set(() {
        _paused = false;
        _since = DateTime.now();
      });
      if (!_busy && _phase == _Phase.running) _cycle();
      return;
    }
    await _halt();
    _set(() {
      _paused = true;
      // The server counts only a little of a long pause, so the local clock stops too.
      _elapsedS = VoiceClock.now(_elapsedS, _since);
      if (!_busy) _mic = VoiceMicState.paused;
    });
  }

  Future<void> _replay() async {
    if (_busy || _phase != _Phase.running) return;
    await _halt();
    if (_paused) {
      _set(() {
        _paused = false;
        _since = DateTime.now();
      });
    }
    _cycle();
  }

  Future<void> _skip() async {
    final item = _item;
    final sid = _sid;
    if (item == null || sid == null || _busy) return;
    await _halt();
    _pending = null;
    _set(() {
      _busy = true;
      _phase = _Phase.running;
      _error = null;
      _mic = VoiceMicState.thinking;
    });
    Map<String, dynamic> r;
    try {
      r = await Api.i.voiceSkip(sid, (item['id'] ?? '').toString());
    } catch (e) {
      _busy = false;
      if (!mounted || _phase != _Phase.running) return;
      _toast(voiceErrorText(e));
      _continueSameItem();
      return;
    }
    _busy = false;
    if (!mounted || _phase != _Phase.running) return;
    _applyTurn(r);
    _continue();
  }

  void _continueSameItem() {
    if (_paused) {
      _set(() => _mic = VoiceMicState.paused);
    } else {
      _cycle(speak: false);
    }
  }

  Future<void> _typeAnswer() async {
    final item = _item;
    if (item == null) return;
    final text = await showDialog<String>(
      context: context,
      builder: (_) => const _TypeAnswerDialog(),
    );
    if (text == null || text.trim().isEmpty || !mounted) return;
    _pending = _Pending((item['id'] ?? '').toString(), typed: text.trim());
    await _send();
  }

  void _retryMic() {
    _set(() => _phase = _Phase.running);
    _continueSameItem();
  }

  void _continueAfterSafety() {
    _set(() {
      _safetyHold = false;
      _phase = _Phase.running;
    });
    _continueSameItem();
  }

  Future<void> _confirmStop() async {
    if (_sid == null ||
        _phase == _Phase.choose ||
        _phase == _Phase.startError) {
      Navigator.of(context).maybePop();
      return;
    }
    if (_phase == _Phase.ending) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Stop the session?', 'सत्र रोकें?')),
        content: Text(
          tr(
            'Saathi will make a report of what your child did so far.',
            'अब तक जो किया, साथी उसकी रिपोर्ट बनाएगा।',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(tr('Keep going', 'जारी रखें')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(tr('Stop and see report', 'रोकें, रिपोर्ट देखें')),
          ),
        ],
      ),
    );
    if (ok == true) _finish('parent_stop');
  }

  Future<void> _finish(String reason) async {
    final sid = _sid;
    if (sid == null || _phase == _Phase.ending) return;
    _endReason = reason;
    await _halt();
    _set(() {
      _phase = _Phase.ending;
      _mic = VoiceMicState.idle;
      _error = null;
    });
    try {
      final report = await Api.i.voiceEnd(sid, reason);
      if (!mounted) return;
      _openReport(sid, report);
    } catch (e) {
      if (!mounted) return;
      // Already ended (e.g. the first reply was lost): the report screen loads it.
      if (e is ApiError && (e.status == 400 || e.status == 409)) {
        _openReport(sid, null);
        return;
      }
      _set(() {
        _phase = _Phase.endError;
        _error = voiceErrorText(e);
      });
    }
  }

  void _openReport(Object sid, Map<String, dynamic>? report) {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => VoiceReportScreen(sessionId: sid, report: report),
      ),
    );
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  // ---- UI ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final canPop =
        _phase == _Phase.choose ||
        _phase == _Phase.startError ||
        _phase == _Phase.endError;
    return PopScope(
      canPop: canPop,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _confirmStop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            _sid == null
                ? tr('Voice session with Saathi', 'साथी के साथ आवाज़ सत्र')
                : switch (_lang) {
                    'en' => tr('Saathi · English', 'साथी · अंग्रेज़ी'),
                    'hi' => tr('Saathi · Hindi', 'साथी · हिंदी'),
                    _ => '${tr('Saathi', 'साथी')} · ${_nativeName(_lang)}',
                  },
          ),
        ),
        body: SafeArea(child: _body()),
      ),
    );
  }

  Widget _body() => switch (_phase) {
    _Phase.choose => _chooseView(),
    _Phase.starting => Loading(
      label: tr('Saathi is getting ready…', 'साथी तैयार हो रहा है…'),
    ),
    _Phase.startError => _messageView(
      icon: Icons.wifi_off_rounded,
      text: _error ?? '',
      primary: tr('Try again', 'फिर से कोशिश करें'),
      onPrimary: () => _start(_lang),
      secondary: tr('Go back', 'वापस जाएँ'),
      onSecondary: () => Navigator.of(context).maybePop(),
    ),
    _Phase.ending => Loading(
      label: _endReason == 'time_up'
          ? tr(
              'Time\'s up — great work! Making the report…',
              'समय पूरा — बहुत बढ़िया! रिपोर्ट बन रही है…',
            )
          : tr('Making the report…', 'रिपोर्ट बन रही है…'),
    ),
    _Phase.endError => _messageView(
      icon: Icons.cloud_off_rounded,
      text: _error ?? '',
      primary: tr('Try again', 'फिर से कोशिश करें'),
      onPrimary: () => _finish(_endReason),
      secondary: tr('Leave without the report', 'रिपोर्ट के बिना निकलें'),
      onSecondary: () => Navigator.of(context).pop(),
    ),
    _ => _sessionView(),
  };

  Widget _chooseView() {
    final langs = _sessionLangs;
    String sub(String code) => switch (code) {
      'hi' => tr('Hindi reading', 'हिंदी पढ़ना'),
      'en' => tr('English reading', 'अंग्रेज़ी पढ़ना'),
      _ => _englishName(code) ?? code,
    };
    Widget langButton(String code, String label, String sub) => Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: FilledButton(
        style: FilledButton.styleFrom(
          // Many languages: the others are shorter so the tips stay in reach.
          minimumSize: Size.fromHeight(
            code == langs.first || langs.length <= 2 ? 76 : 60,
          ),
          backgroundColor: code == langs.first ? Ks.accent : Ks.ink,
        ),
        onPressed: () => _start(code),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: const TextStyle(fontSize: 24)),
            Text(
              sub,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w400),
            ),
          ],
        ),
      ),
    );
    Widget tip(IconData i, String t) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(i, color: Ks.accent, size: 22),
          const SizedBox(width: 10),
          Expanded(child: Text(t, style: const TextStyle(fontSize: 15))),
        ],
      ),
    );
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.all(20),
          children: [
            const Center(child: Text('🦉', style: TextStyle(fontSize: 72))),
            const SizedBox(height: 8),
            Text(
              tr(
                'Which language should Saathi speak?',
                'साथी किस भाषा में बात करे?',
              ),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontSize: 24),
            ),
            const SizedBox(height: 20),
            // The learning language first (highlighted), then the other content languages.
            for (final code in langs)
              langButton(code, _nativeName(code), sub(code)),
            const SizedBox(height: 10),
            tip(
              Icons.volume_off_rounded,
              tr('Sit in a quiet place', 'शांत जगह पर बैठें'),
            ),
            tip(
              Icons.phone_android_rounded,
              tr(
                'Keep the phone close to your child',
                'फ़ोन बच्चे के पास रखें',
              ),
            ),
            tip(
              Icons.timer_outlined,
              tr(
                'About 30 minutes — you can pause or stop anytime',
                'लगभग 30 मिनट — कभी भी रोक सकते हैं',
              ),
            ),
            tip(
              Icons.lock_outline_rounded,
              tr(
                'Recordings are only used to check answers, never saved on the phone',
                'रिकॉर्डिंग सिर्फ़ जवाब जाँचने के लिए है, फ़ोन पर सेव नहीं होती',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messageView({
    required IconData icon,
    required String text,
    required String primary,
    required VoidCallback onPrimary,
    required String secondary,
    required VoidCallback onSecondary,
  }) => Center(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 480),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 52, color: Ks.muted),
            const SizedBox(height: 12),
            Text(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 17),
            ),
            const SizedBox(height: 20),
            FilledButton(onPressed: onPrimary, child: Text(primary)),
            const SizedBox(height: 10),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(56),
              ),
              onPressed: onSecondary,
              child: Text(secondary),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _sessionView() {
    final size = MediaQuery.sizeOf(context);
    final wide = size.width >= 760;
    // A help panel (network, mic, safety) needs the room more than the transcript does.
    final panel = _phase != _Phase.running;
    final showTranscript = !panel && (_showTranscript ?? size.height >= 760);
    final main = Column(
      children: [
        _tutorCard(),
        Expanded(child: _itemArea()),
        ConstrainedBox(
          constraints: BoxConstraints(maxHeight: size.height * 0.4),
          child: SingleChildScrollView(child: _statusArea()),
        ),
        if (!wide && !panel) _transcriptToggle(showTranscript),
        if (!wide && showTranscript)
          SizedBox(
            height: (size.height * 0.26).clamp(140.0, 260.0),
            child: _transcriptBox(),
          ),
      ],
    );
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 6),
          child: Column(
            children: [
              VoiceClock(
                elapsedS: _elapsedS,
                since: _since,
                targetMinutes: _targetMin,
                running: !_paused,
              ),
              const SizedBox(height: 8),
              VoiceLadder(stage: _stage),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: wide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(child: main),
                      const SizedBox(width: 12),
                      SizedBox(
                        width: 340,
                        child: Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: _transcriptBox(),
                        ),
                      ),
                    ],
                  )
                : main,
          ),
        ),
        _controls(),
      ],
    );
  }

  Widget _tutorCard() => Card(
    child: Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(14, 10, 6, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('🦉', style: TextStyle(fontSize: 30)),
          const SizedBox(width: 10),
          Expanded(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 110),
              child: SingleChildScrollView(
                child: Text(
                  _tutorText,
                  style: const TextStyle(
                    fontSize: 19,
                    height: 1.45,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );

  Widget _itemArea() {
    final item = _shown;
    return Stack(
      children: [
        Positioned.fill(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 6),
              child: item == null
                  ? const Text('🦉', style: TextStyle(fontSize: 96))
                  : VoiceItemView(item: item, words: _shownWords),
            ),
          ),
        ),
        if (_try > 1 && _item != null && _shown?['id'] == _item?['id'])
          Positioned(
            top: 8,
            right: 4,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: Ks.amberSoft,
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text(
                trf('Try {try} of {maxTries}', 'कोशिश {try} / {maxTries}', {'try': _try, 'maxTries': _maxTries}),
                style: const TextStyle(
                  color: Ks.amber,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        if (_cheer != null)
          Positioned(
            top: 8,
            left: 0,
            right: 0,
            child: Center(
              child: TweenAnimationBuilder<double>(
                key: ValueKey(_cheerKey),
                tween: Tween(begin: 0.3, end: 1),
                duration: const Duration(milliseconds: 600),
                curve: Curves.elasticOut,
                builder: (_, v, child) =>
                    Transform.scale(scale: v, child: child),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: _cheer!.bg,
                    borderRadius: BorderRadius.circular(99),
                    border: Border.all(color: _cheer!.fg.withValues(alpha: .4)),
                  ),
                  child: Text(
                    '${_cheer!.emoji}  ${_cheer!.text}',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      color: _cheer!.fg,
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _statusArea() {
    switch (_phase) {
      case _Phase.netError:
        return _panel(
          color: Ks.amberSoft,
          icon: Icons.cloud_off_rounded,
          text:
              '${_error ?? ''}\n${tr('Your child\'s answer is kept.', 'बच्चे का जवाब सुरक्षित है।')}',
          actions: [
            FilledButton.icon(
              onPressed: _send,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Try again', 'फिर से भेजें')),
            ),
          ],
        );
      case _Phase.micBlocked:
        return _panel(
          color: Ks.roseSoft,
          icon: Icons.mic_off_rounded,
          text: _micDenied
              ? tr(
                  'Saathi needs the microphone to hear your child. Allow microphone access (phone Settings › Apps › Kaksha Saathi › Permissions), then try again.',
                  'बच्चे को सुनने के लिए साथी को माइक चाहिए। फ़ोन की सेटिंग › ऐप › कक्षा साथी › अनुमति में माइक चालू करें, फिर कोशिश करें।',
                )
              : tr('The microphone did not start.', 'माइक चालू नहीं हुआ।'),
          actions: [
            FilledButton.icon(
              onPressed: _retryMic,
              icon: const Icon(Icons.mic_rounded),
              label: Text(tr('Try the mic again', 'माइक फिर से')),
            ),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(56),
              ),
              onPressed: _typeAnswer,
              icon: const Icon(Icons.keyboard_rounded),
              label: Text(
                tr('Type what your child said', 'बच्चे ने जो कहा, लिखें'),
              ),
            ),
          ],
        );
      case _Phase.safety:
        return _panel(
          color: Ks.accentSoft,
          icon: Icons.favorite_rounded,
          text: tr(
            'Saathi has paused. Please sit with your child for a moment and talk with them. Continue when you are both ready.',
            'साथी रुक गया है। कृपया थोड़ी देर बच्चे के साथ बैठकर बात करें। जब दोनों तैयार हों, तब आगे बढ़ें।',
          ),
          actions: [
            FilledButton(
              onPressed: _continueAfterSafety,
              child: Text(tr('Continue the session', 'सत्र जारी रखें')),
            ),
          ],
        );
      default:
        final state = _paused && !_busy ? VoiceMicState.paused : _mic;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(
            children: [
              VoiceMicIndicator(
                state: state,
                level: _rec.level,
                speaking: _rec.speaking,
              ),
              if (state == VoiceMicState.listening)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: FilledButton.icon(
                    onPressed: _rec.finish,
                    icon: const Icon(Icons.check_rounded, size: 26),
                    label: Text(tr('Done speaking', 'बोल लिया')),
                  ),
                ),
              if (state == VoiceMicState.paused)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: FilledButton.icon(
                    onPressed: _togglePause,
                    icon: const Icon(Icons.play_arrow_rounded, size: 28),
                    label: Text(tr('Resume', 'फिर शुरू करें')),
                  ),
                ),
            ],
          ),
        );
    }
  }

  Widget _panel({
    required Color color,
    required IconData icon,
    required String text,
    required List<Widget> actions,
  }) => Container(
    margin: const EdgeInsets.symmetric(vertical: 6),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(16),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: Ks.ink),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                text.trim(),
                style: const TextStyle(fontSize: 16, height: 1.4),
              ),
            ),
          ],
        ),
        for (final a in actions) ...[const SizedBox(height: 10), a],
      ],
    ),
  );

  Widget _transcriptToggle(bool open) => InkWell(
    onTap: () => _set(() => _showTranscript = !open),
    child: ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 48),
      child: Row(
        children: [
          const Icon(Icons.forum_outlined, color: Ks.accent, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              trf(
                'Conversation ({linesCount})',
                'बातचीत ({linesCount})', {'linesCount': _lines.length},
              ),
              style: const TextStyle(
                fontWeight: FontWeight.w600,
                color: Ks.accent,
              ),
            ),
          ),
          Icon(
            open ? Icons.expand_more_rounded : Icons.expand_less_rounded,
            color: Ks.accent,
          ),
        ],
      ),
    ),
  );

  Widget _transcriptBox() => DecoratedBox(
    decoration: BoxDecoration(
      color: Ks.card,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: Ks.line),
    ),
    child: ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: VoiceTranscript(lines: List.of(_lines)),
    ),
  );

  Widget _controls() {
    final running =
        _phase == _Phase.running ||
        _phase == _Phase.netError ||
        _phase == _Phase.micBlocked;
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
      decoration: const BoxDecoration(
        color: Ks.card,
        border: Border(top: BorderSide(color: Ks.line)),
      ),
      child: Row(
        children: [
          _ctrl(
            _paused ? Icons.play_arrow_rounded : Icons.pause_rounded,
            _paused ? tr('Resume', 'शुरू') : tr('Pause', 'रोकें'),
            _phase == _Phase.running ? _togglePause : null,
          ),
          _ctrl(
            Icons.replay_rounded,
            tr('Repeat', 'दोहराएँ'),
            _phase == _Phase.running && !_busy ? _replay : null,
          ),
          _ctrl(
            Icons.skip_next_rounded,
            tr('Skip', 'छोड़ें'),
            running && !_busy && _item != null ? _skip : null,
          ),
          _ctrl(
            Icons.stop_circle_outlined,
            tr('Stop', 'बंद करें'),
            _confirmStop,
            color: Ks.rose,
          ),
        ],
      ),
    );
  }

  Widget _ctrl(
    IconData icon,
    String label,
    VoidCallback? onTap, {
    Color color = Ks.accent,
  }) => Expanded(
    child: Semantics(
      button: true,
      label: label,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 60),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 30, color: onTap == null ? Ks.line : color),
              const SizedBox(height: 2),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: onTap == null ? Ks.muted : color,
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

/// Fallback when the mic cannot be used: the parent types what the child said.
class _TypeAnswerDialog extends StatefulWidget {
  const _TypeAnswerDialog();
  @override
  State<_TypeAnswerDialog> createState() => _TypeAnswerDialogState();
}

class _TypeAnswerDialogState extends State<_TypeAnswerDialog> {
  final _c = TextEditingController();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(tr('What did your child say?', 'बच्चे ने क्या कहा?')),
    content: TextField(
      controller: _c,
      autofocus: true,
      style: const TextStyle(fontSize: 20),
      textInputAction: TextInputAction.send,
      onSubmitted: (v) => Navigator.of(context).pop(v),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: Text(tr('Cancel', 'रद्द करें')),
      ),
      FilledButton(
        style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
        onPressed: () => Navigator.of(context).pop(_c.text),
        child: Text(tr('Send', 'भेजें')),
      ),
    ],
  );
}
