import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../record_audio.dart';
import '../theme.dart';

/// Reading-aloud check for one child and one lesson: the child reads the target words, the teacher
/// records them, the server scores each word (code, not AI) and the teacher confirms the result as
/// evidence. If there is no mic or the recording cannot be scored, the teacher ticks each word by
/// hand and saves it through the tap route. Pops `true` when evidence was saved.
class ReadAloudSheet extends StatefulWidget {
  const ReadAloudSheet({
    super.key,
    required this.classId,
    required this.childId,
    required this.childName,
    required this.checkpointId,
    required this.title,
    required this.targets,
  });
  final int classId;
  final int childId;
  final String childName;
  final String checkpointId;
  final String title;
  final List<String> targets;
  @override
  State<ReadAloudSheet> createState() => _ReadAloudSheetState();
}

enum _Stage { ready, recording, busy, result, manual }

class _ReadAloudSheetState extends State<ReadAloudSheet> {
  final Recorder _rec = Recorder();
  _Stage _stage = _Stage.ready;
  bool _saving = false;
  String? _notice; // friendly note shown above the current step
  Map<String, dynamic>? _resp;
  String _result =
      'partial'; // result the teacher will save from a scored recording
  late final List<bool?> _ticks = List.filled(widget.targets.length, null);

  @override
  void dispose() {
    _rec.dispose();
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (_stage == _Stage.recording) {
      final bytes = await _rec.stop();
      if (!mounted) return;
      if (bytes == null || bytes.isEmpty) {
        setState(() {
          _stage = _Stage.ready;
          _notice = tr(
            'The recording was empty. Try again, or tick the words by hand.',
            'रिकॉर्डिंग खाली रही। दोबारा करें, या शब्द हाथ से चुनें।',
          );
        });
        return;
      }
      await _score(bytes);
      return;
    }
    final ok = await _rec.start();
    if (!mounted) return;
    if (!ok) {
      setState(() {
        _stage = _Stage.manual;
        _notice = tr(
          'Mic is not available. Tick each word by hand instead.',
          'माइक उपलब्ध नहीं है। हर शब्द हाथ से चुनें।',
        );
      });
      return;
    }
    setState(() {
      _stage = _Stage.recording;
      _notice = null;
    });
  }

  Future<void> _score(List<int> bytes) async {
    setState(() {
      _stage = _Stage.busy;
      _notice = null;
    });
    try {
      final r = await Api.i.postMultipart(
        '/v1/classes/${widget.classId}/captures/voice',
        fields: {
          'body_json': jsonEncode({
            'child_id': widget.childId,
            'checkpoint_id': widget.checkpointId,
            'target_items': widget.targets,
          }),
        },
        file: Uint8List.fromList(bytes),
        fieldName: 'audio',
        filename: 'read.wav',
      ) as Map;
      if (!mounted) return;
      final resp = r.cast<String, dynamic>();
      if (resp['capture_id'] == null) {
        // audio too quiet / nothing heard: let the teacher retry or tick by hand
        setState(() {
          _stage = _Stage.ready;
          _notice = tr(
            'Could not hear the child clearly. Try again in a quiet place, or tick the words by hand.',
            'बच्चे की आवाज़ साफ़ नहीं सुनाई दी। शांत जगह पर दोबारा करें, या शब्द हाथ से चुनें।',
          );
        });
        return;
      }
      final proposal = (resp['proposal'] as Map?) ?? const {};
      final res = proposal['result'] as String?;
      setState(() {
        _resp = resp;
        _result = const ['correct', 'partial', 'incorrect'].contains(res)
            ? res!
            : 'partial';
        _stage = _Stage.result;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _stage = _Stage.ready;
        _notice = trf(
          'Could not score the recording ({short}). Try again, or tick the words by hand.',
          'रिकॉर्डिंग जाँच नहीं पाए ({short})। दोबारा करें, या शब्द हाथ से चुनें।', {'short': _short(e)},
        );
      });
    }
  }

  String _short(Object e) {
    final s = e.toString();
    return s.length > 80 ? '${s.substring(0, 80)}…' : s;
  }

  /// Saves the scored recording through the proposal the server stored.
  Future<void> _confirm() async {
    final resp = _resp!;
    final proposal = (resp['proposal'] as Map?) ?? const {};
    final score = (resp['score'] as Map?) ?? const {};
    final accuracy = (score['accuracy'] as num?)?.toDouble();
    setState(() => _saving = true);
    try {
      final r = await Api.i.postQueued(
        '/v1/captures/${resp['capture_id']}/confirm',
        {
          'accepted': [
            {
              'child_id': widget.childId,
              'checkpoint_id': widget.checkpointId,
              'result': _result,
              'misconception': proposal['misconception'],
              'confidence': (proposal['confidence'] as num?) ?? 0.8,
              'score': ?accuracy,
            },
          ],
        },
      );
      _done(r);
    } catch (e) {
      _failed(e);
    }
  }

  /// Manual fallback: the teacher's ✓/✗ per word becomes one tap result for the lesson.
  Future<void> _saveManual() async {
    final ok = _ticks.where((t) => t == true).length;
    final ratio = ok / widget.targets.length;
    final result = ratio >= 0.75
        ? 'correct'
        : (ratio >= 0.4 ? 'partial' : 'incorrect');
    setState(() => _saving = true);
    try {
      final r = await Api.i.postQueued(
        '/v1/classes/${widget.classId}/captures/tap',
        {
          'items': [
            {
              'child_id': widget.childId,
              'checkpoint_id': widget.checkpointId,
              'result': result,
            },
          ],
        },
      );
      _done(r);
    } catch (e) {
      _failed(e);
    }
  }

  void _done(dynamic r) {
    if (!mounted) return;
    final queued = r is Map && r['queued'] == true;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          queued
              ? tr(
                  'No internet. Saved on this phone and will send later.',
                  'इंटरनेट नहीं है। फ़ोन में रखा है, बाद में भेजा जाएगा।',
                )
              : tr('Saved.', 'दर्ज हो गया।'),
        ),
      ),
    );
    Navigator.of(context).pop(true);
  }

  void _failed(Object e) {
    if (!mounted) return;
    setState(() {
      _saving = false;
      _notice = trf(
        'Could not save: {short}',
        'दर्ज नहीं हो पाया: {short}', {'short': _short(e)},
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          16,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      tr('Reading check', 'पढ़ने की जाँच'),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: tr('Close', 'बंद करें'),
                    onPressed: _saving || _stage == _Stage.busy
                        ? null
                        : () => Navigator.of(context).pop(false),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              Text(widget.title, style: const TextStyle(color: Ks.muted)),
              const SizedBox(height: 4),
              Text(
                trf(
                  'Ask {childName} to read these aloud.',
                  '{childName} से ये ज़ोर से पढ़वाएँ।', {'childName': widget.childName},
                ),
              ),
              const SizedBox(height: 14),
              if (_notice != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(
                    _notice!,
                    style: const TextStyle(color: Ks.rose, fontSize: 14),
                  ),
                ),
              if (_stage == _Stage.result)
                ..._resultView()
              else if (_stage == _Stage.manual)
                ..._manualView()
              else
                ..._readView(),
            ],
          ),
        ),
      ),
    );
  }

  // ---- step 1: words + record
  List<Widget> _readView() {
    final recording = _stage == _Stage.recording;
    final busy = _stage == _Stage.busy;
    return [
      Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          for (final w in widget.targets)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
              decoration: BoxDecoration(
                color: Ks.accentSoft,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Text(
                w,
                style: const TextStyle(
                  fontSize: 34,
                  fontWeight: FontWeight.w600,
                  color: Ks.ink,
                ),
              ),
            ),
        ],
      ),
      const SizedBox(height: 20),
      Center(
        child: InkWell(
          onTap: busy || _saving ? null : _toggleRecord,
          customBorder: const CircleBorder(),
          child: Container(
            width: 84,
            height: 84,
            decoration: BoxDecoration(
              color: busy ? Ks.muted : (recording ? Ks.rose : Ks.accent),
              shape: BoxShape.circle,
            ),
            child: busy
                ? const Padding(
                    padding: EdgeInsets.all(26),
                    child: CircularProgressIndicator(
                      color: Colors.white,
                      strokeWidth: 3,
                    ),
                  )
                : Icon(
                    recording ? Icons.stop_rounded : Icons.mic_rounded,
                    color: Colors.white,
                    size: 42,
                  ),
          ),
        ),
      ),
      Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Center(
          child: Text(
            busy
                ? tr('Checking the reading…', 'पढ़ना जाँच रहे हैं…')
                : recording
                ? tr(
                    'Listening… tap to stop',
                    'सुन रहे हैं… रोकने के लिए टैप करें',
                  )
                : tr(
                    'Tap and let the child read',
                    'टैप करें और बच्चे को पढ़ने दें',
                  ),
            style: TextStyle(color: recording ? Ks.rose : Ks.muted),
          ),
        ),
      ),
      const SizedBox(height: 8),
      Center(
        child: TextButton(
          onPressed: busy || recording
              ? null
              : () => setState(() {
                  _stage = _Stage.manual;
                  _notice = null;
                }),
          child: Text(tr('Tick the words by hand', 'शब्द हाथ से चुनें')),
        ),
      ),
    ];
  }

  // ---- step 2: scored result
  String _judgedLabel(String j) =>
      {
        'correct': tr('Correct', 'सही'),
        'close': tr('Close', 'करीब'),
        'wrong': tr('Wrong', 'गलत'),
        'omitted': tr('Missed', 'छूटा'),
      }[j] ??
      j;

  List<Widget> _resultView() {
    final score = (_resp!['score'] as Map?) ?? const {};
    final items = ((score['items'] as List?) ?? const [])
        .cast<Map<dynamic, dynamic>>();
    final note = (_resp!['proposal'] as Map?)?['note_for_teacher_hi'];
    return [
      for (final it in items) _scoreRow(it),
      if ((score['summary_hi'] as String?)?.isNotEmpty == true)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(
            score['summary_hi'],
            style: const TextStyle(color: Ks.muted, fontSize: 14),
          ),
        ),
      if (note is String && note.isNotEmpty && note != score['summary_hi'])
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text(
            note,
            style: const TextStyle(color: Ks.muted, fontSize: 14),
          ),
        ),
      const SizedBox(height: 14),
      Text(
        tr('Save as', 'इस रूप में दर्ज करें'),
        style: const TextStyle(fontWeight: FontWeight.w700),
      ),
      const SizedBox(height: 6),
      Wrap(
        spacing: 8,
        children: [
          for (final r in const ['correct', 'partial', 'incorrect'])
            ChoiceChip(
              label: Text(_resultLabel(r)),
              selected: _result == r,
              onSelected: _saving ? null : (_) => setState(() => _result = r),
            ),
        ],
      ),
      const SizedBox(height: 14),
      FilledButton.icon(
        onPressed: _saving ? null : _confirm,
        icon: const Icon(Icons.check_rounded),
        label: Text(
          _saving
              ? tr('Saving…', 'दर्ज हो रहा है…')
              : tr('Confirm and save', 'पुष्टि करें और दर्ज करें'),
        ),
      ),
      Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          TextButton(
            onPressed: _saving
                ? null
                : () => setState(() {
                    _stage = _Stage.ready;
                    _resp = null;
                    _notice = null;
                  }),
            child: Text(tr('Record again', 'दोबारा रिकॉर्ड करें')),
          ),
          TextButton(
            onPressed: _saving
                ? null
                : () => setState(() {
                    _stage = _Stage.manual;
                    _resp = null;
                    _notice = null;
                  }),
            child: Text(tr('Tick by hand', 'हाथ से चुनें')),
          ),
        ],
      ),
    ];
  }

  String _resultLabel(String r) =>
      {
        'correct': tr('Doing well', 'ठीक चल रहा है'),
        'partial': tr('Partly', 'थोड़ा'),
        'incorrect': tr('Needs help', 'मदद चाहिए'),
      }[r] ??
      r;

  Widget _scoreRow(Map it) {
    final j = '${it['judged'] ?? ''}';
    final ok = j == 'correct';
    final near = j == 'close';
    final color = ok ? Ks.green : (near ? Ks.amber : Ks.rose);
    final icon = ok
        ? Icons.check_circle_rounded
        : (near ? Icons.remove_circle_rounded : Icons.cancel_rounded);
    final heard = it['heard'] as String?;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(width: 10),
          Text('${it['target']}', style: const TextStyle(fontSize: 24)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              ok || heard == null || heard.isEmpty
                  ? ''
                  : trf('heard: {heard}', 'सुना: {heard}', {'heard': heard}),
              style: const TextStyle(color: Ks.muted, fontSize: 13),
            ),
          ),
          Text(
            _judgedLabel(j),
            style: TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }

  // ---- manual fallback
  List<Widget> _manualView() {
    final allMarked = !_ticks.contains(null);
    return [
      for (var i = 0; i < widget.targets.length; i++)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  widget.targets[i],
                  style: const TextStyle(fontSize: 28),
                ),
              ),
              IconButton.filledTonal(
                tooltip: tr('Read correctly', 'सही पढ़ा'),
                isSelected: _ticks[i] == true,
                style: IconButton.styleFrom(
                  backgroundColor: _ticks[i] == true ? Ks.green : null,
                  foregroundColor: _ticks[i] == true ? Colors.white : Ks.green,
                ),
                onPressed: _saving
                    ? null
                    : () => setState(() => _ticks[i] = true),
                icon: const Icon(Icons.check_rounded),
              ),
              const SizedBox(width: 6),
              IconButton.filledTonal(
                tooltip: tr('Not correct', 'सही नहीं'),
                isSelected: _ticks[i] == false,
                style: IconButton.styleFrom(
                  backgroundColor: _ticks[i] == false ? Ks.rose : null,
                  foregroundColor: _ticks[i] == false ? Colors.white : Ks.rose,
                ),
                onPressed: _saving
                    ? null
                    : () => setState(() => _ticks[i] = false),
                icon: const Icon(Icons.close_rounded),
              ),
            ],
          ),
        ),
      const SizedBox(height: 14),
      FilledButton.icon(
        onPressed: _saving || !allMarked ? null : _saveManual,
        icon: const Icon(Icons.save_rounded),
        label: Text(
          _saving
              ? tr('Saving…', 'दर्ज हो रहा है…')
              : tr('Save check', 'जाँच दर्ज करें'),
        ),
      ),
      Center(
        child: TextButton(
          onPressed: _saving
              ? null
              : () => setState(() {
                  _stage = _Stage.ready;
                  _notice = null;
                }),
          child: Text(tr('Record instead', 'रिकॉर्ड करके देखें')),
        ),
      ),
    ];
  }
}
