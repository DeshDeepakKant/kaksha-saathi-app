import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../tts.dart';
import '../l10n.dart';
import '../widgets/capture_sheet.dart';
import '../widgets/read_aloud_sheet.dart';
import '../widgets/trend_chart.dart';

/// One child's learning map: status per checkpoint, evidence timeline, misconception hints,
/// probe suggestion, and a one-tap 3-item probe.
class LevelScreen extends StatefulWidget {
  const LevelScreen({
    super.key,
    required this.childId,
    required this.childName,
    required this.classId,
    required this.subject,
  });
  final int childId;
  final String childName;
  final int classId;
  final String subject;
  @override
  State<LevelScreen> createState() => _LevelScreenState();
}

class _LevelScreenState extends State<LevelScreen> {
  Map<String, dynamic>? _profile;
  List<dynamic> _history = const [];
  List<Map<String, dynamic>> _trend = const [];
  final Map<String, List<String>> _targets =
      {}; // lesson id -> words to read aloud
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// [silent] keeps the current profile on screen (pull-to-refresh, after saving evidence).
  Future<void> _load({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final results = await Future.wait<dynamic>([
        Api.i.profile(widget.childId, widget.subject),
        Api.i
            .history(widget.childId, subject: widget.subject)
            .catchError((_) => const []),
        Api.i
            .get(
              '/v1/children/${widget.childId}/timeline?subject=${widget.subject}&weeks=6',
            )
            .catchError((_) => null),
      ]);
      if (!mounted) return;
      final p = results[0] as Map<String, dynamic>;
      final tl = results[2];
      setState(() {
        _profile = p;
        _history = results[1] is List ? results[1] as List : const [];
        _trend = tl is Map && tl['points'] is List
            ? (tl['points'] as List).whereType<Map<String, dynamic>>().toList()
            : const [];
        _error = null;
        _loading = false;
      });
      _loadTargets(p);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        // a failed silent refresh keeps the old profile; a first load shows the retry state
        if (!silent || _profile == null) _error = e.toString();
        _loading = false;
      });
      if (silent && _profile != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              tr(
                'Could not refresh. Showing the last copy.',
                'ताज़ा नहीं हो पाया। पिछली जानकारी दिख रही है।',
              ),
            ),
          ),
        );
      }
    }
  }

  /// Which "needs attention" lessons have words to read aloud (decides the Reading check button).
  Future<void> _loadTargets(Map<String, dynamic> p) async {
    final ids = _needs((p['items'] as List).cast<Map<String, dynamic>>())
        .take(4)
        .map((i) => i['checkpoint_id'] as String);
    for (final id in ids) {
      if (_targets.containsKey(id)) continue;
      try {
        final r = await Api.i.checkpointTargets(id);
        final words = r is Map && r['has_items'] == true
            ? ((r['targets'] as List?) ?? const [])
                  .map((t) => '$t'.trim())
                  .where((t) => t.isNotEmpty && !t.contains('?'))
                  .take(6)
                  .toList()
            : <String>[];
        if (!mounted) return;
        setState(() => _targets[id] = words);
      } catch (_) {
        if (!mounted) return;
        _targets[id] = const []; // no button; not worth an error on the profile
      }
    }
  }

  List<Map<String, dynamic>> _needs(List<Map<String, dynamic>> items) =>
      items
          .where(
            (i) =>
                i['status'] == 'needs_intervention' ||
                i['status'] == 'needs_practice',
          )
          .toList()
        ..sort(
          (a, b) => (a['status'] == 'needs_intervention' ? 0 : 1).compareTo(
            b['status'] == 'needs_intervention' ? 0 : 1,
          ),
        );

  Future<void> _addEvidence({String? checkpointId}) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => CaptureSheet(
        classId: widget.classId,
        subject: widget.subject,
        presetCheckpointId: checkpointId,
        presetChildIds: [widget.childId],
      ),
    );
    if (changed == true) _load(silent: true);
  }

  Future<void> _readAloud(Map<String, dynamic> item) async {
    final cp = item['checkpoint_id'] as String;
    final words = _targets[cp] ?? const <String>[];
    if (words.isEmpty) return;
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => ReadAloudSheet(
        classId: widget.classId,
        childId: widget.childId,
        childName: widget.childName,
        checkpointId: cp,
        title: cpTitle(item),
        targets: words,
      ),
    );
    if (saved == true) _load(silent: true);
  }

  Future<void> _probe(Map<String, dynamic> item) async {
    final cp = item['checkpoint_id'] as String;
    dynamic probe;
    try {
      probe = await Api.i.probe(cp);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr('Could not load questions: $e', 'प्रश्न नहीं मिले: $e'),
          ),
        ),
      );
      return;
    }
    final p = probe['probe'] as Map<String, dynamic>?;
    final items = (p?['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    if (!mounted) return;
    // state lives here, outside the builder, so rebuilds don't reset the answer
    var passed = 0;
    var saving = false;
    String? saveError;
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSt) {
          return Padding(
            padding: EdgeInsets.fromLTRB(
              20,
              16,
              20,
              20 + MediaQuery.of(ctx).viewInsets.bottom,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  p?['title_hi'] ?? tr('Check', 'जाँच'),
                  style: Theme.of(ctx).textTheme.titleLarge,
                ),
                const SizedBox(height: 6),
                Text(
                  tr(
                    'Ask ${widget.childName}:',
                    '${widget.childName} से पूछें:',
                  ),
                  style: const TextStyle(color: Ks.muted),
                ),
                const SizedBox(height: 12),
                for (final it in items)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            it['ask_hi'],
                            style: const TextStyle(fontSize: 17),
                          ),
                        ),
                        IconButton(
                          tooltip: tr('Listen', 'सुनें'),
                          icon: const Icon(
                            Icons.volume_up_rounded,
                            color: Ks.accent,
                          ),
                          onPressed: () => Speak.say(it['ask_hi']),
                        ),
                      ],
                    ),
                  ),
                if (items.isEmpty)
                  Text(
                    tr(
                      'No ready-made question for this lesson — check directly with taps.',
                      'इस सबक का तैयार प्रश्न नहीं — सीधे टैप में जाँचें।',
                    ),
                  ),
                if ((p?['tell_hi'] as String?)?.isNotEmpty == true)
                  Padding(
                    padding: const EdgeInsets.only(top: 4, bottom: 10),
                    child: Text(
                      p!['tell_hi'],
                      style: const TextStyle(color: Ks.muted),
                    ),
                  ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => setSt(() => passed = 0),
                        child: Text(tr('Not correct', 'सही नहीं')),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: FilledButton(
                        onPressed: () => setSt(() => passed = items.length),
                        child: Text(tr('All correct', 'सब सही')),
                      ),
                    ),
                  ],
                ),
                if (saveError != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      saveError!,
                      style: const TextStyle(color: Ks.rose, fontSize: 14),
                    ),
                  ),
                const SizedBox(height: 10),
                FilledButton.icon(
                  onPressed: items.isEmpty || saving
                      ? null
                      : () async {
                          setSt(() {
                            saving = true;
                            saveError = null;
                          });
                          try {
                            final r = await Api.i.postQueued(
                              '/v1/classes/${widget.classId}/captures/probe?child_id=${widget.childId}&checkpoint_id=$cp&passed=$passed&total=${items.length}',
                              {},
                            );
                            if (ctx.mounted) Navigator.of(ctx).pop();
                            if (!mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(
                                  r is Map && r['queued'] == true
                                      ? tr(
                                          'No internet. Saved on this phone and will send later.',
                                          'इंटरनेट नहीं है। फ़ोन में रखा है, बाद में भेजा जाएगा।',
                                        )
                                      : tr('Check saved.', 'जाँच दर्ज हो गई।'),
                                ),
                              ),
                            );
                            _load(silent: true);
                          } catch (e) {
                            if (!ctx.mounted) return;
                            setSt(() {
                              saving = false;
                              saveError = tr(
                                'Could not save the check. Try again. ($e)',
                                'जाँच दर्ज नहीं हो पाई। दोबारा कोशिश करें। ($e)',
                              );
                            });
                          }
                        },
                  icon: const Icon(Icons.save_rounded),
                  label: Text(
                    saving
                        ? tr('Saving…', 'दर्ज हो रहा है…')
                        : tr(
                            'Save check ($passed/${items.length})',
                            'जाँच दर्ज करें ($passed/${items.length})',
                          ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.childName),
        actions: [
          IconButton(
            tooltip: tr('Refresh', 'ताज़ा करें'),
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loading ? null : () => _load(),
          ),
        ],
      ),
      body: _loading
          ? const Loading()
          : _error != null || _profile == null
          ? _errorView()
          : RefreshIndicator(
              color: Ks.accent,
              onRefresh: () => _load(silent: true),
              child: _body(),
            ),
    );
  }

  Widget _errorView() => Center(
    child: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          EmptyState(
            icon: Icons.error_outline,
            text: tr(
              'Could not load ${widget.childName}\'s profile.\n${_error ?? ''}',
              '${widget.childName} की प्रोफ़ाइल नहीं खुल पाई।\n${_error ?? ''}',
            ),
          ),
          FilledButton.icon(
            onPressed: () => _load(),
            icon: const Icon(Icons.refresh_rounded),
            label: Text(tr('Retry', 'दोबारा कोशिश करें')),
          ),
        ],
      ),
    ),
  );

  Widget _body() {
    final p = _profile!;
    final items = (p['items'] as List).cast<Map<String, dynamic>>();
    final needs = _needs(items);
    final titles = {for (final i in items) i['checkpoint_id'] as String: i};
    final assessed = items.where((i) => i['status'] != 'not_started').length;
    final chapters = <String, List<Map<String, dynamic>>>{};
    for (final i in items) {
      (chapters[i['chapter'] as String? ?? tr('Other', 'अन्य')] ??= []).add(i);
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 26,
              backgroundColor: Ks.accentSoft,
              child: Text(
                '${p['child']['roll_no']}',
                style: const TextStyle(
                  color: Ks.accent,
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tr(
                      '$assessed / ${items.length} lessons assessed',
                      '$assessed / ${items.length} सबक जाँचे गए',
                    ),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    widget.subject == 'numeracy'
                        ? tr('Maths', 'गणित')
                        : widget.subject == 'literacy'
                        ? tr('Hindi', 'हिंदी')
                        : widget.subject,
                    style: const TextStyle(color: Ks.muted),
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        FilledButton.tonalIcon(
          onPressed: () => _addEvidence(),
          icon: const Icon(Icons.add_task_rounded),
          label: Text(tr('Add evidence', 'साक्ष्य जोड़ें')),
        ),
        const SizedBox(height: 14),
        if (_trend.length >= 2) ...[
          SectionTitle(tr('Progress over time', 'समय के साथ प्रगति')),
          TrendCard(points: _trend),
        ],
        if (needs.isNotEmpty) ...[
          SectionTitle(tr('Needs attention now', 'अभी ध्यान दें')),
          ...needs.take(4).map((i) => _focusCard(i)),
        ] else
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                tr(
                  'No major gap visible yet. Start from the board with children whose checks are pending.',
                  'अभी कोई बड़ी चूक नहीं दिख रही। ऊपर बोर्ड से जाँच बाकी बच्चों से शुरू करें।',
                ),
              ),
            ),
          ),
        SectionTitle(tr('Full map', 'पूरा नक्शा')),
        for (final ch in chapters.entries) ...[
          Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 6),
            child: Text(
              ch.key,
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 15,
                color: Ks.muted,
              ),
            ),
          ),
          for (final i in ch.value) _row(i),
        ],
        if (_history.isNotEmpty) ...[
          SectionTitle(tr('Recent evidence', 'हाल के सबूत')),
          for (final h in _history.take(12))
            _historyRow(h as Map<String, dynamic>, titles),
        ],
      ],
    );
  }

  Widget _focusCard(Map<String, dynamic> i) {
    final misc = i['misconception_top'] as String?;
    final improving = i['improving'] == true;
    final lowConf = (i['confidence'] as num? ?? 0) < 0.5;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    cpTitle(i),
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (improving)
                  Padding(
                    padding: EdgeInsets.only(right: 6),
                    child: Tooltip(
                      message: tr('Improving', 'सुधर रहा है'),
                      child: Icon(
                        Icons.trending_up_rounded,
                        color: Ks.green,
                        size: 20,
                      ),
                    ),
                  ),
                StatusChip(i['status'], compact: true),
              ],
            ),
            if (_nipun(i) != null) _nipunChip(i),
            if (misc != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  tr(
                    'Likely gap: ${_miscHi(misc)}',
                    'संभावित चूक: ${_miscHi(misc)}',
                  ),
                  style: const TextStyle(color: Ks.rose, fontSize: 14),
                ),
              ),
            if (lowConf)
              Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text(
                  tr(
                    'Little evidence — check with taps',
                    'सबूत कम — टैप से जाँचें',
                  ),
                  style: TextStyle(color: Ks.muted, fontSize: 13),
                ),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: () => _probe(i),
                  icon: const Icon(Icons.quiz_rounded, size: 18),
                  label: Text(
                    tr(
                      'Check in 2 minutes (with questions)',
                      '2 मिनट में जाँचें (प्रश्न सहित)',
                    ),
                  ),
                ),
                if ((_targets[i['checkpoint_id']] ?? const []).isNotEmpty)
                  OutlinedButton.icon(
                    onPressed: () => _readAloud(i),
                    icon: const Icon(Icons.record_voice_over_rounded, size: 18),
                    label: Text(tr('Reading check', 'पढ़ने की जाँच')),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String? _nipun(Map<String, dynamic> i) {
    final n = (i['nipun_ref'] as String?)?.trim();
    return n == null || n.isEmpty ? null : n;
  }

  /// Small "NIPUN" reference chip (the national learning-outcome code for this lesson).
  Widget _nipunChip(Map<String, dynamic> i) => Padding(
    padding: const EdgeInsets.only(top: 4),
    child: Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: Ks.accentSoft,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(
          'NIPUN ${_nipun(i)}',
          style: const TextStyle(
            fontSize: 11,
            color: Ks.accent,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    ),
  );

  Widget _row(Map<String, dynamic> i) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(cpTitle(i), style: const TextStyle(fontSize: 15)),
              if (_nipun(i) != null) _nipunChip(i),
            ],
          ),
        ),
        const SizedBox(width: 8),
        StatusChip(i['status'], compact: true),
        IconButton(
          tooltip: tr('Check this', 'यह जाँचें'),
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.add_task_rounded, size: 20, color: Ks.accent),
          onPressed: () =>
              _addEvidence(checkpointId: i['checkpoint_id'] as String),
        ),
      ],
    ),
  );

  Widget _historyRow(
    Map<String, dynamic> h,
    Map<String, Map<String, dynamic>> lessons,
  ) {
    final result = h['result'] as String? ?? '';
    final icon = result == 'correct'
        ? Icons.check_rounded
        : (result == 'partial' ? Icons.remove_rounded : Icons.close_rounded);
    final color = result == 'correct'
        ? Ks.green
        : (result == 'partial' ? Ks.amber : Ks.rose);
    final at = DateTime.tryParse(h['at'] as String? ?? '')?.toLocal();
    final when = at == null ? '' : '${at.day}/${at.month}';
    final id = h['checkpoint_id'] as String? ?? '';
    final lesson = lessons[id];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              lesson != null ? cpTitle(lesson) : _shortCp(id),
              style: const TextStyle(fontSize: 14),
            ),
          ),
          Text(
            '${_srcHi(h['source'] as String? ?? '')} · $when',
            style: const TextStyle(color: Ks.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  String _shortCp(String id) => id.split('.').last.replaceAll('_', ' ');
  String _srcHi(String s) =>
      {
        'teacher_tap': tr('Tap', 'टैप'),
        'photo_work': tr('Photo', 'फ़ोटो'),
        'class_voice': tr('Voice', 'आवाज़'),
        'teacher_note': tr('Spoken', 'बोलकर'),
        'guided_probe': tr('Check', 'जाँच'),
        'home_voice': tr('Home', 'घर'),
        'home_tap': tr('Home', 'घर'),
      }[s] ??
      tr('Other', 'अन्य');
  String _miscHi(String m) =>
      {
        'smaller_minus_larger': tr(
          'Subtracts the smaller from the larger',
          'छोटे में से बड़ा घटा रहा है',
        ),
        'borrow_from_wrong_column': tr(
          'Borrows from the wrong place',
          'उधार गलत जगह से',
        ),
        'ignores_zero_borrow': tr(
          'Doesn\'t understand borrowing across zero',
          'शून्य वाला उधार नहीं समझा',
        ),
        'forgets_carry': tr('Forgets to carry', 'हासिल भूल रहा है'),
        'confuses_sa_sha': tr('Confuses स and श', 'स और श में फर्क नहीं'),
        'confuses_i_ii_matra': tr(
          'Confuses the इ and ई matras',
          'इ और ई की मात्रा में फर्क नहीं',
        ),
        'ignores_matra': tr('Drops the matra', 'मात्रा छोड़ देता है'),
        'reads_letters_separately': tr(
          'Reads letters one by one',
          'अक्षर अलग-अलग पढ़ता है',
        ),
        'treats_digits_as_separate': tr(
          'Treats digits separately',
          'अंकों को अलग-अलग समझता है',
        ),
      }[m] ??
      m;
}
