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
    this.presetCheckpointId,
    this.presetChildIds,
  });
  final int classId;
  final String subject;
  final List<Map<String, dynamic>>? presetChildren;

  /// Open on the tap tab with this lesson selected (plan card "Check now", profile "Add evidence").
  final String? presetCheckpointId;

  /// Only show these children in the tap grid (null = whole class).
  final List<int>? presetChildIds;
  @override
  State<CaptureSheet> createState() => _CaptureSheetState();
}

/// Roadmap loader the panels share: the first call reuses the request the sheet already
/// started; `refresh: true` fetches again (Retry).
typedef _RoadmapLoader = Future<dynamic> Function({bool refresh});

const _kResults = ['correct', 'partial', 'incorrect'];

bool _validResult(Object? v) => v is String && _kResults.contains(v);

String _resultLabel(String r) => switch (r) {
  'correct' => tr('Correct', 'सही'),
  'partial' => tr('Partly', 'थोड़ा'),
  'incorrect' => tr('Wrong', 'गलत'),
  _ => tr('Skip', 'छोड़ें'),
};

bool _wasQueued(dynamic r) => r is Map && r['queued'] == true;

String _queuedMsg() => tr(
  'Saved on this phone — will send when online.',
  'इस फ़ोन पर सहेजा — नेट आने पर भेजा जाएगा।',
);

/// Guardrail counter: an AI result the teacher walked away from counts as rejected.
/// Never blocks the UI and errors are ignored.
void _rejectQuietly(int? captureId) {
  if (captureId == null) return;
  try {
    Api.i
        .postJson('/v1/captures/$captureId/confirm', {
          'accepted': <Map<String, dynamic>>[],
          'reject_all': true,
        })
        .catchError((_) {});
  } catch (_) {}
}

class _CaptureSheetState extends State<CaptureSheet> {
  String _mode = 'tap';
  bool _changed = false;
  late Future<dynamic> _checkpoints;

  Future<dynamic> _fetchRoadmap() {
    final f = Api.i.get(
      '/v1/classes/${widget.classId}/roadmap?subject=${widget.subject}',
    );
    // A panel may not be listening yet (or ever); keep a failed fetch from going unhandled.
    f.then((_) {}, onError: (_) {});
    return f;
  }

  Future<dynamic> _roadmap({bool refresh = false}) {
    if (refresh) _checkpoints = _fetchRoadmap();
    return _checkpoints;
  }

  @override
  void initState() {
    super.initState();
    _checkpoints = _fetchRoadmap();
  }

  void _markChanged() => setState(() => _changed = true);

  void _close() => Navigator.of(context).pop(_changed);

  @override
  Widget build(BuildContext context) {
    final inset = MediaQuery.of(context).viewInsets.bottom;
    // Back, the barrier and the close button all report whether anything changed so
    // the board refreshes. (Navigator.pop from a confirm still returns its own `true`.)
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _close();
      },
      child: Padding(
        // lift the sheet above the keyboard so a typed note is never hidden
        padding: EdgeInsets.only(bottom: inset),
        child: SizedBox(
          height: MediaQuery.of(context).size.height * 0.92,
          child: Column(
            children: [
              // Dragging the header down closes through _close too (the sheet's own
              // drag would pop with null and the board would not refresh).
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onVerticalDragEnd: (d) {
                  if ((d.primaryVelocity ?? 0) > 600) _close();
                },
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
                            const Icon(
                              Icons.check_circle_rounded,
                              color: Ks.green,
                            ),
                          IconButton(
                            onPressed: _close,
                            constraints: const BoxConstraints(
                              minWidth: 48,
                              minHeight: 48,
                            ),
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
                        onSelectionChanged: (s) =>
                            setState(() => _mode = s.first),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Expanded(
                child: switch (_mode) {
                  'tap' => _TapPanel(
                    classId: widget.classId,
                    subject: widget.subject,
                    roadmap: _roadmap,
                    preset: widget.presetChildren,
                    presetCheckpointId: widget.presetCheckpointId,
                    presetChildIds: widget.presetChildIds,
                    onChanged: _markChanged,
                  ),
                  'note' => _NotePanel(
                    classId: widget.classId,
                    subject: widget.subject,
                    roadmap: _roadmap,
                    onChanged: _markChanged,
                  ),
                  _ => _PhotoPanel(
                    classId: widget.classId,
                    subject: widget.subject,
                    onChanged: _markChanged,
                  ),
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------ TAP
class _TapData {
  _TapData(this.items, this.roster);
  final List<Map<String, dynamic>>
  items; // roadmap lessons that have a checkpoint
  final List<Map<String, dynamic>> roster;
}

class _TapPanel extends StatefulWidget {
  const _TapPanel({
    required this.classId,
    required this.subject,
    required this.roadmap,
    required this.onChanged,
    this.preset,
    this.presetCheckpointId,
    this.presetChildIds,
  });
  final int classId;
  final String subject;
  final _RoadmapLoader roadmap;
  final VoidCallback onChanged;
  final List<Map<String, dynamic>>? preset;
  final String? presetCheckpointId;
  final List<int>? presetChildIds;
  @override
  State<_TapPanel> createState() => _TapPanelState();
}

class _TapPanelState extends State<_TapPanel> {
  // cp -> (childId -> result). Kept per lesson; Save sends every lesson's marks and the
  // button says when more than one lesson is involved, so nothing is hidden.
  final Map<String, Map<int, String>> _marks = {};
  final Map<String, Map<int, String>> _misc =
      {}; // cp -> (childId -> misconception)
  final Set<int> _absent = {};
  final Map<int, int> _rolls = {}; // childId -> roll number (for the register)
  String? _cp;
  int? _lastWrong; // child whose ✗ the misconception chips refer to
  Map<String, List<String>>? _miscByCp;
  bool _miscLoading = false;
  late Future<_TapData> _data;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _data = _load();
  }

  Future<_TapData> _load({bool refresh = false}) async {
    final res = await Future.wait<dynamic>([
      widget.roadmap(refresh: refresh),
      Api.i.roster(widget.classId),
    ]);
    final rm = (res[0] as Map).cast<String, dynamic>();
    final items = (rm['items'] as List)
        .cast<Map<String, dynamic>>()
        .where((i) => (i['checkpoint_id'] as String?)?.isNotEmpty == true)
        .toList();
    final pre = widget.presetCheckpointId;
    if (pre != null && !items.any((i) => i['checkpoint_id'] == pre)) {
      // a lesson from outside the roadmap (e.g. a prerequisite): still let it be checked
      try {
        final t = (await Api.i.checkpointTargets(pre) as Map)
            .cast<String, dynamic>();
        items.insert(0, {
          'checkpoint_id': pre,
          'chapter': '',
          'title_hi': t['title_hi'] ?? pre,
          'title_en': t['title_en'] ?? '',
        });
      } catch (_) {}
    }
    final roster = (res[1] as List).cast<Map<String, dynamic>>();
    for (final c in roster) {
      if (c['id'] is int && c['roll_no'] is int) {
        _rolls[c['id'] as int] = c['roll_no'] as int;
      }
    }
    return _TapData(items, roster);
  }

  String? _initialCp(List<Map<String, dynamic>> items) {
    final pre = widget.presetCheckpointId;
    if (pre != null && items.any((i) => i['checkpoint_id'] == pre)) return pre;
    return items.isEmpty ? null : items.first['checkpoint_id'] as String;
  }

  List<Map<String, dynamic>> _kids(List<Map<String, dynamic>> roster) {
    var kids = widget.preset ?? roster;
    final ids = widget.presetChildIds;
    if (ids != null && ids.isNotEmpty) {
      final f = kids.where((c) => ids.contains(c['id'])).toList();
      // a stale id list must not leave an empty grid
      if (f.isNotEmpty) kids = f;
    }
    return kids;
  }

  int get _markCount => _marks.values.fold(0, (n, m) => n + m.length);
  int get _count => _markCount + _absent.length;
  int get _lessonsWithMarks => _marks.values.where((m) => m.isNotEmpty).length;

  void _mark(int child, String r) {
    final cp = _cp;
    if (cp == null) return;
    setState(() {
      final m = _marks.putIfAbsent(cp, () => {});
      if (m[child] == r) {
        // tapping the chosen answer again undoes it
        m.remove(child);
        _misc[cp]?.remove(child);
        if (_lastWrong == child) _lastWrong = null;
        return;
      }
      m[child] = r;
      if (r == 'incorrect') {
        _lastWrong = child;
      } else {
        _misc[cp]?.remove(child);
        if (_lastWrong == child) _lastWrong = null;
      }
    });
    if (r == 'incorrect') _loadMisc();
  }

  void _toggleAbsent(int child) {
    setState(() {
      if (_absent.remove(child)) return;
      _absent.add(child);
      for (final m in _marks.values) {
        m.remove(child);
      }
      for (final m in _misc.values) {
        m.remove(child);
      }
      if (_lastWrong == child) _lastWrong = null;
    });
  }

  void _markRestCorrect(List<Map<String, dynamic>> kids) {
    final cp = _cp;
    if (cp == null) return;
    setState(() {
      final m = _marks.putIfAbsent(cp, () => {});
      for (final c in kids) {
        final id = c['id'] as int;
        if (_absent.contains(id)) continue;
        m.putIfAbsent(id, () => 'correct'); // keeps marks already made
      }
    });
  }

  /// Misconception tags for the chip row; fetched once, only after the first ✗.
  Future<void> _loadMisc() async {
    if (_miscByCp != null || _miscLoading) return;
    _miscLoading = true;
    try {
      final r = await Api.i.get(
        '/v1/content/checkpoints?subject=${widget.subject}',
      );
      final out = <String, List<String>>{};
      for (final c in (r as List)) {
        final l = ((c['misconceptions'] as List?) ?? const [])
            .map((e) => '$e')
            .toList();
        if (l.isNotEmpty) out[c['id'] as String] = l;
      }
      if (mounted) setState(() => _miscByCp = out);
    } catch (_) {
      // optional feature: no chips, no problem
    } finally {
      _miscLoading = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_TapData>(
      future: _data,
      builder: (context, snap) {
        if (snap.hasError) return _error(snap.error);
        if (!snap.hasData) return const Loading();
        final items = snap.data!.items;
        final kids = _kids(snap.data!.roster);
        _cp ??= _initialCp(items);
        if (items.isEmpty) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                tr(
                  'No lessons in this class\'s roadmap yet.',
                  'इस कक्षा की रोडमैप में अभी कोई सबक नहीं है।',
                ),
                textAlign: TextAlign.center,
                style: const TextStyle(color: Ks.muted),
              ),
            ),
          );
        }
        final unmarked = kids.any(
          (c) =>
              !_absent.contains(c['id']) &&
              _marks[_cp]?[c['id'] as int] == null,
        );
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
                  for (final it in items)
                    DropdownMenuItem(
                      value: it['checkpoint_id'] as String,
                      child: Text(
                        '${(it['chapter'] ?? '') == '' ? '' : '${it['chapter']} · '}${cpTitle(it)}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (v) => setState(() {
                  _cp = v;
                  _lastWrong = null;
                }),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 2, 8, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: unmarked ? () => _markRestCorrect(kids) : null,
                  style: TextButton.styleFrom(
                    minimumSize: const Size(48, 48),
                    textStyle: const TextStyle(fontSize: 14),
                  ),
                  icon: const Icon(Icons.done_all_rounded),
                  label: Text(
                    tr(
                      'Mark everyone correct, then fix exceptions',
                      'सबको सही करें, फिर अपवाद बदलें',
                    ),
                  ),
                ),
              ),
            ),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(12, 2, 12, 8),
                itemCount: kids.length,
                separatorBuilder: (_, _) => const SizedBox(height: 6),
                itemBuilder: (_, i) => _kidCard(kids[i]),
              ),
            ),
            _miscRow(kids),
            if (_lessonsWithMarks > 1)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                child: Text(
                  tr(
                    'Includes marks for $_lessonsWithMarks lessons',
                    '$_lessonsWithMarks सबक के निशान शामिल हैं',
                  ),
                  style: const TextStyle(fontSize: 14, color: Ks.muted),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 6, 16, 16),
              child: SizedBox(
                width: double.infinity,
                height: 52,
                child: FilledButton.icon(
                  onPressed: _count == 0 || _busy ? null : () => _save(),
                  icon: Icon(
                    _busy ? Icons.hourglass_top_rounded : Icons.save_rounded,
                  ),
                  label: Text(tr('Save ($_count)', 'सहेजें ($_count)')),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _error(Object? e) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off_rounded, size: 40, color: Ks.muted),
          const SizedBox(height: 10),
          Text(
            tr(
              'Could not load the lessons or the class list.',
              'सबक या कक्षा की सूची नहीं खुल सकी।',
            ),
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 16),
          ),
          const SizedBox(height: 4),
          Text(
            '$e',
            textAlign: TextAlign.center,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 14, color: Ks.muted),
          ),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: () => setState(() => _data = _load(refresh: true)),
            icon: const Icon(Icons.refresh_rounded),
            label: Text(tr('Retry', 'दोबारा कोशिश करें')),
          ),
        ],
      ),
    ),
  );

  Widget _kidCard(Map<String, dynamic> c) {
    final id = c['id'] as int;
    final absent = _absent.contains(id);
    final v = _marks[_cp]?[id];
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          children: [
            CircleAvatar(
              radius: 17,
              backgroundColor: Ks.accentSoft,
              child: Text(
                '${c['roll_no']}',
                style: const TextStyle(
                  color: Ks.accent,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '${c['first_name']}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 16,
                  color: absent ? Ks.muted : Ks.ink,
                ),
              ),
            ),
            if (absent)
              SizedBox(
                width: 162,
                child: Center(
                  child: Text(
                    tr('Absent today', 'आज अनुपस्थित'),
                    style: const TextStyle(fontSize: 14, color: Ks.rose),
                  ),
                ),
              )
            else
              _triple(v, (r) => _mark(id, r)),
            IconButton(
              tooltip: tr('Absent today', 'आज अनुपस्थित'),
              isSelected: absent,
              onPressed: () => _toggleAbsent(id),
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              icon: const Icon(Icons.person_off_outlined, color: Ks.muted),
              selectedIcon: const Icon(
                Icons.person_off_rounded,
                color: Ks.rose,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Optional "what went wrong" tags for the last child marked ✗.
  Widget _miscRow(List<Map<String, dynamic>> kids) {
    final id = _lastWrong;
    final cp = _cp;
    if (id == null || cp == null || _marks[cp]?[id] != 'incorrect') {
      return const SizedBox.shrink();
    }
    final opts = _miscByCp?[cp] ?? const <String>[];
    if (opts.isEmpty) return const SizedBox.shrink();
    final name = kids.firstWhere(
      (c) => c['id'] == id,
      orElse: () => {'first_name': ''},
    )['first_name'];
    final chosen = _misc[cp]?[id];
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr(
              'What went wrong for $name? (optional)',
              '$name को क्या दिक्कत हुई? (वैकल्पिक)',
            ),
            style: const TextStyle(fontSize: 14, color: Ks.muted),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final m in opts)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text(
                        m.replaceAll('_', ' '),
                        style: const TextStyle(fontSize: 14),
                      ),
                      selected: chosen == m,
                      onSelected: (sel) => setState(() {
                        final mm = _misc.putIfAbsent(cp, () => {});
                        if (sel) {
                          mm[id] = m;
                        } else {
                          mm.remove(id);
                        }
                      }),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _triple(String? v, ValueChanged<String> onTap) {
    Widget b(String val, IconData icon, Color color, String label) => Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 2),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => onTap(val),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 120),
            constraints: const BoxConstraints(minHeight: 52),
            alignment: Alignment.center,
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
                Icon(icon, color: v == val ? color : Ks.muted, size: 22),
                Text(
                  label,
                  maxLines: 1,
                  softWrap: false,
                  overflow: TextOverflow.visible,
                  style: TextStyle(
                    fontSize: 14,
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
      width: 162,
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
      final items = <Map<String, dynamic>>[];
      _marks.forEach((cp, m) {
        m.forEach((child, r) {
          final misc = _misc[cp]?[child];
          items.add({
            'child_id': child,
            'checkpoint_id': cp,
            'result': r,
            if (r == 'incorrect' && misc != null) 'misconception': misc,
          });
        });
      });
      final rolls = [
        for (final id in _absent)
          if (_rolls[id] != null) _rolls[id]!,
      ];
      var queued = false;
      if (items.isNotEmpty) {
        final r = await Api.i.postQueued(
          '/v1/classes/${widget.classId}/captures/tap',
          {'items': items},
        );
        queued = _wasQueued(r);
      }
      if (rolls.isNotEmpty) {
        try {
          // merge: only these children are marked absent, earlier absences today stay
          final r = await Api.i.postQueued(
            '/v1/classes/${widget.classId}/attendance?merge=true',
            {'absent_rolls': rolls},
          );
          if (_wasQueued(r)) queued = true;
        } catch (_) {
          if (items.isEmpty) rethrow; // nothing else was saved, so say so
        }
      }
      widget.onChanged();
      if (!mounted) return;
      setState(() {
        _marks.clear();
        _misc.clear();
        _absent.clear();
        _lastWrong = null;
      });
      _toast(queued ? _queuedMsg() : tr('Saved.', 'दर्ज हो गया।'));
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
}

// ------------------------------------------------------------------ NOTE
class _NotePanel extends StatefulWidget {
  const _NotePanel({
    required this.classId,
    required this.subject,
    required this.roadmap,
    required this.onChanged,
  });
  final int classId;
  final String subject;
  final _RoadmapLoader roadmap;
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
  int? _captureId; // proposed on the server and not yet confirmed
  final Map<int, String> _decisions = {}; // draft index -> result/absent/skip
  final Map<int, String?> _lessonOf =
      {}; // draft index -> lesson (checkpoint id)
  Map<String, Map<String, dynamic>> _lessons =
      {}; // id -> {title_hi,title_en,...}

  @override
  void initState() {
    super.initState();
    _text.addListener(_onText);
  }

  void _onText() {
    // enables/disables "Understand" as the teacher types
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _text.removeListener(_onText);
    _text.dispose();
    _rec.dispose();
    _rejectQuietly(_captureId); // closed or switched away without confirming
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
    _rejectQuietly(_captureId); // the previous result is being replaced
    _captureId = null;
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
        filename: 'note.wav',
      );
      final resp = (r as Map).cast<String, dynamic>();
      final lessons = await _lessonIndex(resp);
      if (!mounted) return;
      setState(() {
        _resp = resp;
        _lessons = lessons;
        _captureId = resp['capture_id'] is int
            ? resp['capture_id'] as int
            : null;
        _decisions.clear();
        _lessonOf.clear();
        final drafts = (resp['drafts'] as List?) ?? const [];
        for (var i = 0; i < drafts.length; i++) {
          final d = drafts[i] as Map<String, dynamic>;
          final cp = d['checkpoint_id'] as String?;
          _lessonOf[i] = cp;
          if (d['status'] == 'absent') {
            _decisions[i] = 'absent';
          } else if (cp != null && _validResult(d['result'])) {
            _decisions[i] = d['result'] as String;
          } else {
            // no lesson or no result: the teacher has to choose, or leave it skipped
            _decisions[i] = 'skip';
          }
        }
      });
    } catch (e) {
      _toast(e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Lesson id -> titles: roadmap order and English names from the roadmap (best effort),
  /// plus whatever the note response itself lists.
  Future<Map<String, Map<String, dynamic>>> _lessonIndex(
    Map<String, dynamic> resp,
  ) async {
    final out = <String, Map<String, dynamic>>{};
    try {
      final rm = (await widget.roadmap() as Map).cast<String, dynamic>();
      for (final it in (rm['items'] as List).cast<Map<String, dynamic>>()) {
        final id = it['checkpoint_id'];
        if (id is String && id.isNotEmpty) out[id] = it;
      }
    } catch (_) {}
    for (final c in ((resp['checkpoints'] as List?) ?? const [])) {
      final id = c['id'];
      if (id is String) {
        out.putIfAbsent(id, () => (c as Map).cast<String, dynamic>());
      }
    }
    return out;
  }

  String _lessonTitle(String? id) {
    if (id == null) return '';
    final m = _lessons[id];
    if (m == null) return id;
    final t = cpTitle(m);
    return t.isEmpty ? id : t;
  }

  Future<void> _confirm() async {
    final resp = _resp!;
    final drafts = (resp['drafts'] as List).cast<Map<String, dynamic>>();
    final accepted = <Map<String, dynamic>>[];
    final absentRolls = <int>[];
    var skipped = 0;
    var edited = 0;
    for (var i = 0; i < drafts.length; i++) {
      final d = drafts[i];
      final dec = _decisions[i] ?? 'skip';
      if (dec == 'absent') {
        // absences go to the register, not the evidence ledger (which only takes results)
        final roll = d['roll_no'];
        if (roll is int && !absentRolls.contains(roll)) absentRolls.add(roll);
        continue;
      }
      final cp = _lessonOf[i];
      if (dec == 'skip' || cp == null) {
        skipped++;
        continue;
      }
      if (cp != d['checkpoint_id'] || dec != d['result']) edited++;
      accepted.add({
        'child_id': d['child_id'],
        'checkpoint_id': cp,
        'result': dec,
        'confidence': d['confidence'] ?? 0.7,
        'quote': d['quote'],
        if (d['misconception'] != null) 'misconception': d['misconception'],
      });
    }
    setState(() => _busy = true);
    try {
      final r = await Api.i.postQueued(
        '/v1/captures/${resp['capture_id']}/confirm',
        {'accepted': accepted, 'skipped': skipped, 'edited': edited},
      );
      _captureId = null; // handled: do not reject it on the way out
      if (absentRolls.isNotEmpty) {
        try {
          // merge so earlier absences today are kept; best-effort, never blocks the evidence
          await Api.i.setAttendance(widget.classId, absentRolls, merge: true);
        } catch (_) {}
      }
      widget.onChanged();
      if (!mounted) return;
      if (_wasQueued(r)) _toast(_queuedMsg());
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
        SizedBox(
          height: 48,
          child: OutlinedButton.icon(
            onPressed: _busy || _text.text.trim().isEmpty
                ? null
                : () => _send(),
            icon: const Icon(Icons.send_rounded),
            label: Text(
              _busy
                  ? tr('Understanding…', 'समझ रहे हैं…')
                  : tr('Understand', 'समझें'),
            ),
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
    final heard = (resp['transcript'] as String?)?.trim() ?? '';
    return [
      const SizedBox(height: 16),
      if (heard.isNotEmpty) ...[
        Text(
          tr('What I heard', 'मैंने यह सुना'),
          style: const TextStyle(fontSize: 14, color: Ks.muted),
        ),
        const SizedBox(height: 4),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Ks.accentSoft,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(heard, style: const TextStyle(fontSize: 15)),
        ),
        const SizedBox(height: 14),
      ],
      Text(
        tr('AI understood this — please check', 'AI ने यह समझा — जाँचें'),
        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17),
      ),
      if (fallback && resp['note'] != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            resp['note'],
            style: const TextStyle(fontSize: 14, color: Ks.muted),
          ),
        ),
      const SizedBox(height: 10),
      if (drafts.isEmpty)
        Text(
          tr(
            'Nothing could be matched to a child. Try again, or use the Tap tab.',
            'किसी बच्चे से कुछ नहीं जुड़ सका। दोबारा कोशिश करें या टैप टैब देखें।',
          ),
          style: const TextStyle(color: Ks.muted),
        ),
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
      SizedBox(
        height: 52,
        child: FilledButton.icon(
          onPressed: _busy ? null : _confirm,
          icon: const Icon(Icons.check_rounded),
          label: Text(tr('Confirm', 'पुष्टि करें')),
        ),
      ),
    ];
  }

  Widget _lessonPicker(int i, Map<String, dynamic> d) {
    final cp = _lessonOf[i];
    final ids = _lessons.keys.toList();
    if (cp != null && !ids.contains(cp)) ids.insert(0, cp);
    return DropdownButton<String>(
      value: cp,
      isExpanded: true,
      isDense: false,
      underline: Container(height: 1, color: Ks.line),
      hint: Text(
        tr('Pick a lesson', 'सबक चुनें'),
        style: const TextStyle(fontSize: 14, color: Ks.amber),
      ),
      style: const TextStyle(fontSize: 14, color: Ks.ink),
      items: [
        for (final id in ids)
          DropdownMenuItem(
            value: id,
            child: Text(_lessonTitle(id), overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: (v) => setState(() {
        _lessonOf[i] = v;
        // a draft that had no lesson starts skipped; picking one turns it on
        if (d['checkpoint_id'] == null &&
            _decisions[i] == 'skip' &&
            _validResult(d['result'])) {
          _decisions[i] = d['result'] as String;
        }
      }),
    );
  }

  Widget _draftTile(int i, Map<String, dynamic> d) {
    final isAbsent = d['status'] == 'absent';
    final dec = _decisions[i] ?? 'skip';
    final noLesson = !isAbsent && _lessonOf[i] == null;
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
                    style: const TextStyle(fontSize: 12, color: Ks.accent),
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
                    fontSize: 14,
                  ),
                ),
              ),
            if (!isAbsent) ...[
              const SizedBox(height: 6),
              Text(
                tr('Lesson', 'सबक'),
                style: const TextStyle(fontSize: 12, color: Ks.muted),
              ),
              _lessonPicker(i, d),
              if (noLesson)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    tr(
                      'No lesson matched. Pick one to save this, or skip it.',
                      'कोई सबक नहीं मिला। सहेजने के लिए चुनें, या छोड़ दें।',
                    ),
                    style: const TextStyle(fontSize: 14, color: Ks.amber),
                  ),
                ),
            ],
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Wrap(
                spacing: 6,
                children: [
                  for (final opt
                      in isAbsent
                          ? const ['absent', 'skip']
                          : const ['correct', 'partial', 'incorrect', 'skip'])
                    ChoiceChip(
                      label: Text(
                        opt == 'absent'
                            ? tr('Absent', 'अनुपस्थित')
                            : _resultLabel(opt),
                        style: const TextStyle(fontSize: 14),
                      ),
                      selected: dec == opt,
                      onSelected: (_) => setState(() => _decisions[i] = opt),
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
  int? _captureId; // proposed on the server and not yet confirmed
  // question index -> correct|partial|incorrect|skip. A missing entry means the model
  // was unclear and the teacher has not chosen yet.
  final Map<int, String> _verdicts = {};

  @override
  void initState() {
    super.initState();
    _roster = Api.i.roster(widget.classId);
  }

  @override
  void dispose() {
    _rejectQuietly(_captureId); // closed or switched away without confirming
    super.dispose();
  }

  Future<void> _pick(ImageSource source) async {
    if (_childId == null) {
      _toast(tr('Choose a child first', 'पहले बच्चा चुनें'));
      return;
    }
    try {
      final picker = ImagePicker();
      final file = await picker.pickImage(
        source: source,
        maxWidth: 1600,
        imageQuality: 82,
      );
      if (file == null) return;
      final bytes = await file.readAsBytes();
      _rejectQuietly(_captureId); // the previous result is being replaced
      _captureId = null;
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
        // "unclear" is not "correct": leave it unset so the teacher must decide
        if (v == 'correct' || v == 'incorrect') _verdicts[i] = v!;
      }
      _captureId = map['capture_id'] is int ? map['capture_id'] as int : null;
      setState(() => _result = map);
    } on ApiError catch (e) {
      if (mounted) setState(() => _message = e.message);
    } catch (e) {
      if (mounted) {
        setState(
          () => _message = tr(
            'Could not open the photo: $e',
            'फ़ोटो नहीं खुल सकी: $e',
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final res = _result!;
    final qs = (res['questions'] as List).cast<Map<String, dynamic>>();
    final needLook = <int>[
      for (var i = 0; i < qs.length; i++)
        if (qs[i]['checkpoint_id'] != null && _verdicts[i] == null) i,
    ];
    if (needLook.isNotEmpty) {
      _toast(
        tr(
          '${needLook.length} answer(s) need a look — choose Correct, Partly, Wrong or Skip.',
          '${needLook.length} जवाब देखने हैं — सही, थोड़ा, गलत या छोड़ें चुनें।',
        ),
      );
      return;
    }
    final accepted = <Map<String, dynamic>>[];
    final perCp = <String, List<double>>{}; // cp -> [points, total]
    var skipped = 0;
    var edited = 0;
    for (var i = 0; i < qs.length; i++) {
      final cp = qs[i]['checkpoint_id'] as String?;
      final v = _verdicts[i];
      if (cp == null || v == null || v == 'skip') {
        skipped++;
        continue;
      }
      final orig = qs[i]['verdict'];
      if ((orig == 'correct' || orig == 'incorrect') && orig != v) edited++;
      final bucket = perCp.putIfAbsent(cp, () => [0.0, 0.0]);
      // a partly-right answer is half a point, so it never rounds down to "wrong"
      bucket[0] += v == 'correct' ? 1 : (v == 'partial' ? 0.5 : 0);
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
          'Nothing to save. Choose answers, or check with taps.',
          'सहेजने को कुछ नहीं। जवाब चुनें, या टैप से जाँचें।',
        ),
      );
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await Api.i.postQueued(
        '/v1/captures/${res['capture_id']}/confirm',
        {'accepted': accepted, 'skipped': skipped, 'edited': edited},
      );
      _captureId = null; // handled: do not reject it on the way out
      widget.onChanged();
      if (!mounted) return;
      if (_wasQueued(r)) _toast(_queuedMsg());
      Navigator.of(context).pop(true);
    } on ApiError catch (e) {
      _toast(e.message);
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
            SizedBox(
              height: 52,
              child: FilledButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.camera),
                icon: const Icon(Icons.photo_camera_rounded),
                label: Text(
                  _busy
                      ? tr('Reading…', 'पढ़ा जा रहा है…')
                      : tr('Take photo and read', 'फ़ोटो लें और पढ़ें'),
                ),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: 48,
              child: OutlinedButton.icon(
                onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                icon: const Icon(Icons.photo_library_rounded),
                label: Text(tr('Choose from gallery', 'गैलरी से चुनें')),
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
            style: const TextStyle(fontSize: 14, color: Ks.muted),
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
        SizedBox(
          height: 52,
          child: FilledButton.icon(
            onPressed: _busy ? null : _confirm,
            icon: const Icon(Icons.check_rounded),
            label: Text(tr('Confirm', 'पुष्टि करें')),
          ),
        ),
      ],
    ];
  }

  Widget _qTile(int i, Map<String, dynamic> q) {
    final v = _verdicts[i];
    final linked = (q['checkpoint_id'] as String?) != null;
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
                    child: const Padding(
                      padding: EdgeInsets.all(8),
                      child: Icon(
                        Icons.calculate_rounded,
                        size: 18,
                        color: Ks.muted,
                      ),
                    ),
                  ),
              ],
            ),
            if (!linked)
              Padding(
                padding: EdgeInsets.only(top: 2),
                child: Text(
                  tr(
                    'Not linked to a lesson, so it will not be saved',
                    'किसी सबक से नहीं जुड़ा, इसलिए सहेजा नहीं जाएगा',
                  ),
                  style: TextStyle(fontSize: 14, color: Ks.muted),
                ),
              ),
            if (q['override_note'] == 'arithmetic')
              Padding(
                padding: EdgeInsets.only(top: 2),
                child: Text(
                  tr('Corrected by calculation', 'गणना से सुधारा गया'),
                  style: TextStyle(fontSize: 14, color: Ks.accent),
                ),
              ),
            if (linked && v == null)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  tr(
                    'Needs a look — the answer was not clear. Choose one, or skip.',
                    'देखना होगा — जवाब साफ़ नहीं था। एक चुनें, या छोड़ें।',
                  ),
                  style: const TextStyle(fontSize: 14, color: Ks.amber),
                ),
              ),
            if (linked) ...[
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                children: [
                  for (final opt in const [..._kResults, 'skip'])
                    ChoiceChip(
                      label: Text(
                        _resultLabel(opt),
                        style: const TextStyle(fontSize: 14),
                      ),
                      selected: v == opt,
                      onSelected: (sel) => setState(() => _verdicts[i] = opt),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
