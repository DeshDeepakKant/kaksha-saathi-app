import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import '../widgets/capture_sheet.dart';

// ---- shared helpers (also used by widgets/voice_sessions_card.dart)

/// Friendly name of a reading-ladder stage (`letter` … `reading`, see voice_session_contract.md).
String voiceStageLabel(String? stage) => switch (stage) {
  'letter' => tr('Letters', 'अक्षर'),
  'word_build' => tr('Building words', 'शब्द बनाना'),
  'word_read' => tr('Reading words', 'शब्द पढ़ना'),
  'sentence_build' => tr('Making sentences', 'वाक्य बनाना'),
  'reading' => tr('Reading', 'पढ़ना'),
  _ => tr('Not reached', 'अभी नहीं'),
};

/// Subject a voice session belongs to: English sessions are 'english', everything else Hindi.
String voiceSubject(String? lang) => lang == 'en' ? 'english' : 'literacy';

String voiceLangLabel(String? lang) =>
    lang == 'en' ? tr('English', 'अंग्रेज़ी') : tr('Hindi', 'हिंदी');

/// Accuracy as a whole percent. The server sends 0..1; a value above 1 is taken as a percent.
int? voiceAccuracyPct(dynamic v) {
  if (v is! num) return null;
  final pct = v > 1 ? v : v * 100;
  return pct.round().clamp(0, 100).toInt();
}

/// Session length for display ("<1" for very short sessions).
String voiceMinutes(dynamic v) {
  if (v is! num) return '0';
  if (v > 0 && v < 1) return '<1';
  return '${v.round()}';
}

/// "29/10 · 17:05" from an ISO timestamp (local time).
String voiceWhen(dynamic iso) {
  final at = iso is String ? DateTime.tryParse(iso)?.toLocal() : null;
  if (at == null) return '';
  String two(int n) => n.toString().padLeft(2, '0');
  return '${at.day}/${at.month} · ${two(at.hour)}:${two(at.minute)}';
}

/// Green / amber / rose by accuracy; always shown next to the number, never alone.
Color voiceAccuracyColor(int pct) =>
    pct >= 75 ? Ks.green : (pct >= 40 ? Ks.amber : Ks.rose);

/// Thin rounded bar (0..1).
class VoiceBar extends StatelessWidget {
  const VoiceBar({super.key, required this.value, required this.color});
  final double value;
  final Color color;
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(999),
    child: LinearProgressIndicator(
      value: value.clamp(0.0, 1.0),
      minHeight: 6,
      color: color,
      backgroundColor: Ks.line,
    ),
  );
}

Map<String, dynamic> _m(dynamic v) =>
    v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};

List<Map<String, dynamic>> _ms(dynamic v) => v is List
    ? v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

List<String> _strs(dynamic v) => v is List
    ? v.map((e) => '$e'.trim()).where((s) => s.isNotEmpty).toList()
    : <String>[];

int _n(dynamic v) => v is num ? v.toInt() : 0;

/// `{en, hi}` (or `{.._en, .._hi}`) text in the selected language, falling back to the other one.
String _bi(dynamic m, {String en = 'en', String hi = 'hi'}) {
  final map = _m(m);
  final e = (map[en] ?? '').toString().trim();
  final h = (map[hi] ?? '').toString().trim();
  if (Lang.isHi) return h.isNotEmpty ? h : e;
  return e.isNotEmpty ? e : h;
}

/// Teacher view of one 30-minute voice session the child had with Saathi at home:
/// headline numbers, the teacher narrative, topics to check in class, difficult sounds and words,
/// exact mistakes, per-stage results, fluency, next steps and the full transcript.
/// Data: `GET /v1/voice_sessions/{id}` -> `{session, report}` (docs/voice_session_contract.md).
class VoiceReportScreen extends StatefulWidget {
  const VoiceReportScreen({
    super.key,
    required this.sessionId,
    required this.childId,
    required this.childName,
    required this.classId,
    this.onEvidenceSaved,
  });
  final String sessionId;
  final int childId;
  final String childName;
  final int classId;

  /// Called after a "Check in class" capture saved something (the profile reloads).
  final VoidCallback? onEvidenceSaved;
  @override
  State<VoiceReportScreen> createState() => _VoiceReportScreenState();
}

class _VoiceReportScreenState extends State<VoiceReportScreen> {
  late Future<dynamic> _future;
  String? _lang; // language of the loaded session; English sessions are checked as 'english'

  @override
  void initState() {
    super.initState();
    _future = _fetch();
  }

  Future<dynamic> _fetch() =>
      Api.i.get('/v1/voice_sessions/${widget.sessionId}');

  void _reload() => setState(() { _future = _fetch(); });

  Future<void> _checkInClass(String checkpointId) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) => CaptureSheet(
        classId: widget.classId,
        subject: voiceSubject(_lang),
        presetCheckpointId: checkpointId,
        presetChildIds: [widget.childId],
      ),
    );
    if (changed == true) widget.onEvidenceSaved?.call();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          trf(
            '{childName}: voice session',
            '{childName}: आवाज़ सत्र', {'childName': widget.childName},
          ),
        ),
        actions: [
          IconButton(
            tooltip: tr('Refresh', 'ताज़ा करें'),
            icon: const Icon(Icons.refresh_rounded),
            onPressed: _reload,
          ),
        ],
      ),
      body: FutureBuilder<dynamic>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Loading();
          }
          if (snap.hasError || snap.data is! Map) {
            return Center(
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    EmptyState(
                      icon: Icons.error_outline,
                      text: trf(
                        'Could not load this session.\n{v}',
                        'यह सत्र नहीं खुल पाया।\n{v}', {'v': snap.error ?? ''},
                      ),
                    ),
                    FilledButton.icon(
                      onPressed: _reload,
                      icon: const Icon(Icons.refresh_rounded),
                      label: Text(tr('Retry', 'दोबारा कोशिश करें')),
                    ),
                  ],
                ),
              ),
            );
          }
          final data = _m(snap.data);
          return RefreshIndicator(
            color: Ks.accent,
            onRefresh: () async {
              _reload();
              await _future.catchError((_) => null);
            },
            child: _body(
              _m(data['session']),
              data['report'] is Map ? _m(data['report']) : null,
              offline: data['offline'] == true,
            ),
          );
        },
      ),
    );
  }

  Widget _body(
    Map<String, dynamic> session,
    Map<String, dynamic>? report, {
    required bool offline,
  }) {
    final lang = (report?['lang'] ?? session['lang']) as String?;
    _lang = lang;
    final transcript = _ms(session['transcript']);
    final subtitle = [
      voiceWhen(session['started_at']),
      voiceLangLabel(lang),
      if (session['status'] == 'active') tr('In progress', 'चल रहा है'),
    ].where((s) => s.isNotEmpty).join(' · ');
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Text(subtitle, style: const TextStyle(color: Ks.muted)),
        if (offline) ...[
          const SizedBox(height: 8),
          _note(
            Icons.cloud_off_rounded,
            tr(
              'Offline: showing the last saved copy.',
              'ऑफ़लाइन: पिछली सहेजी जानकारी दिख रही है।',
            ),
          ),
        ],
        const SizedBox(height: 12),
        if (report == null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                tr(
                  'No report yet. The session is still going on or was not finished.',
                  'अभी रिपोर्ट नहीं है। सत्र चल रहा है या पूरा नहीं हुआ।',
                ),
              ),
            ),
          )
        else
          ..._reportSections(report),
        _transcript(transcript),
      ],
    );
  }

  Widget _note(IconData icon, String text) => Row(
    children: [
      Icon(icon, size: 18, color: Ks.muted),
      const SizedBox(width: 6),
      Expanded(
        child: Text(
          text,
          style: const TextStyle(color: Ks.muted, fontSize: 14),
        ),
      ),
    ],
  );

  List<Widget> _reportSections(Map<String, dynamic> r) {
    final pct = voiceAccuracyPct(r['accuracy']);
    final narrative = _m(r['narrative']);
    final teacherText = _bi(narrative, en: 'teacher_en', hi: 'teacher_hi');
    final topics = _ms(r['topics_attention']);
    final sounds = _ms(r['difficult_sounds']);
    final words = _strs(r['difficult_words']);
    final mistakes = _ms(r['mistakes']);
    final stages = _ms(r['stages']).where((s) => _n(s['attempted']) > 0);
    final fluency = _m(r['fluency']);
    final wcpm = fluency['wcpm'];
    final strengths = _ms(r['strengths']).map(_bi).where((s) => s.isNotEmpty);
    final weaknesses = _ms(r['weaknesses']).map(_bi).where((s) => s.isNotEmpty);
    final steps = _m(r['next_steps']);
    var nextSteps = _strs(Lang.isHi ? steps['hi'] : steps['en']);
    if (nextSteps.isEmpty) {
      nextSteps = _strs(Lang.isHi ? steps['en'] : steps['hi']);
    }

    return [
      // ---- headline numbers
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          _stat(voiceMinutes(r['minutes']), tr('minutes', 'मिनट')),
          _stat('${_n(r['items_attempted'])}', tr('items tried', 'प्रश्न')),
          _stat(
            pct == null ? '–' : '$pct%',
            tr('accuracy', 'सटीकता'),
            color: pct == null ? null : voiceAccuracyColor(pct),
          ),
          _stat(
            voiceStageLabel(r['highest_stage'] as String?),
            tr('highest stage', 'सबसे ऊँचा स्तर'),
            small: true,
          ),
        ],
      ),
      const SizedBox(height: 8),
      Text(
        trf(
          'First try: {first_try} · after hints: {after_retry} · '
              'not yet: {failed} · skipped: {skipped}',
          'पहली बार में: {first_try} · संकेत के बाद: {after_retry} · '
              'अभी नहीं: {failed} · छोड़े: {skipped}', {'first_try': _n(r['first_try']), 'after_retry': _n(r['after_retry']), 'failed': _n(r['failed']), 'skipped': _n(r['skipped'])},
        ),
        style: const TextStyle(color: Ks.muted, fontSize: 14),
      ),
      const SizedBox(height: 14),

      // ---- narrative
      if (teacherText.isNotEmpty) ...[
        SectionTitle(tr('Summary for you', 'आपके लिए सार')),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(teacherText),
                const SizedBox(height: 6),
                Text(
                  r['narrative_status'] == 'ai'
                      ? tr(
                          'Written by AI from the scores. The scores are checked by code.',
                          'अंकों से AI ने लिखा। अंक कोड से जाँचे गए हैं।',
                        )
                      : tr(
                          'Summary made from the scores.',
                          'अंकों से बना सार।',
                        ),
                  style: const TextStyle(color: Ks.muted, fontSize: 12),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
      ],
      if (strengths.isNotEmpty || weaknesses.isNotEmpty) ...[
        for (final s in strengths)
          _bullet(Icons.check_circle_rounded, Ks.green, s),
        for (final w in weaknesses) _bullet(Icons.error_rounded, Ks.amber, w),
        const SizedBox(height: 14),
      ],

      // ---- topics to check in class
      if (topics.isNotEmpty) ...[
        SectionTitle(tr('Topics needing attention', 'जिन सबक पर ध्यान दें')),
        for (final t in topics) _topicCard(t),
        const SizedBox(height: 4),
      ],

      // ---- sounds and words
      if (sounds.isNotEmpty) ...[
        SectionTitle(tr('Difficult sounds', 'कठिन ध्वनियाँ')),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [for (final s in sounds) _soundChip(s)],
        ),
        const SizedBox(height: 14),
      ],
      if (words.isNotEmpty) ...[
        SectionTitle(tr('Difficult words', 'कठिन शब्द')),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final w in words) _chip(w, Ks.rose, Ks.roseSoft, fontSize: 17),
          ],
        ),
        const SizedBox(height: 14),
      ],

      // ---- mistakes
      if (mistakes.isNotEmpty) ...[
        SectionTitle(tr('Mistakes', 'गलतियाँ')),
        _mistakesTable(mistakes),
        const SizedBox(height: 14),
      ],

      // ---- per stage
      if (stages.isNotEmpty) ...[
        SectionTitle(tr('By stage', 'स्तर अनुसार')),
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
            child: Column(children: [for (final s in stages) _stageRow(s)]),
          ),
        ),
        const SizedBox(height: 14),
      ],

      // ---- fluency
      if (wcpm is num) ...[
        SectionTitle(tr('Reading fluency', 'पढ़ने की गति')),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Text(
              trf(
                '{wcpm} correct words per minute '
                    '({paragraphs} paragraph(s) read)',
                '{wcpm} सही शब्द प्रति मिनट '
                    '({paragraphs} अनुच्छेद पढ़े)', {'wcpm': wcpm.round(), 'paragraphs': _n(fluency['paragraphs'])},
              ),
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
            ),
          ),
        ),
        const SizedBox(height: 14),
      ],

      // ---- next steps
      if (nextSteps.isNotEmpty) ...[
        SectionTitle(tr('Next steps', 'आगे क्या करें')),
        for (final s in nextSteps)
          _bullet(Icons.arrow_forward_rounded, Ks.accent, s),
        const SizedBox(height: 14),
      ],
    ];
  }

  Widget _stat(
    String value,
    String label, {
    Color? color,
    bool small = false,
  }) => Container(
    constraints: const BoxConstraints(minWidth: 96),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: Ks.card,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: Ks.line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value,
          style: TextStyle(
            fontSize: small ? 16 : 22,
            fontWeight: FontWeight.w700,
            color: color ?? Ks.ink,
          ),
        ),
        Text(label, style: const TextStyle(color: Ks.muted, fontSize: 13)),
      ],
    ),
  );

  Widget _bullet(IconData icon, Color color, String text) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 3),
          child: Icon(icon, size: 18, color: color),
        ),
        const SizedBox(width: 8),
        Expanded(child: Text(text)),
      ],
    ),
  );

  Widget _chip(
    String text,
    Color fg,
    Color bg, {
    double fontSize = 15,
    IconData? icon,
  }) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: bg,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 15, color: fg),
          const SizedBox(width: 4),
        ],
        Text(
          text,
          style: TextStyle(
            color: fg,
            fontSize: fontSize,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );

  Widget _topicCard(Map<String, dynamic> t) {
    final id = (t['checkpoint_id'] as String?)?.trim() ?? '';
    final title = cpTitle(t);
    final reason = _bi(t, en: 'reason_en', hi: 'reason_hi');
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title.isNotEmpty ? title : id,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
            if (reason.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  reason,
                  style: const TextStyle(color: Ks.muted, fontSize: 14),
                ),
              ),
            // CaptureSheet also handles lessons outside the class roadmap, so this is always offered.
            if (id.isNotEmpty) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: () => _checkInClass(id),
                icon: const Icon(Icons.add_task_rounded, size: 18),
                label: Text(tr('Check in class', 'कक्षा में जाँचें')),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _soundChip(Map<String, dynamic> s) {
    final sound = '${s['sound'] ?? ''}'.trim();
    final with_ = '${s['confused_with'] ?? ''}'.trim();
    final count = _n(s['count']);
    final text = [
      with_.isEmpty ? sound : '$sound → $with_',
      if (count > 1) '×$count',
    ].join('  ');
    return Semantics(
      label: trf(
        '{sound} said as {with_}, {count} times',
        '{sound} को {with_} बोला, {count} बार', {'sound': sound, 'with_': with_, 'count': count},
      ),
      excludeSemantics: true,
      child: _chip(text, Ks.amber, Ks.amberSoft, fontSize: 17),
    );
  }

  Widget _mistakesTable(List<Map<String, dynamic>> mistakes) {
    const head = TextStyle(
      color: Ks.muted,
      fontSize: 13,
      fontWeight: FontWeight.w600,
    );
    Widget cell(String text, {TextStyle? style}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
      child: Text(text, style: style ?? const TextStyle(fontSize: 15)),
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
        child: Table(
          columnWidths: const {
            0: FlexColumnWidth(3),
            1: FlexColumnWidth(3),
            2: IntrinsicColumnWidth(),
            3: FlexColumnWidth(3),
          },
          defaultVerticalAlignment: TableCellVerticalAlignment.top,
          children: [
            TableRow(
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: Ks.line)),
              ),
              children: [
                cell(tr('Item', 'प्रश्न'), style: head),
                cell(tr('Heard', 'सुना'), style: head),
                cell(tr('Tries', 'प्रयास'), style: head),
                cell(tr('Errors', 'चूक'), style: head),
              ],
            ),
            for (final m in mistakes)
              TableRow(
                children: [
                  cell('${m['item'] ?? ''}'),
                  cell(
                    '${m['heard'] ?? ''}'.trim().isEmpty
                        ? '—'
                        : '${m['heard']}',
                  ),
                  cell('${_n(m['attempts'])}'),
                  cell(
                    _strs(m['errors']).join(', '),
                    style: const TextStyle(fontSize: 14, color: Ks.rose),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _stageRow(Map<String, dynamic> s) {
    final attempted = _n(s['attempted']);
    final correct = _n(s['correct']);
    final failed = _n(s['failed']);
    final rest = (attempted - correct - failed).clamp(0, attempted);
    final label = trf(
      '{correct} of {attempted} right · {failed} not yet',
      '{attempted} में से {correct} सही · {failed} अभी नहीं', {'correct': correct, 'attempted': attempted, 'failed': failed},
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Semantics(
        label: '${voiceStageLabel(s['stage'] as String?)}: $label',
        excludeSemantics: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 10,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  voiceStageLabel(s['stage'] as String?),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                Text(
                  label,
                  style: const TextStyle(color: Ks.muted, fontSize: 13),
                ),
              ],
            ),
            const SizedBox(height: 4),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: SizedBox(
                height: 8,
                child: Row(
                  children: [
                    if (correct > 0)
                      Expanded(
                        flex: correct,
                        child: Container(color: Ks.green),
                      ),
                    if (rest > 0)
                      Expanded(
                        flex: rest,
                        child: Container(color: Ks.line),
                      ),
                    if (failed > 0)
                      Expanded(
                        flex: failed,
                        child: Container(color: Ks.rose),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ---- transcript

  Widget _transcript(List<Map<String, dynamic>> lines) {
    if (lines.isEmpty) return const SizedBox.shrink();
    return Card(
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        shape: const Border(),
        collapsedShape: const Border(),
        leading: const Icon(Icons.forum_rounded, color: Ks.accent),
        title: Text(
          tr('Full transcript', 'पूरी बातचीत'),
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          trf('{linesCount} lines', '{linesCount} पंक्तियाँ', {'linesCount': lines.length}),
          style: const TextStyle(color: Ks.muted, fontSize: 13),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _legend(),
          const SizedBox(height: 10),
          for (final l in lines) _line(l),
        ],
      ),
    );
  }

  Widget _legend() => Wrap(
    spacing: 6,
    runSpacing: 6,
    children: [
      for (final st in const ['correct', 'close', 'wrong', 'missed'])
        _chip(
          _wordStatusLabel(st),
          _wordFg(st),
          _wordBg(st),
          fontSize: 12,
          icon: _wordIcon(st),
        ),
    ],
  );

  String _wordStatusLabel(String st) => switch (st) {
    'correct' => tr('Right', 'सही'),
    'close' => tr('Almost', 'लगभग'),
    'wrong' => tr('Wrong', 'गलत'),
    'missed' => tr('Missed', 'छूटा'),
    'extra' => tr('Extra', 'अतिरिक्त'),
    _ => st,
  };

  Color _wordFg(String st) => switch (st) {
    'correct' => Ks.green,
    'close' => Ks.amber,
    'wrong' || 'missed' => Ks.rose,
    _ => Ks.muted,
  };

  Color _wordBg(String st) => switch (st) {
    'correct' => Ks.greenSoft,
    'close' => Ks.amberSoft,
    'wrong' || 'missed' => Ks.roseSoft,
    _ => const Color(0xFFF1EEE7),
  };

  IconData _wordIcon(String st) => switch (st) {
    'correct' => Icons.check_rounded,
    'close' => Icons.more_horiz_rounded,
    'wrong' => Icons.close_rounded,
    'missed' => Icons.remove_rounded,
    _ => Icons.add_rounded,
  };

  /// One spoken word: what was heard (or the missed target, struck through), with an icon for the
  /// status and the target word when it differs.
  Widget _word(Map<String, dynamic> w) {
    final st = '${w['status'] ?? ''}';
    final target = '${w['target'] ?? ''}'.trim();
    final heard = '${w['heard'] ?? ''}'.trim();
    final missed = st == 'missed' || heard.isEmpty;
    final shown = missed ? target : heard;
    final showTarget =
        !missed && st != 'correct' && target.isNotEmpty && target != heard;
    final fg = _wordFg(st);
    return Semantics(
      label: [
        shown,
        _wordStatusLabel(st),
        if (showTarget) trf('should be {target}', 'सही: {target}', {'target': target}),
      ].join(', '),
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: _wordBg(st),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(_wordIcon(st), size: 14, color: fg),
            const SizedBox(width: 3),
            Text(
              shown,
              style: TextStyle(
                color: fg,
                fontSize: 16,
                fontWeight: FontWeight.w600,
                decoration: missed ? TextDecoration.lineThrough : null,
                decorationColor: fg,
              ),
            ),
            if (showTarget)
              Text(
                ' → $target',
                style: const TextStyle(color: Ks.ink, fontSize: 13),
              ),
          ],
        ),
      ),
    );
  }

  String _lineTime(dynamic at) {
    if (at is num) {
      final s = at.round();
      return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
    }
    final t = at is String ? DateTime.tryParse(at)?.toLocal() : null;
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(t.hour)}:${two(t.minute)}';
  }

  Widget _line(Map<String, dynamic> l) {
    final child = l['role'] == 'child';
    final words = _ms(l['words']);
    final text = '${l['text'] ?? ''}'.trim();
    final verdict = l['verdict'] as String?;
    final time = _lineTime(l['at']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: child ? Ks.card : Ks.accentSoft,
          borderRadius: BorderRadius.circular(12),
          border: child ? Border.all(color: Ks.line) : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    child ? widget.childName : 'Saathi',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: child ? Ks.ink : Ks.accent,
                    ),
                  ),
                ),
                if (child && verdict != null && verdict.isNotEmpty)
                  _verdictChip(verdict),
                if (time.isNotEmpty) ...[
                  const SizedBox(width: 6),
                  Text(
                    time,
                    style: const TextStyle(color: Ks.muted, fontSize: 12),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 4),
            if (child && words.isNotEmpty)
              Wrap(
                spacing: 4,
                runSpacing: 4,
                children: [for (final w in words) _word(w)],
              )
            else
              Text(
                text.isEmpty
                    ? (child ? tr('(nothing heard)', '(कुछ नहीं सुना)') : '')
                    : text,
                style: TextStyle(
                  fontSize: 15,
                  color: text.isEmpty ? Ks.muted : Ks.ink,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _verdictChip(String v) {
    final (label, st) = switch (v) {
      'correct' => (tr('Right', 'सही'), 'correct'),
      'close' => (tr('Almost', 'लगभग'), 'close'),
      'wrong' => (tr('Not yet', 'अभी नहीं'), 'wrong'),
      'silent' => (tr('Silent', 'चुप'), 'extra'),
      'skipped' => (tr('Skipped', 'छोड़ा'), 'extra'),
      _ => (v, 'extra'),
    };
    return _chip(
      label,
      _wordFg(st),
      _wordBg(st),
      fontSize: 12,
      icon: v == 'silent' ? Icons.mic_off_rounded : _wordIcon(st),
    );
  }
}
