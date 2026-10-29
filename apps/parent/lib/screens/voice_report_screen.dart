import 'package:flutter/material.dart';

import '../api.dart';
import '../api_voice.dart';
import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';

/// Report for one 30-minute voice session (contract `Report`), with the full transcript on demand.
class VoiceReportScreen extends StatefulWidget {
  const VoiceReportScreen({super.key, required this.sessionId, this.report});
  final Object sessionId;
  final Map<String, dynamic>? report;
  @override
  State<VoiceReportScreen> createState() => _VoiceReportScreenState();
}

class _VoiceReportScreenState extends State<VoiceReportScreen> {
  Map<String, dynamic>? _report;
  Future<Map<String, dynamic>>? _detail; // GET session: {session, report}
  bool _loading = false;
  bool _notReady = false;
  String? _error;
  bool _speaking = false;

  @override
  void initState() {
    super.initState();
    _report = widget.report;
    if (_report == null) _load();
  }

  @override
  void dispose() {
    Speak.stop();
    super.dispose();
  }

  Future<Map<String, dynamic>> _fetchDetail() {
    final f = Api.i.voiceSession(widget.sessionId);
    _detail = f;
    // A failed fetch must not stick: let the next expand try again.
    f.catchError((Object _) {
      if (identical(_detail, f)) _detail = null;
      return <String, dynamic>{};
    });
    return f;
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _notReady = false;
    });
    try {
      final d = await _fetchDetail();
      final r = (d['report'] as Map?)?.cast<String, dynamic>();
      if (!mounted) return;
      setState(() {
        _report = r;
        _notReady = r == null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = voiceErrorText(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ---- parsing helpers -------------------------------------------------------------------

  static int _int(Object? v) => (v as num?)?.round() ?? 0;

  static List<Map<String, dynamic>> _maps(Object? v) =>
      ((v as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();

  static List<String> _strings(Object? v) => ((v as List?) ?? const [])
      .where((e) => e != null)
      .map((e) => e.toString())
      .where((s) => s.trim().isNotEmpty)
      .toList();

  /// `{en, hi}` text in the UI language, falling back to the other.
  static String _bi(Map m, [String en = 'en', String hi = 'hi']) {
    final h = (m[hi] ?? '').toString();
    final e = (m[en] ?? '').toString();
    if (Lang.isHi) return h.isNotEmpty ? h : e;
    return e.isNotEmpty ? e : h;
  }

  /// Accuracy may arrive as 0..1 or 0..100.
  static int _pct(Object? v) {
    final a = (v as num?)?.toDouble() ?? 0;
    return (a <= 1 ? a * 100 : a).round().clamp(0, 100);
  }

  String _narrative(Map<String, dynamic> r) {
    final n = (r['narrative'] as Map?) ?? const {};
    final text = _bi(n, 'parent_en', 'parent_hi');
    if (text.trim().isNotEmpty) return text;
    final mins = _int(r['minutes']);
    final items = _int(r['items_attempted']);
    final acc = _pct(r['accuracy']);
    final stage = voiceStageLabel(r['highest_stage'] as String?);
    return trf(
      'Your child practised for {mins} minutes and tried {items} questions, getting {acc}% right. '
          'The highest level reached was "{stage}".',
      'आपके बच्चे ने {mins} मिनट अभ्यास किया और {items} सवाल किए, जिनमें {acc}% सही रहे। '
          'सबसे ऊँचा स्तर "{stage}" रहा।', {'mins': mins, 'items': items, 'acc': acc, 'stage': stage},
    );
  }

  Future<void> _toggleRead(String text) async {
    if (_speaking) {
      await Speak.stop();
      if (mounted) setState(() => _speaking = false);
      return;
    }
    setState(() => _speaking = true);
    await Speak.say(text, Lang.isHi ? 'hi' : 'en');
    if (mounted) setState(() => _speaking = false);
  }

  // ---- build -----------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Session report', 'सत्र रिपोर्ट'))),
      body: SafeArea(child: _body()),
    );
  }

  Widget _body() {
    if (_loading) {
      return Loading(
        label: tr('Preparing the report…', 'रिपोर्ट तैयार हो रही है…'),
      );
    }
    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              EmptyState(icon: Icons.wifi_off_rounded, text: _error!),
              FilledButton.icon(
                onPressed: _load,
                icon: const Icon(Icons.refresh_rounded),
                label: Text(tr('Try again', 'फिर से कोशिश करें')),
              ),
            ],
          ),
        ),
      );
    }
    final r = _report;
    if (r == null || _notReady) {
      return ListView(
        padding: const EdgeInsets.all(18),
        children: [
          EmptyState(
            icon: Icons.hourglass_top_rounded,
            text: tr(
              'The report is not ready yet — this session may still be in progress.',
              'रिपोर्ट अभी तैयार नहीं है — यह सत्र शायद अभी चल रहा है।',
            ),
          ),
          _transcriptTile(),
        ],
      );
    }
    final narrative = _narrative(r);
    final strengths = _maps(r['strengths']);
    final weaknesses = _maps(r['weaknesses']);
    final words = _strings(r['difficult_words']);
    final sounds = _maps(r['difficult_sounds']);
    final topics = _maps(r['topics_attention']);
    final mistakes = _maps(r['mistakes']);
    final stages = _maps(r['stages']);
    final wcpm = ((r['fluency'] as Map?)?['wcpm'] as num?)?.toDouble();
    final steps = _strings(
      ((r['next_steps'] as Map?) ?? const {})[Lang.isHi ? 'hi' : 'en'],
    );
    final stepsAlt = _strings(
      ((r['next_steps'] as Map?) ?? const {})[Lang.isHi ? 'en' : 'hi'],
    );

    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        _headline(r),
        const SizedBox(height: 10),
        _counts(r),
        const SizedBox(height: 18),
        // Narrative + read aloud
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Text('🦉', style: TextStyle(fontSize: 28)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        tr('What Saathi noticed', 'साथी ने क्या देखा'),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  narrative,
                  style: const TextStyle(fontSize: 17, height: 1.55),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () => _toggleRead(narrative),
                  icon: Icon(
                    _speaking ? Icons.stop_rounded : Icons.volume_up_rounded,
                    color: Ks.accent,
                  ),
                  label: Text(
                    _speaking
                        ? tr('Stop', 'रोकें')
                        : tr('Read aloud', 'सुनाएँ'),
                  ),
                ),
              ],
            ),
          ),
        ),
        if (stages.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(tr('Levels practised', 'किन स्तरों पर अभ्यास हुआ')),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(children: [for (final s in stages) _stageBar(s)]),
            ),
          ),
        ],
        if (strengths.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(tr('Strengths', 'खूबियाँ')),
          for (final s in strengths)
            _bullet(_bi(s), Icons.star_rounded, Ks.green),
        ],
        if (weaknesses.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(tr('Things to practise', 'किन चीज़ों का अभ्यास करें')),
          for (final s in weaknesses)
            _bullet(_bi(s), Icons.fitness_center_rounded, Ks.amber),
        ],
        if (words.isNotEmpty || sounds.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(
            tr('Difficult words and sounds', 'कठिन शब्द और ध्वनियाँ'),
          ),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final w in words) _chip(w, Ks.roseSoft, Ks.rose),
              for (final s in sounds)
                _chip(
                  [
                    (s['sound'] ?? '').toString(),
                    if ((s['confused_with'] ?? '').toString().isNotEmpty)
                      '→ ${s['confused_with']}',
                    if (_int(s['count']) > 1) '×${_int(s['count'])}',
                  ].join(' '),
                  Ks.amberSoft,
                  Ks.amber,
                ),
            ],
          ),
        ],
        if (topics.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(
            tr('Topics needing attention', 'जिन विषयों पर ध्यान चाहिए'),
          ),
          for (final t in topics)
            Card(
              margin: const EdgeInsets.only(bottom: 8),
              child: ListTile(
                leading: const Icon(Icons.flag_rounded, color: Ks.amber),
                title: Text(_bi(t, 'title_en', 'title_hi')),
                subtitle: _bi(t, 'reason_en', 'reason_hi').isEmpty
                    ? null
                    : Text(_bi(t, 'reason_en', 'reason_hi')),
              ),
            ),
        ],
        if (mistakes.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(tr('Where it was hard', 'कहाँ मुश्किल हुई')),
          for (final m in mistakes) _mistake(m),
        ],
        if (wcpm != null) ...[
          const SizedBox(height: 18),
          Card(
            child: ListTile(
              leading: const Icon(Icons.speed_rounded, color: Ks.accent),
              title: Text(
                trf(
                  'Reading speed: {wcpm} words a minute',
                  'पढ़ने की गति: {wcpm} शब्द प्रति मिनट', {'wcpm': wcpm.round()},
                ),
              ),
              subtitle: Text(
                trf(
                  'Paragraphs read: {paragraphs}',
                  'पढ़े गए अनुच्छेद: {paragraphs}', {'paragraphs': _int((r['fluency'] as Map?)?['paragraphs'])},
                ),
              ),
            ),
          ),
        ],
        if (steps.isNotEmpty || stepsAlt.isNotEmpty) ...[
          const SizedBox(height: 18),
          SectionTitle(tr('Next steps at home', 'घर पर आगे क्या करें')),
          for (final s in (steps.isNotEmpty ? steps : stepsAlt))
            _bullet(s, Icons.arrow_forward_rounded, Ks.accent),
        ],
        const SizedBox(height: 18),
        _transcriptTile(),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _headline(Map<String, dynamic> r) {
    Widget tile(String value, String label, IconData icon) => Expanded(
      child: Card(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
          child: Column(
            children: [
              Icon(icon, color: Ks.accent, size: 22),
              const SizedBox(height: 4),
              Text(
                value,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: Ks.ink,
                ),
              ),
              Text(
                label,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Ks.muted, fontSize: 13),
              ),
            ],
          ),
        ),
      ),
    );
    return Column(
      children: [
        Row(
          children: [
            tile(
              '${_int(r['minutes'])}',
              tr('minutes', 'मिनट'),
              Icons.timer_rounded,
            ),
            const SizedBox(width: 8),
            tile(
              '${_int(r['items_attempted'])}',
              tr('questions', 'सवाल'),
              Icons.quiz_rounded,
            ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            tile(
              '${_pct(r['accuracy'])}%',
              tr('correct', 'सही'),
              Icons.check_circle_rounded,
            ),
            const SizedBox(width: 8),
            tile(
              voiceStageLabel(r['highest_stage'] as String?),
              tr('highest level', 'सबसे ऊँचा स्तर'),
              Icons.trending_up_rounded,
            ),
          ],
        ),
      ],
    );
  }

  Widget _counts(Map<String, dynamic> r) {
    Widget c(String label, Object? v, Color fg, Color bg) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        '$label: ${_int(v)}',
        style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 14),
      ),
    );
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        c(
          tr('First try', 'पहली बार में'),
          r['first_try'],
          Ks.green,
          Ks.greenSoft,
        ),
        c(
          tr('After retry', 'दोबारा कोशिश में'),
          r['after_retry'],
          Ks.accent,
          Ks.accentSoft,
        ),
        c(tr('Not yet', 'अभी नहीं'), r['failed'], Ks.rose, Ks.roseSoft),
        c(tr('Skipped', 'छोड़े'), r['skipped'], Ks.muted, Ks.line),
      ],
    );
  }

  Widget _stageBar(Map<String, dynamic> s) {
    final attempted = _int(s['attempted']);
    final correct = _int(s['correct']);
    final frac = attempted == 0 ? 0.0 : (correct / attempted).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  voiceStageLabel(s['stage'] as String?),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                trf(
                  '{correct} of {attempted} right',
                  '{attempted} में से {correct} सही', {'correct': correct, 'attempted': attempted},
                ),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
            ],
          ),
          const SizedBox(height: 6),
          LinearProgressIndicator(
            value: frac,
            minHeight: 10,
            borderRadius: BorderRadius.circular(99),
            color: Ks.green,
            backgroundColor: Ks.accentSoft,
          ),
        ],
      ),
    );
  }

  Widget _bullet(String text, IconData icon, Color color) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 3),
          child: Icon(icon, size: 20, color: color),
        ),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: const TextStyle(fontSize: 16))),
      ],
    ),
  );

  Widget _chip(String text, Color bg, Color fg) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
    decoration: BoxDecoration(
      color: bg,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      text,
      style: TextStyle(color: fg, fontSize: 18, fontWeight: FontWeight.w700),
    ),
  );

  Widget _mistake(Map<String, dynamic> m) {
    final heard = (m['heard'] ?? '').toString();
    final errors = _strings(m['errors']);
    final attempts = _int(m['attempts']);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    (m['item'] ?? '').toString(),
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if ((m['stage'] as String?)?.isNotEmpty == true)
                  Text(
                    voiceStageLabel(m['stage'] as String?),
                    style: const TextStyle(color: Ks.muted, fontSize: 13),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              heard.isEmpty
                  ? tr(
                      'Saathi heard: (nothing clear)',
                      'साथी ने सुना: (कुछ साफ़ नहीं)',
                    )
                  : trf('Saathi heard: {heard}', 'साथी ने सुना: {heard}', {'heard': heard}),
              style: const TextStyle(color: Ks.rose, fontSize: 15),
            ),
            if (attempts > 0)
              Text(
                trf('Tries: {attempts}', 'कोशिशें: {attempts}', {'attempts': attempts}),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
            if (errors.isNotEmpty)
              Text(
                errors.join(' · '),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
          ],
        ),
      ),
    );
  }

  Widget _transcriptTile() => Card(
    child: ExpansionTile(
      shape: const Border(),
      collapsedShape: const Border(),
      leading: const Icon(Icons.forum_rounded, color: Ks.accent),
      title: Text(tr('Full conversation', 'पूरी बातचीत')),
      childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
      children: [_TranscriptLoader(load: () => _detail ?? _fetchDetail())],
    ),
  );
}

/// Loads the session once (when the tile is first expanded) and shows its transcript.
class _TranscriptLoader extends StatefulWidget {
  const _TranscriptLoader({required this.load});
  final Future<Map<String, dynamic>> Function() load;
  @override
  State<_TranscriptLoader> createState() => _TranscriptLoaderState();
}

class _TranscriptLoaderState extends State<_TranscriptLoader> {
  late Future<Map<String, dynamic>> _f = widget.load();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
      future: _f,
      builder: (_, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.all(16),
            child: Center(child: CircularProgressIndicator(color: Ks.accent)),
          );
        }
        if (snap.hasError) {
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(8),
                child: Text(
                  voiceErrorText(snap.error!),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Ks.muted),
                ),
              ),
              TextButton.icon(
                onPressed: () => setState(() { _f = widget.load(); }),
                icon: const Icon(Icons.refresh_rounded),
                label: Text(tr('Try again', 'फिर से कोशिश करें')),
              ),
            ],
          );
        }
        final session = (snap.data?['session'] as Map?) ?? const {};
        final lines = ((session['transcript'] as List?) ?? const [])
            .whereType<Map>()
            .map((e) => e.cast<String, dynamic>())
            .toList();
        if (lines.isEmpty) {
          return Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              tr('No conversation saved.', 'कोई बातचीत सहेजी नहीं गई।'),
              style: const TextStyle(color: Ks.muted),
            ),
          );
        }
        return Column(children: [for (final l in lines) _bubble(l)]);
      },
    );
  }

  static Color _wordColor(String? status) => switch (status) {
    'correct' => Ks.green,
    'close' => Ks.amber,
    'wrong' || 'missed' || 'extra' => Ks.rose,
    _ => Ks.ink,
  };

  Widget _bubble(Map<String, dynamic> l) {
    final tutor = l['role'] != 'child';
    final verdict = l['verdict'] as String?;
    final words = ((l['words'] as List?) ?? const []).whereType<Map>().toList();
    final bg = tutor
        ? Ks.accentSoft
        : switch (verdict) {
            'correct' => Ks.greenSoft,
            'close' => Ks.amberSoft,
            'wrong' => Ks.roseSoft,
            _ => Ks.card,
          };
    final text = (l['text'] ?? '').toString();
    final body = (!tutor && words.isNotEmpty)
        ? Text.rich(
            TextSpan(
              children: [
                for (final w in words)
                  TextSpan(
                    text:
                        '${(w['heard'] ?? '').toString().isNotEmpty ? w['heard'] : w['target'] ?? ''} ',
                    style: TextStyle(
                      color: _wordColor(w['status'] as String?),
                      fontWeight: FontWeight.w600,
                      decoration: w['status'] == 'missed'
                          ? TextDecoration.lineThrough
                          : null,
                    ),
                  ),
              ],
            ),
            style: const TextStyle(fontSize: 16),
          )
        : Text(text, style: const TextStyle(fontSize: 16, color: Ks.ink));
    return Align(
      alignment: tutor ? AlignmentDirectional.centerStart : AlignmentDirectional.centerEnd,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 320),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: Ks.line),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(tutor ? '🦉' : '🧒', style: const TextStyle(fontSize: 18)),
              const SizedBox(width: 8),
              Flexible(child: body),
            ],
          ),
        ),
      ),
    );
  }
}
