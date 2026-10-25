import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../tts.dart';

import '../api.dart';
import '../theme.dart';
import '../l10n.dart';

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
  Map<String, dynamic>? _plan;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool force = false}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      Map<String, dynamic> p;
      if (!force) {
        final latest = await Api.i.latestPlan(
          widget.classId,
          widget.subject,
        ) as Map<String, dynamic>;
        final today = DateTime.now().toIso8601String().substring(0, 10);
        if (latest['exists'] == true && latest['for_date'] == today) {
          p = latest;
        } else {
          p = await Api.i.plan(
            widget.classId,
            widget.subject,
          ) as Map<String, dynamic>;
        }
      } else {
        p = await Api.i.plan(
          widget.classId,
          widget.subject,
          force: true,
        ) as Map<String, dynamic>;
      }
      setState(() => _plan = p);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _loading = false);
    }
  }

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
            onPressed: _loading ? null : () => _load(force: true),
          ),
          IconButton(
            tooltip: tr('Listen', 'सुनें'),
            icon: const Icon(Icons.volume_up_rounded),
            onPressed: () => _speak(),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _load(force: true),
        child: _loading
            ? Loading(
                label: tr(
                  'Building the plan for groups…',
                  'समूहों के लिए योजना बन रही है…',
                ),
              )
            : _error != null
            ? EmptyState(icon: Icons.wifi_off_rounded, text: _error!)
            : _body(),
      ),
    );
  }

  Widget _body() {
    final p = _plan!;
    final groups = (p['groups'] as List).cast<Map<String, dynamic>>();
    final ai = p['generated_by'] == 'ai';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
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
        if ((p['assess_first'] as Map?)?['members'] != null)
          _assessFirst(p['assess_first'] as Map<String, dynamic>),
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
    final members = (g['members'] as List).cast<Map<String, dynamic>>();
    final act = g['activity'] as Map<String, dynamic>?;
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
              ],
            ),
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
                  'सामग्री: ${act!['materials_hi']}',
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
                  child: FilledButton.icon(
                    onPressed: planId == null
                        ? null
                        : () => _markDone(planId, g['key'] as String),
                    icon: const Icon(Icons.done_all_rounded, size: 18),
                    label: Text(tr('Done', 'किया')),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _assessFirst(Map<String, dynamic> g) {
    final members = (g['members'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            const Icon(Icons.help_outline_rounded, color: Ks.muted),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                tr(
                  '${members.length} children still need checking — add evidence.',
                  '${members.length} बच्चों की जाँच बाकी — साक्ष्य जोड़ें।',
                ),
                style: const TextStyle(color: Ks.muted),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _markDone(int planId, String key) async {
    try {
      await Api.i.markDone(planId, key);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr(
              'Saved — check again later so groups update.',
              'दर्ज — बाद में फिर जाँचें ताकि समूह अपडेट हों।',
            ),
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  void _copy(Map<String, dynamic> g) {
    final members = (g['members'] as List)
        .cast<Map<String, dynamic>>()
        .map((m) => m['first_name'])
        .join(', ');
    final text =
        '${tr('Group', 'समूह')}: $members\n${g['teacher_script_hi'] ?? ''}\n${(g['reassessment'] as Map?)?['ask_hi'] ?? ''}';
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          tr('Copied — send on WhatsApp', 'कॉपी हो गया — WhatsApp पर भेजें'),
        ),
      ),
    );
  }

  void _speak() {
    final p = _plan!;
    final groups = (p['groups'] as List).cast<Map<String, dynamic>>();
    final parts = <String>[];
    for (final g in groups) {
      final names = (g['members'] as List)
          .map((m) => m['first_name'])
          .join(', ');
      parts.add('गतिविधि ${g['order']}: $names। ${g['time_min']} मिनट।');
    }
    final text = 'आज ${groups.length} समूह हैं। ${parts.join(' ')}';
    // Works on web via the injected speech bridge; on Android the OS "Listen" button in the
    // app bar is replaced by device TTS through the same channel (see web/speech.js).
    Speak.say(text);
  }
}
