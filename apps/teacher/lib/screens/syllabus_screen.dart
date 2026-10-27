import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import '../widgets/capture_sheet.dart';
import '../widgets/syllabus_add_topic.dart';
import '../widgets/syllabus_import.dart';
import '../widgets/syllabus_widgets.dart';

/// Syllabus & progress: every lesson (checkpoint) of a subject with how many children are
/// done / in progress / not started, plus add-topic and index-photo import.
/// "Done / in progress / not started" is defined once in `syllabus_widgets.dart` (`sylTopicState`).
class SyllabusScreen extends StatefulWidget {
  const SyllabusScreen({
    super.key,
    required this.classId,
    required this.subject,
    required this.className,
  });
  final int classId;
  final String subject;
  final String className;
  @override
  State<SyllabusScreen> createState() => _SyllabusScreenState();
}

enum _Filter { all, notStarted, inProgress, done }

class _SyllabusScreenState extends State<SyllabusScreen> {
  late String _subject = widget.subject;
  List<Map<String, dynamic>> _subjects = [];
  late Future<Map<String, dynamic>> _future;
  Map<String, dynamic>?
  _last; // last good response, kept on screen while reloading
  _Filter _filter = _Filter.all;
  final Set<String> _open = {};
  String? _openFor; // subject the default-open chapter was chosen for

  @override
  void initState() {
    super.initState();
    _future = _fetch();
    _loadSubjects();
  }

  Future<void> _loadSubjects() async {
    var list = <Map<String, dynamic>>[];
    try {
      final r = await Api.i.get('/v1/classes/${widget.classId}/subjects');
      list = sylMaps(r).where((s) => s['key'] != null).toList();
    } catch (_) {
      // Fall through to the built-ins.
    }
    if (list.isEmpty) {
      list = [
        {'key': 'numeracy', 'name_en': 'Maths', 'name_hi': 'गणित'},
        {'key': 'literacy', 'name_en': 'Hindi', 'name_hi': 'हिन्दी'},
      ];
    }
    if (!list.any((s) => s['key'] == widget.subject)) {
      list.add({
        'key': widget.subject,
        'name_en': widget.subject,
        'name_hi': widget.subject,
      });
    }
    if (mounted) setState(() => _subjects = list);
  }

  Future<Map<String, dynamic>> _fetch() async {
    final r = await Api.i.get(
      '/v1/classes/${widget.classId}/syllabus?subject=${Uri.encodeQueryComponent(_subject)}',
    );
    final m = (r as Map).cast<String, dynamic>();
    _pickOpenDefault(m);
    return m;
  }

  /// Collapsed by default, except the first chapter that has any activity.
  void _pickOpenDefault(Map<String, dynamic> m) {
    if (_openFor == _subject) return;
    _openFor = _subject;
    _open.clear();
    for (final c in sylMaps(m['chapters'])) {
      final active = sylMaps(c['topics'])
          .any((t) => sylTopicState(t) != TopicState.notStarted);
      if (active) {
        _open.add((c['chapter'] ?? '').toString());
        break;
      }
    }
  }

  void _reload() => setState(() => _future = _fetch());

  Future<void> _refresh() async {
    final f = _fetch();
    setState(() => _future = f);
    try {
      await f;
    } catch (_) {
      // The error view (or the stale copy) is shown by the FutureBuilder.
    }
  }

  void _switchSubject(String key) {
    if (key == _subject) return;
    setState(() {
      _subject = key;
      _last = null;
      _filter = _Filter.all;
      _future = _fetch();
    });
  }

  void _toast(String s) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));

  String _subjectLabel(Map<String, dynamic> s) {
    final name = pick(s, 'name');
    return name.isEmpty ? s['key'].toString() : name;
  }

  // ---- actions
  Future<void> _openTopic(Map<String, dynamic> topic, String chapter) async {
    final action = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => SylTopicSheet(topic: topic, chapter: chapter),
    );
    if (!mounted || action == null) return;
    final id = topic['checkpoint_id'].toString();
    if (action == 'check') {
      final changed = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Ks.paper,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
        ),
        builder: (_) => CaptureSheet(
          classId: widget.classId,
          subject: _subject,
          presetCheckpointId: id,
        ),
      );
      if (changed == true && mounted) _reload();
    } else if (action == 'remove') {
      await _confirmRemove(topic);
    }
  }

  Future<void> _confirmRemove(Map<String, dynamic> topic) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Remove this topic?', 'यह विषय हटाएँ?')),
        content: Text(
          tr(
            '"${cpTitle(topic)}" will leave the syllabus. Evidence already recorded for it is not deleted.',
            '"${cpTitle(topic)}" पाठ्यक्रम से हट जाएगा। इसके लिए दर्ज प्रमाण नहीं मिटेंगे।',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(tr('Cancel', 'रद्द करें')),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Ks.rose),
            child: Text(tr('Remove', 'हटाएँ')),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final id = Uri.encodeComponent(topic['checkpoint_id'].toString());
      await Api.i.delete(
        '/v1/classes/${widget.classId}/syllabus/topics/$id?subject=${Uri.encodeQueryComponent(_subject)}',
      );
      if (!mounted) return;
      _toast(tr('Removed from the syllabus.', 'पाठ्यक्रम से हटा दिया।'));
      _reload();
    } on ApiError catch (e) {
      if (mounted) _toast(e.message);
    } catch (_) {
      if (mounted) {
        _toast(
          tr(
            'Could not remove it. Check the network and try again.',
            'हटा नहीं सके। नेटवर्क देखकर दोबारा कोशिश करें।',
          ),
        );
      }
    }
  }

  Future<void> _addTopic() async {
    final chapters = <String>[
      for (final c in sylMaps(_last?['chapters']))
        if ((c['chapter'] ?? '').toString().trim().isNotEmpty)
          (c['chapter']).toString().trim(),
    ];
    final added = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => SylAddTopicSheet(
        classId: widget.classId,
        subject: _subject,
        chapters: chapters,
      ),
    );
    if (added == true && mounted) {
      _toast(tr('Topic added.', 'विषय जुड़ गया।'));
      _reload();
    }
  }

  Future<void> _import() async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => SylImportScreen(
          classId: widget.classId,
          subject: _subject,
          existingChapters: sylMaps(_last?['chapters']),
          confirmed: _last?['confirmed'] == true,
        ),
      ),
    );
    if (saved == true && mounted) {
      _toast(tr('Syllabus saved.', 'पाठ्यक्रम सहेज लिया।'));
      _reload();
    }
  }

  void _showLegend() => showModalBottomSheet<void>(
    context: context,
    backgroundColor: Ks.paper,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (_) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              tr('How to read this', 'इसे कैसे पढ़ें'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            const SylLegend(),
          ],
        ),
      ),
    ),
  );

  // ---- build
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(tr('Syllabus', 'पाठ्यक्रम')),
            Text(
              widget.className,
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
                color: Ks.muted,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: tr('What do the colours mean?', 'रंगों का मतलब'),
            onPressed: _showLegend,
            icon: const Icon(Icons.help_outline_rounded),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addTopic,
        backgroundColor: Ks.accent,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_rounded),
        label: Text(tr('Add topic', 'विषय जोड़ें')),
      ),
      body: Column(
        children: [
          _subjectChips(),
          Expanded(
            child: FutureBuilder<Map<String, dynamic>>(
              future: _future,
              builder: (context, snap) {
                if (snap.hasData) _last = snap.data;
                final loading = snap.connectionState != ConnectionState.done;
                final data = snap.hasData
                    ? snap.data
                    : (loading ? _last : null);
                if (data == null) {
                  if (loading) return const Loading();
                  return _errorView(snap.error);
                }
                return Column(
                  children: [
                    if (loading)
                      const LinearProgressIndicator(
                        minHeight: 3,
                        color: Ks.accent,
                      ),
                    Expanded(child: _content(data)),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _subjectChips() {
    final list = _subjects.isEmpty
        ? [
            {
              'key': widget.subject,
              'name_en': widget.subject,
              'name_hi': widget.subject,
            },
          ]
        : _subjects;
    return SizedBox(
      height: 54,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 6),
        itemCount: list.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final s = list[i];
          return ChoiceChip(
            label: Text(_subjectLabel(s), style: const TextStyle(fontSize: 15)),
            selected: s['key'] == _subject,
            onSelected: (_) => _switchSubject(s['key'].toString()),
          );
        },
      ),
    );
  }

  Widget _errorView(Object? err) {
    final msg = err is ApiError
        ? err.message
        : tr(
            'Could not load the syllabus. Check the network.',
            'पाठ्यक्रम नहीं खुल सका। नेटवर्क देखें।',
          );
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded, size: 48, color: Ks.muted),
            const SizedBox(height: 12),
            Text(
              msg,
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
  }

  bool _matches(_Filter f, Map<String, dynamic> topic) {
    final s = sylTopicState(topic);
    return switch (f) {
      _Filter.all => true,
      _Filter.notStarted => s == TopicState.notStarted,
      _Filter.inProgress => s == TopicState.inProgress,
      _Filter.done => s == TopicState.done,
    };
  }

  Widget _content(Map<String, dynamic> data) {
    final chapters = sylMaps(data['chapters']);
    final all = [for (final c in chapters) ...sylMaps(c['topics'])];
    if (all.isEmpty) return _empty();

    var done = 0, progress = 0, notStarted = 0;
    for (final t in all) {
      switch (sylTopicState(t)) {
        case TopicState.done:
          done++;
        case TopicState.inProgress:
          progress++;
        case TopicState.notStarted:
          notStarted++;
      }
    }
    final shown = <(String, List<Map<String, dynamic>>)>[];
    for (final c in chapters) {
      final ts = sylMaps(c['topics'])
          .where((t) => _matches(_filter, t))
          .toList();
      if (ts.isNotEmpty) shown.add(((c['chapter'] ?? '').toString(), ts));
    }
    final offline = data['offline'] == true;
    final children = sylInt(data['children']);

    return RefreshIndicator(
      color: Ks.accent,
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
        children: [
          if (offline)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Align(
                alignment: Alignment.centerLeft,
                child: SylTag(
                  tr(
                    'Offline: showing the last saved copy',
                    'ऑफ़लाइन: पिछली सहेजी हुई सूची दिख रही है',
                  ),
                  icon: Icons.cloud_off_rounded,
                  bg: Ks.amberSoft,
                  fg: SylColors.amberText,
                ),
              ),
            ),
          _summary(all.length, done, progress, notStarted, children),
          const SizedBox(height: 12),
          _filterChips(all.length, done, progress, notStarted),
          const SizedBox(height: 12),
          if (shown.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: EmptyState(
                icon: Icons.filter_list_off_rounded,
                text: tr(
                  'No topics match this filter.',
                  'इस फ़िल्टर में कोई विषय नहीं।',
                ),
              ),
            ),
          for (final (name, topics) in shown) ...[
            SylChapterCard(
              name: name,
              topics: topics,
              open: _filter != _Filter.all || _open.contains(name),
              onToggle: () => setState(() {
                if (!_open.remove(name)) _open.add(name);
              }),
              onTopicTap: (t) => _openTopic(t, name),
            ),
            const SizedBox(height: 10),
          ],
          const SizedBox(height: 4),
          _importButton(),
          const SizedBox(height: 14),
          const SylLegend(),
        ],
      ),
    );
  }

  Widget _importButton() => OutlinedButton.icon(
    onPressed: _import,
    icon: const Icon(Icons.photo_camera_rounded),
    label: Text(
      tr(
        'Import syllabus from a book index photo',
        'किताब की विषय-सूची की फ़ोटो से पाठ्यक्रम जोड़ें',
      ),
      textAlign: TextAlign.center,
    ),
  );

  Widget _summary(int n, int done, int progress, int notStarted, int kids) {
    Widget seg(int flex, Color c) => Expanded(
      flex: flex,
      child: Container(color: c),
    );
    final gap = Container(width: 2, color: Ks.card);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              tr(
                '$n topics · $done done · $progress in progress · $notStarted not started',
                '$n विषय · $done पूरे · $progress चल रहे · $notStarted शुरू नहीं',
              ),
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Ks.ink,
                height: 1.35,
              ),
            ),
            const SizedBox(height: 10),
            // Topic-level bar: done (green) / in progress (amber) / not started (grey).
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                height: 10,
                child: Row(
                  children: [
                    if (done > 0) seg(done, Ks.green),
                    if (done > 0 && (progress > 0 || notStarted > 0)) gap,
                    if (progress > 0) seg(progress, SylColors.amberBar),
                    if (progress > 0 && notStarted > 0) gap,
                    if (notStarted > 0) seg(notStarted, SylColors.greyBar),
                  ],
                ),
              ),
            ),
            if (kids > 0) ...[
              const SizedBox(height: 8),
              Text(
                tr('$kids children in the class', 'कक्षा में $kids बच्चे'),
                style: const TextStyle(fontSize: 13.5, color: Ks.muted),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _filterChips(int all, int done, int progress, int notStarted) {
    Widget chip(_Filter f, String label, int n) => ChoiceChip(
      label: Text('$label ($n)', style: const TextStyle(fontSize: 14.5)),
      selected: _filter == f,
      onSelected: (_) => setState(() => _filter = f),
    );
    return Wrap(
      spacing: 8,
      runSpacing: 4,
      children: [
        chip(_Filter.all, tr('All', 'सभी'), all),
        chip(_Filter.notStarted, tr('Not started', 'शुरू नहीं'), notStarted),
        chip(_Filter.inProgress, tr('In progress', 'चल रहा है'), progress),
        chip(_Filter.done, tr('Done', 'पूरा'), done),
      ],
    );
  }

  Widget _empty() {
    return RefreshIndicator(
      color: Ks.accent,
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 24, 16, 96),
        children: [
          EmptyState(
            icon: Icons.menu_book_rounded,
            text: tr(
              'No topics yet — add one or import from your book',
              'अभी कोई विषय नहीं — एक जोड़ें या अपनी किताब से जोड़ें',
            ),
          ),
          const SizedBox(height: 8),
          _importButton(),
        ],
      ),
    );
  }
}
