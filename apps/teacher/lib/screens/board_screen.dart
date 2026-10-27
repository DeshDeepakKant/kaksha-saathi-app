import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets/board_absent.dart';
import '../widgets/board_chips.dart';
import '../widgets/board_moved_banner.dart';
import '../widgets/capture_sheet.dart';
import 'class_picker_screen.dart';
import 'login_screen.dart';
import 'group_plan_screen.dart';
import 'level_screen.dart';
import 'settings_screen.dart';
import 'syllabus_screen.dart';
import '../l10n.dart';

/// Class + subject selection, then the "classroom board": today's groups, on-track, unassessed.
class BoardScreen extends StatefulWidget {
  const BoardScreen({super.key, this.initialClass});
  final Map<String, dynamic>? initialClass;
  @override
  State<BoardScreen> createState() => _BoardScreenState();
}

/// Built-in subjects, used until (or instead of) the server's list.
const _builtinSubjects = <Map<String, dynamic>>[
  {'key': 'numeracy', 'builtin': true},
  {'key': 'literacy', 'builtin': true},
];

List<Map<String, dynamic>> _maps(dynamic v) => v is List
    ? v.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

class _BoardScreenState extends State<BoardScreen> {
  Map<String, dynamic>? _cls;
  String _subject = 'numeracy';
  List<Map<String, dynamic>> _subjects = _builtinSubjects;
  Map<String, dynamic>? _board;
  bool _loading = true;
  bool _waking =
      false; // loading has taken long enough that the server is probably asleep
  String? _error;
  bool _offline = false;
  List<Map<String, dynamic>> _moves = [];
  bool _movedDismissed = false;
  Map<int, String> _rosterNames =
      {}; // fallback names for absent children not on the board
  int? _rosterFor;
  Timer? _wakeTimer;
  int _seq = 0; // only the newest load may touch state
  int _lastPending = 0;

  @override
  void initState() {
    super.initState();
    _cls = widget.initialClass;
    _lastPending = Api.i.pendingCount.value;
    Api.i.pendingCount.addListener(_onPending);
    _init();
  }

  @override
  void dispose() {
    Api.i.pendingCount.removeListener(_onPending);
    _wakeTimer?.cancel();
    super.dispose();
  }

  /// Once the outbox drains, what was parked is on the server: refresh the board.
  void _onPending() {
    final n = Api.i.pendingCount.value;
    final was = _lastPending;
    _lastPending = n;
    if (was > 0 && n == 0 && mounted && _cls != null) {
      _loadBoard(showSpinner: false, freshMoves: true);
    }
  }

  void _startWake() {
    if (_wakeTimer?.isActive ?? false) return;
    _wakeTimer = Timer(const Duration(seconds: 8), () {
      if (mounted && _loading) setState(() => _waking = true);
    });
  }

  void _stopWake() {
    _wakeTimer?.cancel();
    _wakeTimer = null;
    _waking = false;
  }

  /// A server answer in the 4xx range is shown as is; anything else (no network, timeout, a
  /// sleeping or restarting server) is a connection problem, never "Class not found".
  String _friendly(Object e) {
    if (e is ApiError && e.status >= 400 && e.status < 500) return e.message;
    return tr(
      "Can't reach the server right now. It may still be waking up. Check your internet and try again.",
      'सर्वर से जुड़ नहीं पा रहे। हो सकता है वह अभी चालू हो रहा हो। इंटरनेट देखें और दोबारा कोशिश करें।',
    );
  }

  void _showError(Object e) {
    _stopWake();
    setState(() {
      _error = _friendly(e);
      _loading = false;
    });
  }

  Future<void> _init() async {
    final seq = ++_seq;
    setState(() {
      _loading = true;
      _error = null;
    });
    _startWake();
    try {
      await Api.i.fetchMe();
      final classes = await Api.i.classes();
      if (!mounted || seq != _seq) return;
      if (classes is List && classes.isNotEmpty) {
        _cls ??= _pickDefault(classes.cast<Map<String, dynamic>>());
      } else if (classes is List && _cls == null) {
        _stopWake();
        setState(() {
          _loading = false;
          _error = tr(
            'No class found — connect with your school.',
            'कोई कक्षा नहीं मिली — स्कूल से जोड़ें।',
          );
        });
        return;
      }
    } on ApiError catch (e) {
      if (!mounted || seq != _seq) return;
      if (e.status == 401) {
        await Api.i.logout();
        if (mounted) {
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(builder: (_) => const LoginScreen()),
            (_) => false,
          );
        }
        return;
      }
      if (_cls == null) return _showError(e);
    } catch (e) {
      if (!mounted || seq != _seq) return;
      if (_cls == null) return _showError(e);
    }
    if (_cls == null) {
      return _showError(ApiError('', 0));
    }
    await _loadSubjects();
    if (!mounted || seq != _seq) return;
    await _loadBoard();
  }

  Map<String, dynamic> _pickDefault(List<Map<String, dynamic>> classes) {
    final grade2 = classes.where((c) => c['grade'] == 2).toList();
    return (grade2.isNotEmpty ? grade2.first : classes.first);
  }

  /// Subject tabs from the server; the two built-ins if the call fails or the route is missing.
  Future<void> _loadSubjects() async {
    var list = _builtinSubjects;
    try {
      final r = await Api.i.get('/v1/classes/${_cls!['id']}/subjects');
      final parsed = _maps(r)
          .where((s) => (s['key'] ?? '').toString().isNotEmpty)
          .toList();
      if (parsed.isNotEmpty) list = parsed;
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _subjects = list;
      if (!list.any((s) => s['key'] == _subject)) {
        _subject = list.first['key'] as String;
      }
    });
  }

  Future<void> _loadBoard({
    bool showSpinner = true,
    bool freshMoves = false,
  }) async {
    final cls = _cls;
    if (cls == null) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    final seq = ++_seq;
    final subject = _subject;
    if (showSpinner) {
      setState(() {
        _loading = true;
        _error = null;
      });
      _startWake();
    }
    try {
      final b = await Api.i.board(cls['id'] as int, subject);
      if (!mounted || seq != _seq) return;
      if (b is! Map) throw ApiError('', 0);
      _stopWake();
      setState(() {
        _board = b.cast<String, dynamic>();
        _offline = b['offline'] == true;
        _error = null;
        _loading = false;
      });
      _loadMoved(cls['id'] as int, subject, seq, fresh: freshMoves);
      _resolveAbsentNames(cls['id'] as int);
    } catch (e) {
      if (!mounted || seq != _seq) return;
      if (_board == null) return _showError(e);
      // A background refresh failed: keep what is on screen and say it may be stale.
      _stopWake();
      setState(() {
        _offline = true;
        _loading = false;
      });
    }
  }

  /// "Who moved" since yesterday; any failure just hides the card.
  Future<void> _loadMoved(
    int classId,
    String subject,
    int seq, {
    bool fresh = false,
  }) async {
    var moves = <Map<String, dynamic>>[];
    try {
      final r = await Api.i.get(
        '/v1/classes/$classId/moved?subject=$subject&hours=24',
      );
      if (r is Map && r['offline'] != true) moves = _maps(r['moves']);
    } catch (_) {}
    if (!mounted || seq != _seq) return;
    setState(() {
      _moves = moves;
      if (fresh || moves.isEmpty) _movedDismissed = false;
    });
  }

  /// Absent children may not be listed on the board, so fetch the roster once for their names.
  Future<void> _resolveAbsentNames(int classId) async {
    final absent = _absentIds();
    if (absent.isEmpty || _rosterFor == classId) return;
    final known = _boardNames();
    if (absent.every(known.containsKey)) return;
    try {
      final rows = _maps(await Api.i.roster(classId));
      if (!mounted) return;
      setState(() {
        _rosterFor = classId;
        _rosterNames = {
          for (final r in rows)
            if (int.tryParse('${r['id']}') != null)
              int.parse('${r['id']}'): '${r['first_name'] ?? ''}',
        };
      });
    } catch (_) {}
  }

  List<int> _absentIds() {
    final a = _board?['absent'];
    return a is List
        ? a.map((e) => int.tryParse('$e')).whereType<int>().toList()
        : [];
  }

  Map<int, String> _boardNames() {
    final b = _board;
    final out = <int, String>{};
    if (b == null) return out;
    for (final key in const ['on_track', 'unassessed']) {
      for (final c in _maps(b[key])) {
        final id = int.tryParse('${c['id']}');
        if (id != null) out[id] = '${c['first_name'] ?? ''}';
      }
    }
    for (final g in _maps(b['groups'])) {
      for (final c in _maps(g['members'])) {
        final id = int.tryParse('${c['id']}');
        if (id != null) out[id] = '${c['first_name'] ?? ''}';
      }
    }
    return out;
  }

  void _selectSubject(String key) {
    if (key == _subject) return;
    setState(() {
      _subject = key;
      _board = null;
      _moves = [];
      _movedDismissed = false;
    });
    _loadBoard();
  }

  Future<void> _openPlan() async {
    if (_cls == null) return;
    await Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(
        builder: (_) => GroupPlanScreen(
          classId: _cls!['id'] as int,
          className: _cls!['label'] as String,
          subject: _subject,
        ),
      ),
    );
    // Marking a group done or regenerating changes the board; reload however we came back.
    if (mounted) _loadBoard(showSpinner: false, freshMoves: true);
  }

  Future<void> _openSyllabus() async {
    final cls = _cls;
    if (cls == null) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => SyllabusScreen(
          classId: cls['id'] as int,
          subject: _subject,
          className: '${cls['label'] ?? ''}',
        ),
      ),
    );
    if (mounted) _loadBoard(showSpinner: false);
  }

  /// Evidence sheet. It returns its "something changed" flag on every dismissal; only an explicit
  /// false skips the refresh, so a swipe-down or back press can't leave the board stale.
  Future<void> _capture({List<Map<String, dynamic>>? kids}) async {
    final cls = _cls;
    if (cls == null) return;
    final subject = _subject;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => CaptureSheet(
        classId: cls['id'] as int,
        subject: subject,
        presetChildren: kids,
      ),
    );
    if (!mounted || changed == false) return;
    _loadBoard(showSpinner: false, freshMoves: changed == true);
  }

  Future<void> _editAbsent() async {
    final cls = _cls;
    if (cls == null) return;
    final res = await showBoardAbsentSheet(
      context,
      classId: cls['id'] as int,
      absentIds: _absentIds(),
    );
    if (!mounted || res == null) return;
    setState(() => _board = {...?_board, 'absent': res.ids});
    if (res.queued) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr(
              'Saved on this phone. It will be sent when you are online.',
              'फ़ोन में सहेजा। नेटवर्क आने पर भेज दिया जाएगा।',
            ),
          ),
        ),
      );
    } else {
      _loadBoard(showSpinner: false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final loaded = !_loading && _error == null && _board != null;
    final absentIds = _absentIds();
    final names = _boardNames();
    final absentNames = [
      for (final id in absentIds)
        if ((names[id] ?? _rosterNames[id] ?? '').isNotEmpty)
          names[id] ?? _rosterNames[id]!,
    ];
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_cls?['label'] ?? tr('Kaksha Saathi', 'कक्षा साथी')),
            if (Api.i.me != null)
              Text(
                Api.i.me!['name'] ?? '',
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w400,
                  color: Ks.muted,
                ),
              ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: tr('Syllabus', 'पाठ्यक्रम'),
            icon: const Icon(Icons.checklist_rounded),
            onPressed: _cls == null ? null : _openSyllabus,
          ),
          IconButton(
            tooltip: tr('Classes', 'कक्षाएँ'),
            icon: const Icon(Icons.swap_horiz_rounded),
            onPressed: () async {
              final c = await Navigator.of(context).push<Map<String, dynamic>>(
                MaterialPageRoute(builder: (_) => const ClassPickerScreen()),
              );
              if (c != null && mounted) {
                setState(() {
                  _cls = c;
                  _board = null;
                  _moves = [];
                  _movedDismissed = false;
                  _subjects = _builtinSubjects;
                  _rosterFor = null;
                  _rosterNames = {};
                });
                _init();
              }
            },
          ),
          IconButton(
            tooltip: tr('Settings', 'सेटिंग्स'),
            icon: const Icon(Icons.settings_rounded),
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _loadBoard(showSpinner: false),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 110),
          children: [
            if (loaded && _moves.isNotEmpty && !_movedDismissed)
              BoardMovedBanner(
                moves: _moves,
                onDismiss: () => setState(() => _movedDismissed = true),
              ),
            _subjectTabs(),
            if (_offline) _offlineBanner(),
            const BoardPendingChip(),
            if (loaded && _board!['absent'] is List)
              BoardAbsentStrip(
                count: absentIds.length,
                names: absentNames,
                onEdit: _editAbsent,
              ),
            ..._content(),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _capture,
        backgroundColor: Ks.accent,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_a_photo_rounded),
        label: Text(
          tr('Add evidence', 'साक्ष्य जोड़ें'),
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  String _subjectLabel(Map<String, dynamic> s) => switch (s['key']) {
    'numeracy' => tr('Maths', 'गणित'),
    'literacy' => tr('Hindi', 'हिंदी'),
    _ => pick(s, 'name').isNotEmpty ? pick(s, 'name') : '${s['key']}',
  };

  IconData _subjectIcon(Map<String, dynamic> s) => switch (s['key']) {
    'numeracy' => Icons.calculate_rounded,
    'literacy' => Icons.menu_book_rounded,
    _ => Icons.auto_stories_rounded,
  };

  Widget _subjectTabs() => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SegmentedButton<String>(
        segments: [
          for (final s in _subjects)
            ButtonSegment(
              value: s['key'] as String,
              label: Text(_subjectLabel(s)),
              icon: Icon(_subjectIcon(s)),
            ),
        ],
        selected: {_subject},
        onSelectionChanged: (s) => _selectSubject(s.first),
        showSelectedIcon: false,
        style: ButtonStyle(
          minimumSize: WidgetStateProperty.all(const Size(140, 52)),
          textStyle: WidgetStateProperty.all(
            const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
          ),
        ),
      ),
    ),
  );

  Widget _offlineBanner() => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: Ks.amberSoft,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      children: [
        Icon(Icons.cloud_off_rounded, color: Ks.amber),
        SizedBox(width: 8),
        Expanded(
          child: Text(
            tr(
              'Offline — showing the last saved board.',
              'ऑफलाइन — पिछली बार का बोर्ड दिख रहा है।',
            ),
            style: TextStyle(color: Ks.amber),
          ),
        ),
      ],
    ),
  );

  List<Widget> _content() {
    if (_loading) {
      return [
        Padding(
          padding: EdgeInsets.only(top: 60),
          child: Loading(
            label: _waking
                ? tr(
                    'Waking up the server. The first load can take up to a minute…',
                    'सर्वर चालू हो रहा है। पहली बार में एक मिनट तक लग सकता है…',
                  )
                : tr('Loading class status…', 'कक्षा की स्थिति आ रही है…'),
          ),
        ),
      ];
    }
    if (_error != null) {
      return [
        const SizedBox(height: 24),
        EmptyState(icon: Icons.cloud_off_rounded, text: _error!),
        Center(
          child: SizedBox(
            width: 220,
            child: FilledButton.icon(
              onPressed: _init,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Try again', 'फिर कोशिश करें')),
            ),
          ),
        ),
      ];
    }
    final b = _board;
    if (b == null) return const [];
    final groups = _maps(b['groups']);
    final onTrack = _maps(b['on_track']);
    final unassessed = _maps(b['unassessed']);
    return [
      if (groups.isEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 4),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                children: [
                  const Icon(
                    Icons.celebration_rounded,
                    size: 40,
                    color: Ks.green,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    tr('No gaps right now', 'अभी कोई कमी नहीं'),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    tr(
                      'No new plan needed for any group today — everyone is on track or awaiting checks.',
                      'आज किसी समूह के लिए नई योजना नहीं — सब ट्रैक पर या जाँच बाकी है।',
                    ),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ],
              ),
            ),
          ),
        )
      else ...[
        SectionTitle(
          tr('Teach these children together', 'इन बच्चों को एक साथ पढ़ाएँ'),
        ),
        ...groups.map(_groupCard),
      ],
      if (unassessed.isNotEmpty) ...[
        SectionTitle(tr('Check pending — 3 taps', 'जाँच बाकी — 3 टैप')),
        _unassessedCard(unassessed),
      ],
      if (onTrack.isNotEmpty) ...[
        SectionTitle(
          tr('On track (${onTrack.length})', 'अपनी गति पर (${onTrack.length})'),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final c in onTrack)
                  BoardChildChip(
                    label: '${c['first_name'] ?? ''}',
                    background: Ks.greenSoft,
                    icon: Icons.check_rounded,
                    iconColor: Ks.green,
                    onTap: () => _openChild(c),
                  ),
              ],
            ),
          ),
        ),
      ],
    ];
  }

  Future<void> _openChild(Map<String, dynamic> c) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => LevelScreen(
          childId: c['id'] as int,
          childName: c['first_name'] as String,
          classId: _cls!['id'] as int,
          subject: _subject,
        ),
      ),
    );
    if (mounted) _loadBoard(showSpinner: false);
  }

  Widget _groupCard(Map<String, dynamic> g) {
    final status = g['status'] as String? ?? 'needs_practice';
    final reason = g['reason'] as String? ?? '';
    final members = _maps(g['members']);
    final nipun = '${g['nipun_ref'] ?? ''}'.trim();
    final reasonHi = switch (reason) {
      'needs_intervention_root' || 'needs_practice_root' => tr(
        'Foundation gap — start here first',
        'आधार की चूक — पहले यहीं से शुरू करें',
      ),
      'direct' => tr('Struggling in this lesson', 'इसी सबक में कठिनाई'),
      _ => '',
    };
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: _openPlan,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 44,
                    decoration: BoxDecoration(
                      color: Ks.statusColor[status],
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Wrap(
                          spacing: 8,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              tr(
                                '${g['chapter']} · ${members.length} children',
                                '${g['chapter']} · ${members.length} बच्चे',
                              ),
                              style: const TextStyle(
                                color: Ks.muted,
                                fontSize: 14,
                              ),
                            ),
                            if (nipun.isNotEmpty) BoardNipunBadge(nipun),
                          ],
                        ),
                        Text(
                          cpTitle(g),
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right_rounded, color: Ks.muted),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final m in members)
                    BoardChildChip(
                      label: '${m['first_name'] ?? ''}',
                      background:
                          Ks.statusBg[status] ?? Ks.statusBg['not_started']!,
                      onTap: () => _openChild(m),
                    ),
                ],
              ),
              if (reasonHi.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(
                      Icons.lightbulb_outline_rounded,
                      size: 16,
                      color: Ks.muted,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        reasonHi,
                        style: const TextStyle(color: Ks.muted, fontSize: 14),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _unassessedCard(List<Map<String, dynamic>> kids) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final c in kids)
                BoardChildChip(
                  label: '${c['first_name'] ?? ''}',
                  background: Ks.statusBg['not_started']!,
                  onTap: () => _capture(kids: [c]),
                ),
            ],
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: () => _capture(kids: kids),
            icon: const Icon(Icons.touch_app_rounded),
            label: Text(tr('Check in 3 taps', 'तीन टैप में जाँचें')),
          ),
        ],
      ),
    ),
  );
}
