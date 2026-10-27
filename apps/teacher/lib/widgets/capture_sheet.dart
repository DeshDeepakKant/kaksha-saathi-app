import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../record_audio.dart';
import '../theme.dart';
import '../l10n.dart';

/// Evidence capture: three zero- or low-friction paths.
///  - Tap (works offline-free, zero AI): child × checkpoint ✓ / ~ / ✗
///  - Voice note: record → (server ASR+Claude or keyword rules) → chips → confirm
///  - Work photo: camera/gallery → per-question verdicts (arithmetic-checked) → confirm
class CaptureSheet extends StatefulWidget {
  const CaptureSheet({
    super.key,
    required this.classId,
    required this.subject,
    this.presetChildren,
  });
  final int classId;
  final String subject;
  final List<Map<String, dynamic>>? presetChildren;
  @override
  State<CaptureSheet> createState() => _CaptureSheetState();
}

class _CaptureSheetState extends State<CaptureSheet> {
  String _mode = 'tap';
  bool _changed = false;
  late Future<dynamic> _checkpoints;

  @override
  void initState() {
    super.initState();
    _checkpoints = Api.i.get(
      '/v1/classes/${widget.classId}/roadmap?subject=${widget.subject}',
    );
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.92,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 8, 6),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    tr('Add evidence', 'साक्ष्य जोड़ें'),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                if (_changed)
                  const Icon(Icons.check_circle_rounded, color: Ks.green),
                IconButton(
                  onPressed: () => Navigator.of(context).pop(_changed),
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: SegmentedButton<String>(
              segments: [
                ButtonSegment(
                  value: 'tap',
                  label: Text(tr('Tap', 'टैप')),
                  icon: Icon(Icons.touch_app_rounded),
                ),
                ButtonSegment(
                  value: 'note',
                  label: Text(tr('Voice', 'आवाज़')),
                  icon: Icon(Icons.mic_rounded),
                ),
                ButtonSegment(
                  value: 'photo',
                  label: Text(tr('Photo', 'फ़ोटो')),
                  icon: Icon(Icons.photo_camera_rounded),
                ),
              ],
              selected: {_mode},
              onSelectionChanged: (s) => setState(() => _mode = s.first),
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: switch (_mode) {
              'tap' => _TapPanel(
                classId: widget.classId,
                subject: widget.subject,
                checkpoints: _checkpoints,
                preset: widget.presetChildren,
                onChanged: () => setState(() => _changed = true),
              ),
              'note' => _NotePanel(
                classId: widget.classId,
                subject: widget.subject,
                onChanged: () => setState(() => _changed = true),
              ),
              _ => _PhotoPanel(
                classId: widget.classId,
                subject: widget.subject,
                onChanged: () => setState(() => _changed = true),
              ),
            },
          ),
        ],
      ),
    );
  }
}

// ------------------------------------------------------------------ TAP
class _TapPanel extends StatefulWidget {
  const _TapPanel({
    required this.classId,
    required this.subject,
    required this.checkpoints,
    required this.onChanged,
    this.preset,
  });
  final int classId;
  final String subject;
  final Future<dynamic> checkpoints;
  final VoidCallback onChanged;
  final List<Map<String, dynamic>>? preset;
  @override
  State<_TapPanel> createState() => _TapPanelState();
}

class _TapPanelState extends State<_TapPanel> {
  final Map<String, String> _vals = {}; // "childId|cpId" -> result
  String? _cp;
  late final Future<List<dynamic>> _data;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _data = Future.wait([widget.checkpoints, Api.i.roster(widget.classId)]);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
      future: _data,
      builder: (context, snap) {
        if (!snap.hasData) return const Loading();
        final rm = snap.data![0] as Map<String, dynamic>;
        final items = (rm['items'] as List).cast<Map<String, dynamic>>();
        final roster = (snap.data![1] as List).cast<Map<String, dynamic>>();
        final kids = widget.preset ?? roster;
        _cp ??= _guessCheckpoint(items);
        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: DropdownButtonFormField<String>(
                initialValue: _cp,
                isExpanded: true,
                decoration: InputDecoration(
                  labelText: tr(
                    'Which lesson are you checking?',
                    'कौन सा सबक जाँच रहे हैं?',
                  ),
                ),
                items: [
                  for (final it in items.where(
                    (i) => (i['checkpoint_id'] as String?)?.isNotEmpty == true,
                  ))
                    DropdownMenuItem(
                      value: it['checkpoint_id'] as String,
                      child: Text(
                        '${it['chapter']} · ${cpTitle(it)}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (v) => setState(() => _cp = v),
              ),
            ),
            const SizedBox(height: 6),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 90),
                itemCount: kids.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (_, i) {
                  final c = kids[i];
                  final key = '${c['id']}|$_cp';
                  final v = _vals[key];
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      child: Row(
                        children: [
                          CircleAvatar(
                            backgroundColor: Ks.accentSoft,
                            child: Text(
                              '${c['roll_no']}',
                              style: const TextStyle(
                                color: Ks.accent,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              c['first_name'],
                              style: const TextStyle(fontSize: 17),
                            ),
                          ),
                          _triple(v, (r) => setState(() => _vals[key] = r)),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: FilledButton.icon(
                onPressed: _vals.isEmpty || _busy ? null : _save,
                icon: Icon(
                  _busy ? Icons.hourglass_top_rounded : Icons.save_rounded,
                ),
                label: Text(
                  tr('Save (${_vals.length})', 'सहेजें (${_vals.length})'),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  String? _guessCheckpoint(List<Map<String, dynamic>> items) {
    for (final it in items.reversed) {
      if ((it['checkpoint_id'] as String?)?.isNotEmpty == true) {
        return it['checkpoint_id'];
      }
    }
    return null;
  }

  Widget _triple(String? v, ValueChanged<String> onTap) {
    Widget b(String val, IconData icon, Color color, String hi) => Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => onTap(val),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            padding: const EdgeInsets.symmetric(vertical: 10),
            decoration: BoxDecoration(
              color: v == val ? color.withValues(alpha: 0.15) : Ks.paper,
              border: Border.all(
                color: v == val ? color : Ks.line,
                width: v == val ? 2 : 1,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, color: v == val ? color : Ks.muted, size: 24),
                Text(
                  hi,
                  style: TextStyle(
                    fontSize: 12,
                    color: v == val ? color : Ks.muted,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    // The inner Row uses Expanded, so it needs a bounded width: it sits in an
    // outer Row as a non-flex child, where the incoming width is unbounded.
    return SizedBox(
      width: 168,
      child: Row(
        children: [
          b('correct', Icons.check_rounded, Ks.green, tr('Correct', 'सही')),
          b('partial', Icons.remove_rounded, Ks.amber, tr('Partly', 'थोड़ा')),
          b('incorrect', Icons.close_rounded, Ks.rose, tr('Wrong', 'गलत')),
        ],
      ),
    );
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final items = _vals.entries.map((e) {
        final parts = e.key.split('|');
        return {
          'child_id': int.parse(parts[0]),
          'checkpoint_id': parts[1],
          'result': e.value,
        };
      }).toList();
      await Api.i.tap(widget.classId, items);
      widget.onChanged();
      _vals.clear();
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(tr('Saved.', 'दर्ज हो गया।'))));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

// ------------------------------------------------------------------ NOTE
class _NotePanel extends StatefulWidget {
  const _NotePanel({
    required this.classId,
    required this.subject,
    required this.onChanged,
  });
  final int classId;
  final String subject;
  final VoidCallback onChanged;
  @override
  State<_NotePanel> createState() => _NotePanelState();
}

class _NotePanelState extends State<_NotePanel> {
  final _text = TextEditingController();
  final Recorder _rec = Recorder();
  bool _recording = false;
  bool _busy = false;
  Map<String, dynamic>? _resp;
  final Map<String, String> _decisions =
      {}; // draft index -> result/absent/skip

  @override
  void dispose() {
    _rec.dispose();
    super.dispose();
  }

  Future<void> _toggleRecord() async {
    if (!_recording) {
      final ok = await _rec.start();
      if (!ok) {
        _toast(
          tr(
            'Mic not available — type below instead.',
            'माइक उपलब्ध नहीं — नीचे लिखकर लिखें।',
          ),
        );
        return;
      }
      setState(() => _recording = true);
    } else {
      final bytes = await _rec.stop();
      setState(() => _recording = false);
      if (bytes == null || bytes.isEmpty) {
        _toast(tr('Recording was empty', 'रिकॉर्डिंग खाली रही'));
        return;
      }
      await _send(audio: bytes);
    }
  }

  Future<void> _send({List<int>? audio}) async {
    setState(() {
      _busy = true;
      _resp = null;
    });
    try {
      final fields = <String, String>{'subject': widget.subject};
      if (audio == null) {
        fields['transcript'] = _text.text;
      }
      final r = await Api.i.postMultipart(
        '/v1/classes/${widget.classId}/captures/note',
        fields: fields,
        file: audio == null ? null : Uint8List.fromList(audio),
        fieldName: 'audio',
        filename: 'note.webm',
      );
      setState(() {
        _resp = (r as Map).cast<String, dynamic>();
        _decisions.clear();
        for (var i = 0; i < ((_resp!['drafts'] as List?)?.length ?? 0); i++) {
          final d = (_resp!['drafts'] as List)[i] as Map<String, dynamic>;
          _decisions['$i'] = d['status'] == 'absent'
              ? 'absent'
              : (d['result'] ?? 'incorrect');
        }
      });
    } catch (e) {
      _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final resp = _resp!;
    final drafts = (resp['drafts'] as List).cast<Map<String, dynamic>>();
    final accepted = <Map<String, dynamic>>[];
    for (var i = 0; i < drafts.length; i++) {
      final d = drafts[i];
      final dec = _decisions['$i'];
      if (dec == 'skip' || dec == null || d['checkpoint_id'] == null) continue;
      accepted.add({
        'child_id': d['child_id'],
        'checkpoint_id': d['checkpoint_id'],
        'result': dec,
        'confidence': d['confidence'] ?? 0.7,
        'quote': d['quote'],
      });
    }
    setState(() => _busy = true);
    try {
      await Api.i.postJson('/v1/captures/${resp['capture_id']}/confirm', {
        'accepted': accepted,
      });
      widget.onChanged();
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  @override
  Widget build(BuildContext context) {
    final resp = _resp;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 90),
      children: [
        Text(
          tr(
            'Speak for 20 seconds after class — who was absent, who struggled with what.',
            'कक्षा के बाद 20 सेकंड में बोलें — कौन नहीं आया, किसे क्या कठिन लगा।',
          ),
          style: TextStyle(color: Ks.muted),
        ),
        const SizedBox(height: 12),
        Center(
          child: InkWell(
            onTap: _busy ? null : _toggleRecord,
            customBorder: const CircleBorder(),
            child: Container(
              width: 92,
              height: 92,
              decoration: BoxDecoration(
                color: _recording ? Ks.rose : Ks.accent,
                shape: BoxShape.circle,
              ),
              child: Icon(
                _recording ? Icons.stop_rounded : Icons.mic_rounded,
                color: Colors.white,
                size: 44,
              ),
            ),
          ),
        ),
        if (_recording)
          Padding(
            padding: EdgeInsets.only(top: 8),
            child: Center(
              child: Text(
                tr('Listening…', 'सुन रहे हैं…'),
                style: TextStyle(color: Ks.rose),
              ),
            ),
          ),
        const SizedBox(height: 10),
        Center(
          child: Text(
            tr('Or type', 'या लिखें'),
            style: TextStyle(color: Ks.muted),
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _text,
          minLines: 2,
          maxLines: 4,
          decoration: InputDecoration(
            hintText: tr(
              'Did subtraction with borrowing today. Meena didn\'t get borrowing…',
              'आज उधार वाला घटाव कराया। मीना को उधार समझ नहीं आया…',
            ),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _busy || _text.text.trim().isEmpty ? null : () => _send(),
          icon: const Icon(Icons.send_rounded),
          label: Text(
            _busy
                ? tr('Understanding…', 'समझ रहे हैं…')
                : tr('Understand', 'समझें'),
          ),
        ),
        if (resp != null) ..._result(resp),
      ],
    );
  }

  List<Widget> _result(Map<String, dynamic> resp) {
    final drafts = (resp['drafts'] as List).cast<Map<String, dynamic>>();
    final unresolved = (resp['unresolved'] as List?) ?? [];
    final fallback = resp['ai_status'] != 'ready';
    return [
      const SizedBox(height: 16),
      Text(
        tr('AI understood this — please check', 'AI ने यह समझा — जाँचें'),
        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
      ),
      if (fallback && resp['note'] != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            resp['note'],
            style: const TextStyle(fontSize: 13, color: Ks.muted),
          ),
        ),
      const SizedBox(height: 10),
      for (var i = 0; i < drafts.length; i++) _draftTile(i, drafts[i]),
      if (unresolved.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(
            tr(
              'Not understood: ${unresolved.map((u) => u['name']).join(', ')}',
              'समझ नहीं आया: ${unresolved.map((u) => u['name']).join(', ')}',
            ),
            style: const TextStyle(color: Ks.muted),
          ),
        ),
      const SizedBox(height: 12),
      FilledButton.icon(
        onPressed: _busy ? null : _confirm,
        icon: const Icon(Icons.check_rounded),
        label: Text(tr('Confirm', 'पुष्टि करें')),
      ),
    ];
  }

  Widget _draftTile(int i, Map<String, dynamic> d) {
    final isAbsent = d['status'] == 'absent';
    final dec = _decisions['$i'] ?? 'skip';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    d['first_name'] ?? d['name'] ?? '?',
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 16,
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: Ks.accentSoft,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    isAbsent
                        ? tr('Absent', 'अनुपस्थित')
                        : (d['name_status'] == 'matched'
                                  ? 'AI'
                                  : tr('Close match', 'मिलता-जुलता'))
                              .toString(),
                    style: const TextStyle(fontSize: 11, color: Ks.accent),
                  ),
                ),
              ],
            ),
            if ((d['quote'] as String?)?.isNotEmpty == true)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  '"${d['quote']}"',
                  style: const TextStyle(
                    fontStyle: FontStyle.italic,
                    color: Ks.muted,
                    fontSize: 13,
                  ),
                ),
              ),
            if (!isAbsent)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(
                  spacing: 6,
                  children: [
                    for (final opt in const [
                      'correct',
                      'partial',
                      'incorrect',
                      'skip',
                    ])
                      ChoiceChip(
                        label: Text(
                          {
                            'correct': tr('Correct', 'सही'),
                            'partial': tr('Partly', 'थोड़ा'),
                            'incorrect': tr('Wrong', 'गलत'),
                            'skip': tr('Skip', 'छोड़ें'),
                          }[opt]!,
                        ),
                        selected: dec == opt,
                        onSelected: (_) =>
                            setState(() => _decisions['$i'] = opt),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------ PHOTO (camera/gallery on web input[file], via a simple picker on Android)
class _PhotoPanel extends StatefulWidget {
  const _PhotoPanel({
    required this.classId,
    required this.subject,
    required this.onChanged,
  });
  final int classId;
  final String subject;
  final VoidCallback onChanged;
  @override
  State<_PhotoPanel> createState() => _PhotoPanelState();
}

class _PhotoPanelState extends State<_PhotoPanel> {
  Future<dynamic>? _roster;
  int? _childId;
  bool _busy = false;
  String? _message;
  Map<String, dynamic>? _result;
  final Map<int, String> _verdicts =
      {}; // question index -> correct|incorrect|partial

  @override
  void initState() {
    super.initState();
    _roster = Api.i.roster(widget.classId);
  }

  Future<void> _pick() async {
    if (_childId == null) {
      _toast(tr('Choose a child first', 'पहले बच्चा चुनें'));
      return;
    }
    try {
      final picker = ImagePicker();
      final file = await picker.pickImage(
        source: ImageSource.camera,
        maxWidth: 1600,
        imageQuality: 82,
      );
      if (file == null) return;
      final bytes = await file.readAsBytes();
      setState(() {
        _busy = true;
        _message = null;
        _result = null;
      });
      final r = await Api.i.postMultipart(
        '/v1/classes/${widget.classId}/captures/photo',
        fields: {'child_id': '$_childId', 'subject': widget.subject},
        file: bytes,
        filename: file.name.isEmpty ? 'page.jpg' : file.name,
      );
      final map = (r as Map).cast<String, dynamic>();
      if (map['ai_status'] == 'retake') {
        setState(
          () => _message =
              map['message'] as String? ??
              tr(
                'The photo isn\'t clear — retake it.',
                'फ़ोटो साफ़ नहीं है — दोबारा लें।',
              ),
        );
        return;
      }
      final qs = (map['questions'] as List?) ?? const [];
      _verdicts.clear();
      for (var i = 0; i < qs.length; i++) {
        final q = qs[i] as Map<String, dynamic>;
        final v = q['verdict'] as String?;
        _verdicts[i] = (v == 'correct' || v == 'incorrect') ? v! : 'correct';
      }
      setState(() => _result = map);
    } on ApiError catch (e) {
      setState(() => _message = e.message);
    } catch (e) {
      setState(
        () => _message = tr(
          'Could not open the photo: $e',
          'फ़ोटो नहीं खुल सकी: $e',
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final res = _result!;
    final qs = (res['questions'] as List).cast<Map<String, dynamic>>();
    final accepted = <Map<String, dynamic>>[];
    final perCp = <String, List<int>>{}; // cp -> [correct, total]
    for (var i = 0; i < qs.length; i++) {
      final cp = qs[i]['checkpoint_id'] as String?;
      if (cp == null) continue;
      final v = _verdicts[i] ?? 'correct';
      final bucket = perCp.putIfAbsent(cp, () => [0, 0]);
      if (v == 'correct') bucket[0]++;
      bucket[1]++;
    }
    perCp.forEach((cp, counts) {
      final ratio = counts[1] == 0 ? 0.0 : counts[0] / counts[1];
      final result = ratio >= 0.8
          ? 'correct'
          : (ratio >= 0.4 ? 'partial' : 'incorrect');
      accepted.add({
        'child_id': res['child']['id'],
        'checkpoint_id': cp,
        'result': result,
        'score': ratio,
        'confidence': (res['page']?['page_confidence'] ?? 0.8),
      });
    });
    if (accepted.isEmpty) {
      _toast(
        tr(
          'No question is linked to a lesson — check with taps',
          'कोई सवाल किसी सबक से नहीं जुड़ा — टैप से जाँचें',
        ),
      );
      return;
    }
    setState(() => _busy = true);
    try {
      await Api.i.postJson('/v1/captures/${res['capture_id']}/confirm', {
        'accepted': accepted,
      });
      widget.onChanged();
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiError catch (e) {
      _toast(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
      future: _roster,
      builder: (context, snap) {
        final kids = snap.hasData
            ? (snap.data as List).cast<Map<String, dynamic>>()
            : <Map<String, dynamic>>[];
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 90),
          children: [
            Text(
              tr(
                'Take a photo of the page — notebook only, no faces. Answers are checked by code.',
                'पन्ने की फ़ोटो लें — सिर्फ़ कॉपी, चेहरा नहीं। जवाब कोड से जाँचे जाएँगे।',
              ),
              style: TextStyle(color: Ks.muted),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<int>(
              initialValue: _childId,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: tr('Whose work is this?', 'किस बच्चे का काम?'),
              ),
              items: [
                for (final c in kids)
                  DropdownMenuItem(
                    value: c['id'] as int,
                    child: Text('${c['roll_no']} · ${c['first_name']}'),
                  ),
              ],
              onChanged: (v) => setState(() => _childId = v),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _busy ? null : _pick,
              icon: const Icon(Icons.photo_camera_rounded),
              label: Text(
                _busy
                    ? tr('Reading…', 'पढ़ा जा रहा है…')
                    : tr('Take photo and read', 'फ़ोटो लें और पढ़ें'),
              ),
            ),
            if (_message != null) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Ks.amberSoft,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(_message!, style: const TextStyle(color: Ks.amber)),
              ),
            ],
            if (_result != null) ..._resultView(_result!),
          ],
        );
      },
    );
  }

  List<Widget> _resultView(Map<String, dynamic> res) {
    final qs = (res['questions'] as List).cast<Map<String, dynamic>>();
    final fallback = res['ai_status'] != 'ready';
    return [
      const SizedBox(height: 16),
      Text(
        tr('AI read this — please check', 'AI ने यह पढ़ा — जाँचें'),
        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
      ),
      if (fallback && res['note'] != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            res['note'],
            style: const TextStyle(fontSize: 13, color: Ks.muted),
          ),
        ),
      const SizedBox(height: 8),
      if (qs.isEmpty)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tr(
                    'Could not read questions from this page.',
                    'इस पन्ने से सवाल नहीं पढ़े जा सके।',
                  ),
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
                SizedBox(height: 4),
                Text(
                  tr(
                    'Use the Tap tab to check in 20 seconds — it always works.',
                    'टैप टैब में जाकर 20 सेकंड में जाँचें — वह हमेशा काम करता है।',
                  ),
                  style: TextStyle(color: Ks.muted),
                ),
              ],
            ),
          ),
        ),
      for (var i = 0; i < qs.length; i++) _qTile(i, qs[i]),
      if (qs.isNotEmpty) ...[
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: _busy ? null : _confirm,
          icon: const Icon(Icons.check_rounded),
          label: Text(tr('Confirm', 'पुष्टि करें')),
        ),
      ],
    ];
  }

  Widget _qTile(int i, Map<String, dynamic> q) {
    final v = _verdicts[i] ?? 'correct';
    final arith = q['arith_checked'] == true;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${q['printed']} ${q['student_answer'] ?? ''}',
                    style: const TextStyle(
                      fontSize: 18,
                      fontFeatures: [FontFeature.tabularFigures()],
                    ),
                  ),
                ),
                if (arith)
                  Tooltip(
                    message: q['expected'] != null
                        ? tr(
                            'Correct answer: ${q['expected']}',
                            'सही उत्तर: ${q['expected']}',
                          )
                        : tr('Checked by code', 'कोड से जाँचा'),
                    child: const Icon(
                      Icons.calculate_rounded,
                      size: 16,
                      color: Ks.muted,
                    ),
                  ),
              ],
            ),
            if ((q['checkpoint_id'] as String?) == null)
              Padding(
                padding: EdgeInsets.only(top: 2),
                child: Text(
                  tr('Not linked to a lesson', 'किसी सबक से नहीं जुड़ा'),
                  style: TextStyle(fontSize: 12, color: Ks.muted),
                ),
              ),
            if (q['override_note'] == 'arithmetic')
              Padding(
                padding: EdgeInsets.only(top: 2),
                child: Text(
                  tr('Corrected by calculation', 'गणना से सुधारा गया'),
                  style: TextStyle(fontSize: 12, color: Ks.accent),
                ),
              ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              children: [
                for (final opt in const ['correct', 'partial', 'incorrect'])
                  ChoiceChip(
                    label: Text(
                      {
                        'correct': tr('Correct', 'सही'),
                        'partial': tr('Partly', 'थोड़ा'),
                        'incorrect': tr('Wrong', 'गलत'),
                      }[opt]!,
                    ),
                    selected: v == opt,
                    onSelected: (sel) => setState(() => _verdicts[i] = opt),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
