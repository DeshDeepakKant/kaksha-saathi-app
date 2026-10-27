import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:record/record.dart';

import '../api.dart';
import '../theme.dart';
import '../wav.dart';
import '../speech_web.dart' if (dart.library.js_interop) '../speech_js.dart';
import '../l10n.dart';

/// The session runner. When online it talks to the server harness (one turn per attempt);
/// when offline it runs the SAME harness locally from the downloaded pack with canned lines.
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, required this.offline});
  final bool offline;
  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  final _rec = AudioRecorder();
  final _chunks = BytesBuilder(copy: false);
  StreamSubscription<Uint8List>? _sub;

  Map<String, dynamic>? _plan;
  Map<String, dynamic>? _activity;
  String _line = '';
  int _index = 0;
  int _attempt = 0;
  int _total = 0;
  int _done = 0;
  // When the app falls back to offline mid-session we must reload the pack (the online plan
  // was delivered as a JSON list; the pack starts as a map).
  bool _offlineReloaded = false;
  int? _sessionId;
  bool _recording = false;
  bool _busy = false;
  bool _finished = false;
  bool _offline = false;
  final _lines = <String>[];
  String _emotion = '😊';
  String? _safety;
  // Turns finished offline, uploaded via /parent/sessions/sync when the network is back.
  final _offlineItems = <Map<String, dynamic>>[];
  final DateTime _startedAt = DateTime.now().toUtc();

  @override
  void initState() {
    super.initState();
    _offline = widget.offline;
    _start();
  }

  Future<void> _start() async {
    if (_offline) {
      _loadPack();
      return;
    }
    try {
      final r =
          await Api.i.startSession(offlineMode: false) as Map<String, dynamic>;
      final plan = (r['plan'] as Map).cast<String, dynamic>();
      setState(() {
        _sessionId = r['session_id'] as int;
        _plan = plan;
        _total = (plan['activities'] as List).length;
        _activity = (r['activity'] as Map?)?.cast<String, dynamic>();
        _line = r['intro_hi'] as String? ?? '';
      });
      _speak(_line);
    } catch (_) {
      _offline = true;
      _loadPack();
    }
  }

  /// Switches to the downloaded pack. With [resumeRef], continues at that activity if the
  /// pack has it; returns whether it did.
  bool _loadPack({String? resumeRef}) {
    final pack = Api.i.pack;
    if (pack == null) {
      setState(
        () => _line = tr(
          'First download the practice once over the internet.',
          'पहले एक बार इंटरनेट से अभ्यास डाउनलोड करें।',
        ),
      );
      return false;
    }
    final acts = (pack['activities'] as List)
        .map((a) => (a as Map).cast<String, dynamic>())
        .toList();
    final at = resumeRef == null
        ? -1
        : acts.indexWhere((a) => a['ref'] == resumeRef);
    setState(() {
      _plan = pack;
      _total = acts.length;
      _index = at < 0 ? 0 : at;
      _attempt = at < 0 ? 0 : _attempt;
      _activity = acts.isEmpty ? null : acts[_index];
      _line = _canned('intro', _activity?['prompt_hi'] ?? '');
      _offline = true;
    });
    _speak(_line);
    return at >= 0;
  }

  String _canned(String sit, String prompt) {
    final lines = (Api.i.pack?['canned_lines'] as Map?) ?? const {};
    return ((lines[sit] as String?) ?? '').replaceAll('{prompt}', prompt);
  }

  void _speak(String text) {
    if (kIsWeb) speakOnWeb(text);
  }

  Future<void> _toggle() async {
    if (_busy) return;
    if (_recording) {
      await _stopAndSend();
      return;
    }
    if (_offline) {
      // Offline: the child listened to the model pronunciation; we cannot verify speech, so the
      // turn is recorded as "practised" and we move on (no false accuracy claims).
      await _sendLocal(_activity!);
      return;
    }
    // A missing / denied / unresponsive microphone must never dead-end the session:
    // we time out, tell the child, and continue in "listened and practised" mode.
    try {
      final ok = await _rec.hasPermission().timeout(
        const Duration(seconds: 3),
        onTimeout: () => false,
      );
      if (!ok) {
        _toast(
          tr(
            'Mic not found — Saathi will speak, please speak along',
            'माइक नहीं मिला — साथी बोलेगा, आप साथ में बोलिए',
          ),
        );
        await _sendLocal(_activity!, listened: true);
        return;
      }
      final stream = await _rec
          .startStream(
            const RecordConfig(
              encoder: AudioEncoder.pcm16bits,
              sampleRate: 16000,
              numChannels: 1,
            ),
          )
          .timeout(const Duration(seconds: 5));
      _chunks.clear();
      _sub = stream.listen(_chunks.add);
      setState(() => _recording = true);
      _timer = Timer(const Duration(seconds: 7), () {
        if (mounted && _recording) _stopAndSend();
      });
    } catch (_) {
      _toast(
        tr(
          'Mic didn\'t work — Saathi will speak, please speak along',
          'माइक नहीं चला — साथी बोलेगा, आप साथ में बोलिए',
        ),
      );
      await _sendLocal(_activity!, listened: true);
    }
  }

  Timer? _timer;

  Future<void> _stopAndSend() async {
    _timer?.cancel();
    Uint8List? audio;
    try {
      await _rec.stop();
      await _sub?.cancel();
      final pcm = _chunks.takeBytes();
      if (pcm.isNotEmpty) audio = wavFromPcm16(pcm);
    } catch (_) {}
    setState(() {
      _recording = false;
      _busy = true;
    });
    await _send(audio: audio);
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _send({
    Uint8List? audio,
    String? tap,
    String? transcript,
  }) async {
    final act = _activity;
    if (act == null) return;
    if (_offline) {
      _sendLocal(act, tap: tap);
      return;
    }
    try {
      final meta = {
        'index': _index,
        'attempt': _attempt,
        'activity_ref': act['ref'] ?? '',
        'tap': ?tap,
        'transcript': ?transcript,
        'offline': false,
      };
      final r = await Api.i.postMultipart(
        '/v1/parent/sessions/$_sessionId/turn',
        {'meta': jsonEncode(meta)},
        audio: (transcript != null) ? null : audio,
        field: 'audio',
      ) as Map<String, dynamic>;
      _applyTurn(r, act);
    } catch (e) {
      _toast(
        tr(
          'Internet lost — continuing with the remaining practice',
          'इंटरनेट चला गया — आगे बचे अभ्यास से',
        ),
      );
      if (!_offlineReloaded) {
        _offlineReloaded = true;
        // Replay this turn only if the pack has the same activity; otherwise start it fresh.
        final resumed = _loadPack(resumeRef: act['ref'] as String?);
        await Future.delayed(const Duration(milliseconds: 100));
        final a = _activity;
        if (resumed && a != null) {
          await _sendLocal(a, tap: tap, transcript: transcript);
        }
      }
    }
  }

  /// Words and numbers are read aloud as shown; for questions and taps, `target` is the answer.
  static String _shown(Map<String, dynamic> act) {
    final type = act['type'] as String? ?? '';
    return (type == 'say_word' || type == 'say_number')
        ? (act['target'] ?? '').toString()
        : (act['prompt_hi'] ?? '').toString();
  }

  void _applyTurn(Map<String, dynamic> r, Map<String, dynamic> act) {
    setState(() {
      _line = r['line_hi'] as String? ?? '';
      if (r['safety_flag'] != null) _safety = r['safety_flag'] as String;
      if (r['advance'] == true) {
        _index = (r['next_index'] as num?)?.toInt() ?? _index + 1;
        _attempt = 0;
        _done++;
        _activity = (r['next_activity'] as Map?)?.cast<String, dynamic>();
        if (r['done'] == true || _activity == null) _finished = true;
      } else {
        _attempt = (r['attempt'] as num?)?.toInt() ?? _attempt + 1;
      }
      final judged = r['judged'];
      _emotion = judged == 'correct' ? '🎉' : (judged == 'wrong' ? '💪' : '😊');
      _lines.add(_line);
    });
    _speak(_line);
  }

  /// Offline harness mirror of backend/services/tutor.judge (same rules, no model).
  Future<void> _sendLocal(
    Map<String, dynamic> act, {
    String? tap,
    String? transcript,
    bool listened = false,
  }) async {
    final type = act['type'] as String? ?? 'tap_choice';
    final target = (act['target'] ?? '').toString();
    bool ok;
    if (type.startsWith('tap')) {
      ok = tap == target;
    } else {
      // Without a working mic we cannot verify speech, so the turn counts as *practised*
      // (no accuracy claim) and the session moves on. The child still hears the model word.
      ok = true;
      if (!listened) transcript = tr('(offline practice)', '(ऑफलाइन अभ्यास)');
    }
    final sit = ok
        ? 'praise'
        : (_attempt + 1 < 2 ? 'feedback_wrong' : 'comfort');
    final advance = ok || _attempt + 1 >= 2;
    setState(() {
      _line = _canned(sit, act['prompt_hi'] as String? ?? '');
      _emotion = ok ? '🎉' : '💪';
      _lines.add(_line);
      if (advance) {
        _offlineItems.add({
          'activity_ref': act['ref'] ?? '',
          if (type.startsWith('tap') && tap != null) 'tap': tap,
        });
        _done++;
        _index++;
        _attempt = 0;
        final acts = (_plan?['activities'] as List?) ?? const [];
        _activity = _index < acts.length
            ? (acts[_index] as Map).cast<String, dynamic>()
            : null;
        if (_activity == null) _finished = true;
      } else {
        _attempt++;
      }
    });
    _speak(_line);
  }

  Future<void> _finish() async {
    if (_sessionId != null && !_offline) {
      try {
        await Api.i.endSession(_sessionId!, null);
        await Api.i.fetchHistory();
      } catch (_) {}
    }
    if (_offlineItems.isNotEmpty) {
      Api.i.queueSession({
        'started_at': _startedAt.toIso8601String(),
        'ended_at': DateTime.now().toUtc().toIso8601String(),
        if (_sessionId != null) 'session_id': _sessionId,
        'items': _offlineItems,
      });
    }
    await Api.i.flushPending();
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _sub?.cancel();
    _rec.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final act = _activity;
    final type = act?['type'] as String? ?? '';
    final options = ((act?['options'] as List?) ?? const [])
        .map((e) => e.toString())
        .toList();
    return Scaffold(
      appBar: AppBar(
        title: Text(
          _finished
              ? tr('Practice complete', 'अभ्यास पूरा')
              : tr(
                  'Practice ${(_done + 1).clamp(1, _total)} / $_total',
                  'अभ्यास ${(_done + 1).clamp(1, _total)} / $_total',
                ),
        ),
        actions: [
          if (_offline)
            const Padding(
              padding: EdgeInsets.only(right: 12),
              child: Icon(Icons.cloud_off_rounded, color: Ks.amber),
            ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: _finished
              ? _endCard()
              : Column(
                  children: [
                    LinearProgressIndicator(
                      value: _total == 0 ? 0 : _done / _total,
                      minHeight: 10,
                      borderRadius: BorderRadius.circular(99),
                      color: Ks.accent,
                      backgroundColor: Ks.accentSoft,
                    ),
                    const SizedBox(height: 18),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('🦉', style: TextStyle(fontSize: 34)),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                _line,
                                style: const TextStyle(
                                  fontSize: 21,
                                  height: 1.5,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            IconButton(
                              icon: const Icon(
                                Icons.volume_up_rounded,
                                color: Ks.accent,
                              ),
                              onPressed: () => _speak(_line),
                            ),
                          ],
                        ),
                      ),
                    ),
                    if (_safety != null)
                      Card(
                        margin: const EdgeInsets.only(top: 12),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Text(
                            tr(
                              'Please tell a grown-up — mum, dad or a teacher — about this.',
                              'किसी बड़े — मम्मी, पापा या अध्यापक — को यह बात बताइए।',
                            ),
                            style: const TextStyle(
                              color: Ks.rose,
                              fontSize: 17,
                            ),
                          ),
                        ),
                      ),
                    const SizedBox(height: 14),
                    if (act != null && type.startsWith('tap'))
                      Expanded(
                        child: GridView.count(
                          crossAxisCount: 2,
                          mainAxisSpacing: 12,
                          crossAxisSpacing: 12,
                          childAspectRatio: 1.6,
                          children: [
                            for (final o in options)
                              InkWell(
                                borderRadius: BorderRadius.circular(18),
                                onTap: _busy ? null : () => _send(tap: o),
                                child: Container(
                                  alignment: Alignment.center,
                                  decoration: BoxDecoration(
                                    color: Ks.card,
                                    borderRadius: BorderRadius.circular(18),
                                    border: Border.all(color: Ks.line),
                                  ),
                                  child: Text(
                                    o,
                                    style: const TextStyle(
                                      fontSize: 30,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                              ),
                          ],
                        ),
                      )
                    else
                      Expanded(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              _emotion,
                              style: const TextStyle(fontSize: 54),
                            ),
                            const SizedBox(height: 8),
                            if (act != null)
                              Text(
                                tr(
                                  'Say: ${_shown(act)}',
                                  'बोलिए: ${_shown(act)}',
                                ),
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  fontSize: 24,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            const SizedBox(height: 6),
                            Text(
                              _attempt > 0
                                  ? tr(
                                      'Try again ${_attempt + 1} / 2',
                                      'फिर से कोशिश ${_attempt + 1} / 2',
                                    )
                                  : tr('Press mic', 'माइक दबाएँ'),
                              style: const TextStyle(color: Ks.muted),
                            ),
                          ],
                        ),
                      ),
                    const SizedBox(height: 10),
                    if (_recording)
                      Text(
                        tr('Listening…', 'सुन रहे हैं…'),
                        style: TextStyle(color: Ks.rose, fontSize: 16),
                      )
                    else if (_busy)
                      Text(
                        tr('Saathi is thinking…', 'साथी सोच रहा है…'),
                        style: TextStyle(color: Ks.muted),
                      ),
                    const SizedBox(height: 8),
                    if (act == null)
                      Text(
                        tr('Moving on…', 'आगे बढ़ते हैं…'),
                        style: TextStyle(color: Ks.muted),
                      ),
                    GestureDetector(
                      onTap: act == null || type.startsWith('tap')
                          ? null
                          : _toggle,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        width: _recording ? 104 : 88,
                        height: _recording ? 104 : 88,
                        decoration: BoxDecoration(
                          color: type.startsWith('tap')
                              ? Ks.line
                              : (_recording ? Ks.rose : Ks.accent),
                          shape: BoxShape.circle,
                        ),
                        child: Icon(
                          type.startsWith('tap')
                              ? Icons.touch_app_rounded
                              : (_recording
                                    ? Icons.stop_rounded
                                    : Icons.mic_rounded),
                          color: Colors.white,
                          size: 44,
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextButton(
                      onPressed: _finish,
                      child: Text(
                        tr(
                          'That\'s enough for today — stop',
                          'आज के लिए बस — रुकें',
                        ),
                      ),
                    ),
                  ],
                ),
        ),
      ),
    );
  }

  Widget _endCard() => Center(
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('🌟', style: TextStyle(fontSize: 60)),
            const SizedBox(height: 8),
            Text(
              tr(
                'Well done, ${Api.i.child?['first_name'] ?? 'friend'}!',
                'शाबाश, ${Api.i.child?['first_name'] ?? 'बच्चे'}!',
              ),
              style: Theme.of(context).textTheme.titleLarge
                  ?.copyWith(fontSize: 26),
            ),
            const SizedBox(height: 6),
            Text(
              tr(
                '$_done activities completed today.\nPractise again tomorrow.',
                'आज $_done गतिविधियाँ पूरी हुईं।\nकल फिर अभ्यास करें।',
              ),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 17, color: Ks.muted),
            ),
            const SizedBox(height: 18),
            FilledButton(onPressed: _finish, child: Text(tr('OK', 'ठीक है'))),
          ],
        ),
      ),
    ),
  );
}
