import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../tts.dart';

import '../api.dart';
import '../theme.dart';
import '../l10n.dart';
import '../widgets/capture_sheet.dart';

/// Today's intervention plan: one card per group, blackboard version, reassessment, TTS.
class GroupPlanScreen extends StatefulWidget {
  const GroupPlanScreen({
    super.key,
    required this.classId,
    required this.className,
    required this.subject,
  });
  final int classId;
  final String className;
  final String subject;
  @override
  State<GroupPlanScreen> createState() => _GroupPlanScreenState();
}

class _GroupPlanScreenState extends State<GroupPlanScreen> {
  static const _doneKey = 'plan_done_groups';

  Map<String, dynamic>? _plan;
  bool _loading = true;
  bool _busy = false; // a load is in flight (spinner or pull-to-refresh)
  bool _slow =
      false; // loading for more than ~8 s: the server is probably waking up
  String? _error;
  Timer? _slowTimer;

  /// "planId:groupKey" for groups the teacher marked done (kept across app restarts).
  final Set<String> _done = {};
  final Set<String> _queued = {}; // done, but saved offline and waiting to sync
  final Set<String> _doing = {}; // done request in flight (guards double taps)

  @override
  void initState() {
    super.initState();
    _restoreDone();
    _load();
  }

  @override
  void dispose() {
    _slowTimer?.cancel();
    super.dispose();
  }

  Future<void> _restoreDone() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final saved = sp.getStringList(_doneKey) ?? const <String>[];
      if (mounted) setState(() => _done.addAll(saved));
    } catch (_) {}
  }

  Future<void> _persistDone() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final all = _done.toList();
      await sp.setStringList(
        _doneKey,
        all.length > 300 ? all.sublist(all.length - 300) : all,
      );
    } catch (_) {}
  }

  /// The device's local calendar day (yyyy-mm-dd), sent to the server as `for_date` so the plan's
  /// "today" matches the teacher's day, not the server's UTC day.
  String _localDay() {
    final n = DateTime.now();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${n.year.toString().padLeft(4, '0')}-${two(n.month)}-${two(n.day)}';
  }

  Future<Map<String, dynamic>> _generate(
    String day, {
    required bool force,
  }) async => await Api.i.postJson(
    '/v1/classes/${widget.classId}/plans?subject=${widget.subject}&force=$force&for_date=$day',
    {},
  ) as Map<String, dynamic>;

  /// Loads today's saved plan, or generates it when none exists yet. [force] asks the AI again (paid,
  /// up to ~40 s on a sleeping server). [silent] keeps the current plan on screen (pull-to-refresh).
  Future<void> _load({bool force = false, bool silent = false}) async {
    if (_busy) return;
    _busy = true;
    _slowTimer?.cancel();
    if (!silent) {
      setState(() {
        _loading = true;
        _slow = false;
        _error = null;
      });
      _slowTimer = Timer(const Duration(seconds: 8), () {
        if (mounted && _loading) setState(() => _slow = true);
      });
    }
    final today = _localDay();
    Map<String, dynamic>? latest;
    try {
      Map<String, dynamic> p;
      if (force) {
        p = await _generate(today, force: true);
        final id = p['id'];
        if (id != null) {
          _done.removeWhere((k) => k.startsWith('$id:'));
          _queued.removeWhere((k) => k.startsWith('$id:'));
          _persistDone();
        }
      } else {
        latest = await Api.i.latestPlan(
          widget.classId,
          widget.subject,
        ) as Map<String, dynamic>;
        if (latest['exists'] == true && latest['for_date'] == today) {
          p = latest;
        } else {
          p = await _generate(today, force: false);
        }
      }
      if (mounted) setState(() => _plan = p);
    } catch (e) {
      if (!mounted) return;
      if (latest != null && latest['exists'] == true) {
        // Could not build today's plan: show the last saved one, clearly labelled.
        setState(() => _plan = {...latest!, 'offline': true});
      } else if (_plan != null) {
        // Keep what is on screen; just tell the teacher it did not refresh.
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              tr(
                'Could not refresh — showing the saved plan. ($e)',
                'ताज़ा नहीं हो सका — सहेजी योजना दिख रही है। ($e)',
              ),
            ),
          ),
        );
      } else {
        setState(() => _error = e.toString());
      }
    } finally {
      _busy = false;
      _slowTimer?.cancel();
      if (mounted) {
        setState(() {
          _loading = false;
          _slow = false;
        });
      }
    }
  }

  Future<void> _confirmRegenerate() async {
    if (_busy) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Regenerate the plan?', 'योजना फिर से बनाएँ?')),
        content: Text(
          tr(
            'This asks the AI again and can take up to 40 s.',
            'इससे AI से दोबारा योजना बनवाई जाती है, इसमें 40 सेकंड तक लग सकते हैं।',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(tr('Cancel', 'रद्द करें')),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(tr('Regenerate', 'फिर से बनाएँ')),
          ),
        ],
      ),
    );
    if (ok == true && mounted) _load(force: true);
  }

  /// Keeps pull-to-refresh working when the body is a spinner, an error or an empty state.
  Widget _scrollable(Widget child) => LayoutBuilder(
    builder: (context, c) => ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [SizedBox(height: c.maxHeight, child: child)],
    ),
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          tr(
            'Plan for today · ${widget.subject == 'numeracy' ? 'Maths' : 'Hindi'}',
            'आज की योजना · ${widget.subject == 'numeracy' ? 'गणित' : 'हिंदी'}',
          ),
        ),
        actions: [
          IconButton(
            tooltip: tr('Regenerate', 'फिर से बनाएँ'),
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _loading ? null : _confirmRegenerate,
          ),
          IconButton(
            tooltip: tr('Copy whole plan', 'पूरी योजना कॉपी करें'),
            icon: const Icon(Icons.copy_all_rounded),
            onPressed: _plan == null ? null : _copyAll,
          ),
          IconButton(
            tooltip: tr('Listen', 'सुनें'),
            icon: const Icon(Icons.volume_up_rounded),
            onPressed: _plan == null ? null : _speak,
          ),
        ],
      ),
      body: RefreshIndicator(
        // Pull-to-refresh only reloads the saved plan; the AI is asked again via Regenerate.
        onRefresh: () => _load(silent: _plan != null),
        child: _loading
            ? _scrollable(
                Loading(
                  label: _slow
                      ? tr(
                          'Server is waking up, this can take up to 40 seconds…',
                          'सर्वर जाग रहा है, इसमें 40 सेकंड तक लग सकते हैं…',
                        )
                      : tr(
                          'Building the plan for groups…',
                          'समूहों के लिए योजना बन रही है…',
                        ),
                ),
              )
            : _error != null
            ? _scrollable(
                Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      EmptyState(icon: Icons.wifi_off_rounded, text: _error!),
                      FilledButton.icon(
                        onPressed: _load,
                        icon: const Icon(Icons.refresh_rounded, size: 18),
                        label: Text(tr('Retry', 'फिर कोशिश करें')),
                      ),
                    ],
                  ),
                ),
              )
            : _plan == null
            ? _scrollable(
                EmptyState(
                  icon: Icons.event_busy_rounded,
                  text: tr('No plan yet.', 'अभी कोई योजना नहीं।'),
                ),
              )
            : _body(),
      ),
    );
  }

  Widget _body() {
    final p = _plan!;
    final groups = (p['groups'] as List).cast<Map<String, dynamic>>();
    final ai = p['generated_by'] == 'ai';
    final stale = p['offline'] == true || p['for_date'] != _localDay();
    final assess = p['assess_first'];
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      children: [
        if (stale)
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Ks.amberSoft,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              children: [
                const Icon(Icons.cloud_off_rounded, size: 18, color: Ks.amber),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    tr(
                      'Offline — showing the last saved plan (${p['for_date'] ?? ''}). It may be out of date.',
                      'ऑफलाइन — आख़िरी सहेजी योजना (${p['for_date'] ?? ''}) दिख रही है। यह पुरानी हो सकती है।',
                    ),
                    style: const TextStyle(fontSize: 13),
                  ),
                ),
              ],
            ),
          ),
        Row(
          children: [
            Icon(
              ai ? Icons.auto_awesome_rounded : Icons.rule_rounded,
              size: 18,
              color: Ks.muted,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                ai
                    ? tr(
                        'AI-generated — chosen from reviewed activities only',
                        'AI तैयार की गई — सबकी समीक्षा की गई गतिविधियों से चुनी गई',
                      )
                    : tr(
                        'Template plan (offline/fallback) — chosen from the library',
                        'टेम्पलेट योजना (ऑफलाइन/आरक्षित) — लाइब्रेरी से चुनी गई',
                      ),
                style: const TextStyle(color: Ks.muted, fontSize: 13),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (groups.isEmpty)
          EmptyState(
            icon: Icons.check_circle_outline,
            text: tr(
              'No group needs an activity today.',
              'आज किसी समूह के लिए गतिविधि ज़रूरी नहीं।',
            ),
          ),
        for (final g in groups) _groupPlanCard(p['id'] as int?, g),
        if (assess is Map &&
            ((assess['members'] as List?)?.isNotEmpty ?? false))
          _assessFirst(Map<String, dynamic>.from(assess)),
        if ((p['whole_class_note_hi'] as String?)?.isNotEmpty == true) ...[
          SectionTitle(tr('For the whole class', 'पूरी कक्षा के लिए')),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(p['whole_class_note_hi']),
            ),
          ),
        ],
        if ((p['today_observation_to_collect_hi'] as String?)?.isNotEmpty ==
            true) ...[
          const SizedBox(height: 10),
          Text(
            tr(
              'Check today: ${p['today_observation_to_collect_hi']}',
              'आज जाँचें: ${p['today_observation_to_collect_hi']}',
            ),
            style: const TextStyle(color: Ks.muted),
          ),
        ],
        const SizedBox(height: 90),
      ],
    );
  }

  Widget _groupPlanCard(int? planId, Map<String, dynamic> g) {
    final members = _members(g['members']);
    final act = g['activity'] as Map<String, dynamic>?;
    final nipun = (g['nipun_ref'] as String?)?.trim() ?? '';
    final doneId = '$planId:${g['key']}';
    final isDone = _done.contains(doneId);
    final isDoing = _doing.contains(doneId);
    final steps =
        (act?['steps_hi'] as List?)?.cast<String>() ??
        (g['generic_steps_hi'] as List?)?.cast<String>() ??
        [];
    final reassess = g['reassessment'] as Map<String, dynamic>?;
    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 30,
                  height: 30,
                  alignment: Alignment.center,
                  decoration: const BoxDecoration(
                    color: Ks.accent,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    '${g['order']}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    members.map((m) => m['first_name']).join(', '),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                Text(
                  tr('${g['time_min']} min', '${g['time_min']} मिनट'),
                  style: const TextStyle(color: Ks.muted),
                ),
                IconButton(
                  tooltip: tr('Listen to this group', 'इस समूह को सुनें'),
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.volume_up_rounded, size: 22),
                  onPressed: () => Speak.say(_groupSpeech(g)),
                ),
              ],
            ),
            if (nipun.isNotEmpty) ...[
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: Ks.accentSoft,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  'NIPUN $nipun',
                  style: const TextStyle(
                    color: Ks.accent,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
            const SizedBox(height: 8),
            if ((g['why_hi'] as String?)?.isNotEmpty == true)
              Text(
                g['why_hi'],
                style: const TextStyle(color: Ks.muted, fontSize: 15),
              ),
            const SizedBox(height: 10),
            if (act != null)
              Text(
                tr(
                  'Activity: ${act['title_hi']}',
                  'गतिविधि: ${act['title_hi']}',
                ),
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 16,
                ),
              ),
            if ((act?['materials_hi'] as String?)?.isNotEmpty == true)
              Text(
                tr(
                  'Materials: ${act!['materials_hi']}',
                  'सामग्री: ${act['materials_hi']}',
                ),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
            const SizedBox(height: 8),
            Text(
              g['teacher_script_hi'] ?? '',
              style: const TextStyle(fontSize: 16, height: 1.6),
            ),
            if (steps.isNotEmpty) ...[
              const SizedBox(height: 8),
              for (final s in steps)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('•  ', style: TextStyle(fontSize: 16)),
                      Expanded(
                        child: Text(s, style: const TextStyle(fontSize: 15)),
                      ),
                    ],
                  ),
                ),
            ],
            if ((act?['blackboard_hi'] as String?)?.isNotEmpty == true) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF233B36),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tr('On the board', 'बोर्ड पर'),
                      style: TextStyle(color: Color(0xFFA9CFC0), fontSize: 12),
                    ),
                    const SizedBox(height: 4),
                    SelectableText(
                      act!['blackboard_hi'],
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 17,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (reassess != null &&
                (reassess['ask_hi'] as String?)?.isNotEmpty == true) ...[
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Ks.accentSoft,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.fact_check_outlined,
                      size: 18,
                      color: Ks.accent,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        tr(
                          'Check again: ${reassess['ask_hi']}',
                          'फिर जाँचें: ${reassess['ask_hi']}',
                        ),
                        style: const TextStyle(fontSize: 15),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _copy(g),
                    icon: const Icon(Icons.copy_rounded, size: 18),
                    label: Text(tr('Copy', 'कॉपी')),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _checkNow(
                      checkpointId:
                          (g['checkpoint_id'] as String?)?.isNotEmpty == true
                          ? g['checkpoint_id'] as String
                          : g['key'] as String?,
                      childIds: _memberIds(g['members']),
                    ),
                    icon: const Icon(Icons.fact_check_outlined, size: 18),
                    label: Text(tr('Check now', 'अभी जाँचें')),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: isDone
                  ? Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 12,
                        horizontal: 12,
                      ),
                      decoration: BoxDecoration(
                        color: Ks.greenSoft,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(
                            Icons.check_circle_rounded,
                            size: 18,
                            color: Ks.green,
                          ),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              _queued.contains(doneId)
                                  ? tr(
                                      'Done ✓ — will sync when online. Now check again',
                                      'किया ✓ — नेट आने पर भेजा जाएगा। अब फिर जाँचें',
                                    )
                                  : tr(
                                      'Done ✓ — now check again',
                                      'किया ✓ — अब फिर जाँचें',
                                    ),
                              style: const TextStyle(
                                color: Ks.green,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ],
                      ),
                    )
                  : FilledButton.icon(
                      onPressed: planId == null || isDoing
                          ? null
                          : () => _markDone(planId, g['key'] as String),
                      icon: isDoing
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.done_all_rounded, size: 18),
                      label: Text(tr('Done', 'किया')),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _assessFirst(Map<String, dynamic> g) {
    final raw = (g['members'] as List?) ?? const [];
    // New shape: [{id, first_name}]; old shape: roll numbers (no names, no ids).
    final members = _members(raw);
    final count = raw.length;
    final names = members.map((m) => m['first_name']).join(', ');
    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.help_outline_rounded, color: Ks.muted),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        tr('Assessment pending', 'जाँच बाकी'),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        tr(
                          '$count children still need checking — add evidence.',
                          '$count बच्चों की जाँच बाकी — साक्ष्य जोड़ें।',
                        ),
                        style: const TextStyle(color: Ks.muted),
                      ),
                      if (names.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(names, style: const TextStyle(fontSize: 15)),
                      ],
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: () => _checkNow(childIds: _memberIds(raw)),
                icon: const Icon(Icons.touch_app_rounded, size: 18),
                label: Text(tr('Check in 3 taps', '3 टैप में जाँचें')),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Member entries as maps; skips legacy roll-number ints.
  List<Map<String, dynamic>> _members(Object? raw) => [
    for (final m in (raw as List? ?? const []))
      if (m is Map) Map<String, dynamic>.from(m),
  ];

  /// Child ids for CaptureSheet's preset, or null (= whole class) when the server sent no ids.
  List<int>? _memberIds(Object? raw) {
    final ids = [
      for (final m in _members(raw))
        if (m['id'] is num) (m['id'] as num).toInt(),
    ];
    return ids.isEmpty ? null : ids;
  }

  Future<void> _checkNow({String? checkpointId, List<int>? childIds}) async {
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
        presetChildIds: childIds,
      ),
    );
    if (changed == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr(
              'Evidence saved — regenerate the plan to update groups.',
              'साक्ष्य दर्ज — समूह अपडेट करने के लिए योजना फिर से बनाएँ।',
            ),
          ),
          action: SnackBarAction(
            label: tr('Regenerate', 'फिर से बनाएँ'),
            onPressed: _confirmRegenerate,
          ),
        ),
      );
    }
  }

  Future<void> _markDone(int planId, String key) async {
    final id = '$planId:$key';
    if (_done.contains(id) || _doing.contains(id)) return;
    setState(() => _doing.add(id));
    try {
      final r = await Api.i.postQueued(
        '/v1/plans/$planId/groups/${Uri.encodeComponent(key)}/done',
        {},
      );
      final queued = r is Map && r['queued'] == true;
      if (!mounted) return;
      setState(() {
        _done.add(id);
        if (queued) _queued.add(id);
      });
      _persistDone();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            queued
                ? tr(
                    'Saved on this phone — will send when you are online. Check again later.',
                    'फ़ोन में सहेजा — नेट आने पर भेजा जाएगा। बाद में फिर जाँचें।',
                  )
                : tr(
                    'Saved — now check again so groups update.',
                    'दर्ज — अब फिर जाँचें ताकि समूह अपडेट हों।',
                  ),
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr(
              'Could not save "Done" — tap again to retry. ($e)',
              '"किया" दर्ज नहीं हो सका — फिर से दबाएँ। ($e)',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _doing.remove(id));
    }
  }

  String _names(Map<String, dynamic> g) =>
      _members(g['members']).map((m) => m['first_name']).join(', ');

  /// Plain text of one group (names, why, activity, script, steps, board, re-check) for pasting
  /// into WhatsApp.
  String _groupText(Map<String, dynamic> g) {
    final act = g['activity'] as Map<String, dynamic>?;
    final steps =
        (act?['steps_hi'] as List?)?.cast<String>() ??
        (g['generic_steps_hi'] as List?)?.cast<String>() ??
        const <String>[];
    final nipun = (g['nipun_ref'] as String?)?.trim() ?? '';
    final ask = (g['reassessment'] as Map?)?['ask_hi'];
    final lines = <String>[
      '${tr('Group', 'समूह')} ${g['order'] ?? ''}: ${_names(g)} (${tr('${g['time_min']} min', '${g['time_min']} मिनट')})',
      if (nipun.isNotEmpty) 'NIPUN $nipun',
      if ((g['why_hi'] as String?)?.isNotEmpty == true) '${g['why_hi']}',
      if (act != null) '${tr('Activity', 'गतिविधि')}: ${act['title_hi']}',
      if ((act?['materials_hi'] as String?)?.isNotEmpty == true)
        '${tr('Materials', 'सामग्री')}: ${act!['materials_hi']}',
      if ((g['teacher_script_hi'] as String?)?.isNotEmpty == true)
        '${g['teacher_script_hi']}',
      for (final st in steps) '• $st',
      if ((act?['blackboard_hi'] as String?)?.isNotEmpty == true)
        '${tr('On the board', 'बोर्ड पर')}: ${act!['blackboard_hi']}',
      if (ask is String && ask.isNotEmpty)
        '${tr('Check again', 'फिर जाँचें')}: $ask',
    ];
    return lines.join('\n');
  }

  /// No share plugin is available (no new packages), so copy to the clipboard for pasting into
  /// WhatsApp.
  void _copyText(String text) {
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          tr(
            'Copied — paste it in WhatsApp',
            'कॉपी हो गया — WhatsApp में पेस्ट करें',
          ),
        ),
      ),
    );
  }

  void _copy(Map<String, dynamic> g) => _copyText(_groupText(g));

  void _copyAll() {
    final p = _plan!;
    final groups = (p['groups'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final note = p['whole_class_note_hi'];
    final text = [
      '${tr('Plan for today', 'आज की योजना')} · ${widget.className}',
      for (final g in groups) _groupText(g),
      if (note is String && note.isNotEmpty)
        '${tr('For the whole class', 'पूरी कक्षा के लिए')}: $note',
    ].join('\n\n');
    _copyText(text);
  }

  /// Hindi read-aloud of one group: name, time, why, activity, script, steps, re-check.
  String _groupSpeech(Map<String, dynamic> g) {
    final act = g['activity'] as Map<String, dynamic>?;
    final steps =
        (act?['steps_hi'] as List?)?.cast<String>() ??
        (g['generic_steps_hi'] as List?)?.cast<String>() ??
        const <String>[];
    final ask = (g['reassessment'] as Map?)?['ask_hi'];
    final parts = <String>[
      'समूह ${g['order'] ?? ''}: ${_names(g)}। ${g['time_min']} मिनट।',
      if ((g['why_hi'] as String?)?.isNotEmpty == true) '${g['why_hi']}',
      if (act != null) 'गतिविधि: ${act['title_hi']}।',
      if ((g['teacher_script_hi'] as String?)?.isNotEmpty == true)
        '${g['teacher_script_hi']}',
      for (var i = 0; i < steps.length; i++) 'चरण ${i + 1}: ${steps[i]}',
      if (ask is String && ask.isNotEmpty) 'फिर जाँचें: $ask',
    ];
    return parts.join(' ');
  }

  /// Reads the whole plan aloud (every group in full, then the whole-class note) with device TTS
  /// (flutter_tts on Android, browser speech on web; see tts.dart).
  void _speak() {
    final p = _plan!;
    final groups = (p['groups'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final note = p['whole_class_note_hi'];
    final text = [
      'आज ${groups.length} समूह हैं।',
      for (final g in groups) _groupSpeech(g),
      if (note is String && note.isNotEmpty) 'पूरी कक्षा के लिए: $note',
    ].join(' ');
    Speak.say(text);
  }
}
