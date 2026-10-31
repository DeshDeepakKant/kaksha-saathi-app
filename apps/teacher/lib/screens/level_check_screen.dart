import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../subjects.dart';
import '../outbox.dart';
import '../theme.dart';

/// First-week / end-of-term level check (ASER/TaRL style, `content/level_check.json`).
/// The class summary (first vs latest level) and the children list; tap a child to run the
/// check: one level at a time, big items to show the child, right/wrong per item, stop at the
/// first level not passed, then save. The server decides nothing here but the stored level.
class LevelCheckScreen extends StatefulWidget {
  const LevelCheckScreen({
    super.key,
    required this.classId,
    required this.subject,
  });
  final int classId;
  final String subject;
  @override
  State<LevelCheckScreen> createState() => _LevelCheckScreenState();
}

List<Map<String, dynamic>> _maps(dynamic v) => v is List
    ? v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

int _int(dynamic v, [int fallback = 0]) => v is num ? v.toInt() : fallback;

class _LevelCheckScreenState extends State<LevelCheckScreen> {
  // Only the built-in subjects have a ladder; anything else starts on Maths.
  late String _subject = builtinSubjectKeys.contains(widget.subject)
      ? widget.subject
      : 'numeracy';
  late Future<Map<String, dynamic>> _future;
  Map<String, dynamic>? _data; // last good response: ladder + children

  // ---- the check in progress (_child == null means the class list is shown)
  Map<String, dynamic>? _child;
  int _level = 0;
  List<bool?> _marks =
      const []; // per item of the current level: right / wrong / not yet
  final List<Map<String, dynamic>> _results = [];
  bool _finished = false; // ladder over, waiting for Save
  String?
  _uuid; // one per finished check, so a retried Save is not stored twice
  bool _saving = false;
  String? _saveError;
  Map<String, dynamic>? _placed; // after Save: the stored level
  bool _queued = false;
  final Set<int> _doneIds = {}; // children checked in this sitting

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  Future<Map<String, dynamic>> _fetch() async {
    final r = await Api.i.get(
      '/v1/classes/${widget.classId}/level_check?subject=$_subject',
    );
    final m = (r as Map).cast<String, dynamic>();
    _data = m;
    return m;
  }

  Future<void> _reload() async {
    final f = _fetch();
    setState(() {
      _future = f;
    });
    try {
      await f;
    } catch (_) {}
  }

  void _switchSubject(String s) {
    if (s == _subject) return;
    setState(() {
      _subject = s;
      _data = null;
      _doneIds.clear();
      _future = _fetch();
    });
  }

  /// Old server: a new route answers FastAPI's bare 404.
  String _errText(Object? e) {
    if (e is ApiError && e.status == 404 && e.message == 'Not Found') {
      return tr(
        'This needs the latest server. Ask to update the server.',
        'इसके लिए नया सर्वर चाहिए। सर्वर अपडेट करवाएँ।',
      );
    }
    return e is ApiError
        ? e.message
        : tr(
            'Could not load the level check. Check the network.',
            'स्तर जाँच नहीं खुल सकी। नेटवर्क देखें।',
          );
  }

  List<Map<String, dynamic>> get _levels => _maps(_data?['levels']);

  /// Title of a ladder position; -1 is the beginner level.
  String _titleAt(int index) {
    final levels = _levels;
    if (index >= 0 && index < levels.length) {
      return pick(levels[index], 'title');
    }
    final b = _data?['beginner'];
    return b is Map ? pick(b, 'title') : tr('Beginner', 'शुरुआत');
  }

  String _titleForKey(String key) {
    final i = _levels.indexWhere((l) => l['key'] == key);
    return i >= 0 ? _titleAt(i) : (key == 'beginner' ? _titleAt(-1) : key);
  }

  String _subjectLabel(String s) => subjectLabel(s);

  // ---- running a check

  void _start(Map<String, dynamic> child) {
    final levels = _levels;
    if (levels.isEmpty) return;
    setState(() {
      _child = child;
      _level = 0;
      _marks = List<bool?>.filled(_maps(levels[0]['items']).length, null);
      _results.clear();
      _finished = false;
      _uuid = null;
      _saving = false;
      _saveError = null;
      _placed = null;
      _queued = false;
    });
  }

  void _toList() {
    setState(() => _child = null);
    _reload(); // summary and latest levels changed if anything was saved
  }

  /// Back during an unsaved check asks first; after Save it simply returns to the list.
  Future<void> _leaveCheck() async {
    final started = _results.isNotEmpty || _marks.any((m) => m != null);
    if (_placed == null && started) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(tr('Stop this check?', 'यह जाँच रोकें?')),
          content: Text(
            tr(
              'Nothing from this check has been saved yet.',
              'इस जाँच का कुछ भी अभी सहेजा नहीं गया है।',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(tr('Keep checking', 'जाँच जारी रखें')),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              style: TextButton.styleFrom(foregroundColor: Ks.rose),
              child: Text(tr('Stop', 'रोकें')),
            ),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    _toList();
  }

  int get _right => _marks.where((m) => m == true).length;
  int get _wrong => _marks.where((m) => m == false).length;

  /// The level is decided as soon as the result can no longer change.
  bool _decided(int passMin) =>
      _right >= passMin || _wrong > _marks.length - passMin;

  void _finishLevel() {
    final levels = _levels;
    final lv = levels[_level];
    final passed = _right >= _int(lv['pass_min'], _marks.length);
    setState(() {
      _results.add({'level_key': lv['key'], 'passed': passed});
      if (passed && _level + 1 < levels.length) {
        _level++;
        _marks = List<bool?>.filled(
          _maps(levels[_level]['items']).length,
          null,
        );
      } else {
        _finished = true;
        _uuid = newClientUuid();
      }
    });
  }

  /// Last passed ladder index, or -1 (beginner).
  int get _placedIndex {
    var idx = -1;
    for (var i = 0; i < _results.length; i++) {
      if (_results[i]['passed'] == true) idx = i;
    }
    return idx;
  }

  Future<void> _save() async {
    final child = _child!;
    setState(() {
      _saving = true;
      _saveError = null;
    });
    try {
      final r = await Api.i.postQueued(
        '/v1/classes/${widget.classId}/level_check',
        {
          'subject': _subject,
          'child_id': _int(child['child_id']),
          'results': _results,
          'client_uuid': _uuid,
        },
      );
      if (!mounted) return;
      final queued = r is Map && r['queued'] == true;
      setState(() {
        _saving = false;
        _queued = queued;
        _placed = !queued && r is Map
            ? r.cast<String, dynamic>()
            : {'level_index': _placedIndex};
        _doneIds.add(_int(child['child_id']));
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = _errText(e);
      });
    }
  }

  /// Next child after the current one, preferring children with no check yet.
  Map<String, dynamic>? _nextChild() {
    final kids = _maps(_data?['children']);
    final cur = kids.indexWhere((c) => c['child_id'] == _child?['child_id']);
    final after = kids.sublist(cur + 1);
    bool open(Map<String, dynamic> c) =>
        !_doneIds.contains(_int(c['child_id']));
    for (final c in after) {
      if (open(c) && c['latest'] == null) return c;
    }
    for (final c in after) {
      if (open(c)) return c;
    }
    return null;
  }

  // ---- build

  @override
  Widget build(BuildContext context) {
    final child = _child;
    return PopScope(
      canPop: child == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leaveCheck();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            child == null
                ? tr('Level check', 'स्तर जाँच')
                : '${child['first_name']} · ${_subjectLabel(_subject)}',
          ),
        ),
        body: child == null
            ? _classView()
            : _placed != null
            ? _savedView(child)
            : _finished
            ? _confirmView(child)
            : _levelView(child),
      ),
    );
  }

  // ---- class list

  Widget _classView() {
    return FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return Column(
            children: [
              _subjectToggle(),
              const Expanded(child: Loading()),
            ],
          );
        }
        if (snap.hasError || snap.data == null) {
          return Column(
            children: [
              _subjectToggle(),
              Expanded(child: _errorView(snap.error)),
            ],
          );
        }
        final d = snap.data!;
        final kids = _maps(d['children']);
        return RefreshIndicator(
          color: Ks.accent,
          onRefresh: _reload,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
            children: [
              _subjectToggle(),
              if (d['offline'] == true)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Text(
                    tr(
                      'Offline: showing the last saved copy',
                      'ऑफ़लाइन: पिछली सहेजी हुई जानकारी दिख रही है',
                    ),
                    style: const TextStyle(color: Ks.amber),
                  ),
                ),
              _summaryCard(d),
              const SizedBox(height: 10),
              Text(
                tr(
                  'Sit with one child. Start at the first level and move up; the check stops at the first level the child does not pass.',
                  'एक बच्चे के साथ बैठें। पहले स्तर से शुरू करके आगे बढ़ें; जिस स्तर पर बच्चा पास न हो, वहीं जाँच रुक जाती है।',
                ),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
              const SizedBox(height: 14),
              SectionTitle(
                tr('Tap a child to check', 'जाँच के लिए बच्चे पर टैप करें'),
              ),
              if (kids.isEmpty)
                EmptyState(
                  icon: Icons.person_outline_rounded,
                  text: tr(
                    'No students in this class yet.',
                    'इस कक्षा में अभी कोई बच्चा नहीं।',
                  ),
                ),
              for (final c in kids) ...[
                _childTile(c),
                const SizedBox(height: 8),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _subjectToggle() => Padding(
    padding: const EdgeInsets.fromLTRB(0, 10, 0, 12),
    child: SegmentedButton<String>(
      showSelectedIcon: false,
      segments: [
        for (final k in builtinSubjectKeys)
          ButtonSegment(value: k, label: Text(_subjectLabel(k))),
      ],
      selected: {_subject},
      onSelectionChanged: (s) => _switchSubject(s.first),
    ),
  );

  Widget _errorView(Object? err) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off_rounded, size: 48, color: Ks.muted),
          const SizedBox(height: 12),
          Text(
            _errText(err),
            textAlign: TextAlign.center,
            style: const TextStyle(color: Ks.muted, fontSize: 16),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _reload,
            style: FilledButton.styleFrom(minimumSize: const Size(180, 52)),
            icon: const Icon(Icons.refresh_rounded),
            label: Text(tr('Retry', 'दोबारा कोशिश करें')),
          ),
        ],
      ),
    ),
  );

  /// Per level: how many children started there → how many are there now.
  Widget _summaryCard(Map<String, dynamic> d) {
    final s = d['summary'] is Map ? (d['summary'] as Map) : const {};
    final first = s['first'] is Map ? s['first'] as Map : const {};
    final latest = s['latest'] is Map ? s['latest'] as Map : const {};
    final checked = _int(s['checked']);
    final total = _int(s['total']);
    final moved = _int(s['moved_up']);
    final keys = ['beginner', for (final l in _levels) '${l['key']}'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              pick(d, 'title'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              trf(
                '{checked} of {total} children checked · {moved} moved up',
                '{total} में से {checked} बच्चे जाँचे गए · {moved} आगे बढ़े', {'checked': checked, 'total': total, 'moved': moved},
              ),
              style: const TextStyle(color: Ks.muted, fontSize: 14),
            ),
            if (checked > 0) ...[
              const SizedBox(height: 10),
              Row(
                children: [
                  const Expanded(child: SizedBox()),
                  SizedBox(
                    width: 112,
                    child: Text(
                      tr('first → latest', 'पहली → अभी'),
                      textAlign: TextAlign.end,
                      style: const TextStyle(color: Ks.muted, fontSize: 13),
                    ),
                  ),
                ],
              ),
              for (final k in keys)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          _titleForKey(k),
                          style: const TextStyle(fontSize: 15, color: Ks.ink),
                        ),
                      ),
                      SizedBox(
                        width: 112,
                        child: Text(
                          '${_int(first[k])} → ${_int(latest[k])}',
                          textAlign: TextAlign.end,
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: Ks.ink,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _childTile(Map<String, dynamic> c) {
    final first = c['first'] is Map ? c['first'] as Map : null;
    final latest = c['latest'] is Map ? c['latest'] as Map : null;
    final done = _doneIds.contains(_int(c['child_id']));
    String sub;
    if (latest == null) {
      sub = done
          ? tr('Checked just now', 'अभी जाँचा गया')
          : tr('Not checked yet', 'अभी जाँच नहीं हुई');
    } else {
      final a = _int(first?['level_index'], -1);
      final b = _int(latest['level_index'], -1);
      sub = a == b ? _titleAt(b) : '${_titleAt(a)} → ${_titleAt(b)}';
    }
    final up =
        latest != null &&
        _int(latest['level_index'], -1) > _int(first?['level_index'], -1);
    return Card(
      child: ListTile(
        minVerticalPadding: 12,
        onTap: () => _start(c),
        leading: CircleAvatar(
          backgroundColor: Ks.accentSoft,
          foregroundColor: Ks.accent,
          child: Text(
            '${c['roll_no']}',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        title: Text(
          '${c['first_name']}',
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
        subtitle: Row(
          children: [
            if (up)
              const Padding(
                padding: EdgeInsetsDirectional.only(end: 4),
                child: Icon(
                  Icons.trending_up_rounded,
                  size: 16,
                  color: Ks.green,
                ),
              ),
            Flexible(
              child: Text(
                sub,
                style: TextStyle(color: latest == null ? Ks.muted : Ks.ink),
              ),
            ),
          ],
        ),
        trailing: Icon(
          done ? Icons.check_circle_rounded : Icons.chevron_right_rounded,
          color: done ? Ks.green : Ks.muted,
        ),
      ),
    );
  }

  // ---- one level

  /// Short items (a letter, a number) are huge; a sentence still fits on a phone.
  double _itemSize(String s) => s.length <= 2
      ? 88
      : s.length <= 6
      ? 64
      : s.length <= 14
      ? 42
      : 30;

  Widget _levelView(Map<String, dynamic> child) {
    final levels = _levels;
    final lv = levels[_level];
    final items = _maps(lv['items']);
    final passMin = _int(lv['pass_min'], items.length);
    final decided = _decided(passMin);
    final passed = _right >= passMin;
    final last = _level + 1 >= levels.length;
    return Column(
      children: [
        LinearProgressIndicator(
          value: (_level + 1) / levels.length,
          minHeight: 4,
          color: Ks.accent,
          backgroundColor: Ks.accentSoft,
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            children: [
              Text(
                trf(
                  'Level {level} of {levelsCount} · {pick}',
                  'स्तर {level} / {levelsCount} · {pick}', {'level': _level + 1, 'levelsCount': levels.length, 'pick': pick(lv, 'title')},
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Ks.accentSoft,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.record_voice_over_rounded,
                      color: Ks.accent,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        pick(lv, 'ask'),
                        style: const TextStyle(fontSize: 16, color: Ks.ink),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              for (var i = 0; i < items.length; i++) ...[
                _itemCard(i, items[i]),
                const SizedBox(height: 10),
              ],
            ],
          ),
        ),
        // Footer: the tally and the one button that moves on.
        Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
          decoration: const BoxDecoration(
            color: Ks.card,
            border: Border(top: BorderSide(color: Ks.line)),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  trf(
                    '{right} right of {itemsCount} · {passMin} needed to pass',
                    '{itemsCount} में से {right} सही · पास के लिए {passMin} चाहिए', {'right': _right, 'itemsCount': items.length, 'passMin': passMin},
                  ),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Ks.muted, fontSize: 14),
                ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(56),
                    backgroundColor: !decided || passed ? Ks.accent : Ks.amber,
                  ),
                  onPressed: decided ? _finishLevel : null,
                  icon: Icon(
                    !decided
                        ? Icons.touch_app_rounded
                        : passed
                        ? Icons.arrow_upward_rounded
                        : Icons.flag_rounded,
                  ),
                  label: Text(
                    !decided
                        ? tr('Mark the items', 'हर सवाल पर निशान लगाएँ')
                        : passed && !last
                        ? tr('Passed · next level', 'पास · अगला स्तर')
                        : passed
                        ? tr('Passed · finish', 'पास · पूरा करें')
                        : tr('Not passed · finish', 'पास नहीं · पूरा करें'),
                    style: const TextStyle(fontSize: 17),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _itemCard(int i, Map<String, dynamic> item) {
    final show = '${item['show'] ?? ''}';
    final expect = item['expect'];
    final mark = i < _marks.length ? _marks[i] : null;
    void set(bool v) => setState(() => _marks[i] = mark == v ? null : v);
    return Card(
      color: mark == null ? Ks.card : (mark ? Ks.greenSoft : Ks.roseSoft),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 16, 14, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Classroom content stays as written (Hindi words, numerals).
            Text(
              show,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: _itemSize(show),
                fontWeight: FontWeight.w700,
                color: Ks.ink,
                height: 1.25,
              ),
            ),
            if (expect != null && '$expect'.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  trf('Answer: {expect}', 'उत्तर: {expect}', {'expect': expect}),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Ks.muted, fontSize: 14),
                ),
              ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _markButton(
                    selected: mark == false,
                    color: Ks.rose,
                    icon: Icons.close_rounded,
                    label: tr('Wrong', 'गलत'),
                    onTap: () => set(false),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _markButton(
                    selected: mark == true,
                    color: Ks.green,
                    icon: Icons.check_rounded,
                    label: tr('Right', 'सही'),
                    onTap: () => set(true),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _markButton({
    required bool selected,
    required Color color,
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    final style = selected
        ? FilledButton.styleFrom(
            backgroundColor: color,
            minimumSize: const Size.fromHeight(52),
          )
        : OutlinedButton.styleFrom(
            foregroundColor: color,
            side: BorderSide(color: color),
            minimumSize: const Size.fromHeight(52),
          );
    return selected
        ? FilledButton.icon(
            style: style,
            onPressed: onTap,
            icon: Icon(icon),
            label: Text(label, style: const TextStyle(fontSize: 16)),
          )
        : OutlinedButton.icon(
            style: style,
            onPressed: onTap,
            icon: Icon(icon),
            label: Text(label, style: const TextStyle(fontSize: 16)),
          );
  }

  // ---- confirm and save

  Widget _placedCard(String label, String title) => Card(
    color: Ks.accentSoft,
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          Text(label, style: const TextStyle(color: Ks.accent, fontSize: 15)),
          const SizedBox(height: 6),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w800,
              color: Ks.accent,
            ),
          ),
        ],
      ),
    ),
  );

  Widget _confirmView(Map<String, dynamic> child) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
      children: [
        _placedCard(
          trf('{first_name} is at', '{first_name} का स्तर', {'first_name': child['first_name']}),
          _titleAt(_placedIndex),
        ),
        const SizedBox(height: 12),
        for (var i = 0; i < _results.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              children: [
                Icon(
                  _results[i]['passed'] == true
                      ? Icons.check_circle_rounded
                      : Icons.cancel_rounded,
                  color: _results[i]['passed'] == true ? Ks.green : Ks.rose,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    _titleAt(i),
                    style: const TextStyle(fontSize: 16, color: Ks.ink),
                  ),
                ),
                Text(
                  _results[i]['passed'] == true
                      ? tr('Passed', 'पास')
                      : tr('Not passed', 'पास नहीं'),
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: _results[i]['passed'] == true ? Ks.green : Ks.rose,
                  ),
                ),
              ],
            ),
          ),
        if (_saveError != null)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(_saveError!, style: const TextStyle(color: Ks.rose)),
          ),
        const SizedBox(height: 16),
        FilledButton.icon(
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(56)),
          onPressed: _saving ? null : _save,
          icon: const Icon(Icons.save_rounded),
          label: Text(
            _saving ? tr('Saving…', 'सहेज रहे हैं…') : tr('Save', 'सहेजें'),
            style: const TextStyle(fontSize: 17),
          ),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
          ),
          onPressed: _saving ? null : () => _start(child),
          icon: const Icon(Icons.replay_rounded),
          label: Text(tr('Start again', 'फिर से शुरू करें')),
        ),
      ],
    );
  }

  Widget _savedView(Map<String, dynamic> child) {
    final p = _placed!;
    final title = pick(p, 'title').isNotEmpty
        ? pick(p, 'title')
        : _titleAt(_int(p['level_index'], _placedIndex));
    final next = _nextChild();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 24, 16, 32),
      children: [
        Icon(
          _queued ? Icons.cloud_upload_rounded : Icons.check_circle_rounded,
          size: 56,
          color: _queued ? Ks.amber : Ks.green,
        ),
        const SizedBox(height: 8),
        Text(
          _queued
              ? tr(
                  'No internet. Saved on this phone and will send later.',
                  'इंटरनेट नहीं है। फ़ोन में रखा है, बाद में भेजा जाएगा।',
                )
              : tr('Saved.', 'सहेज लिया।'),
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 16, color: Ks.ink),
        ),
        const SizedBox(height: 16),
        _placedCard(
          trf('{first_name} is at', '{first_name} का स्तर', {'first_name': child['first_name']}),
          title,
        ),
        const SizedBox(height: 20),
        if (next != null)
          FilledButton.icon(
            style: FilledButton.styleFrom(
              minimumSize: const Size.fromHeight(56),
            ),
            onPressed: () => _start(next),
            icon: const Icon(Icons.arrow_forward_rounded),
            label: Text(
              trf(
                'Next child: {first_name}',
                'अगला बच्चा: {first_name}', {'first_name': next['first_name']},
              ),
              style: const TextStyle(fontSize: 17),
            ),
          ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size.fromHeight(52),
          ),
          onPressed: _toList,
          icon: const Icon(Icons.list_rounded),
          label: Text(tr('Back to the class list', 'कक्षा की सूची पर लौटें')),
        ),
      ],
    );
  }
}
