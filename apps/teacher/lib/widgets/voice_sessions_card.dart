import 'package:flutter/material.dart';

import '../api.dart';
import '../api_admin.dart' show friendlyError;
import '../l10n.dart';
import '../screens/voice_report_screen.dart';
import '../theme.dart';

/// Home voice practice on the child profile (Hindi and English tabs):
/// - "Home practice focus": the stage the next session will practise and why, the teacher's
///   override (Change / Back to automatic) and the focus trend of recent sessions.
///   Data: `GET|PUT|DELETE /v1/children/{id}/home_focus` (docs/voice_focus_contract.md §3).
/// - "Voice sessions with Saathi (home)": the child's recent 30-minute sessions in this subject
///   (date, language, minutes, items, accuracy, highest stage); tap one for the report.
///   Data: `GET /v1/children/{id}/voice_sessions`, filtered by each row's `lang`.
/// Each part hides itself when its call fails (for example a server without the feature), so the
/// profile never shows an error for it. Focus changes need the network (not queued).
class VoiceSessionsCard extends StatefulWidget {
  const VoiceSessionsCard({
    super.key,
    required this.childId,
    required this.childName,
    required this.classId,
    this.subject = 'literacy',
    this.reloadToken = 0,
    this.onEvidenceSaved,
  });
  final int childId;
  final String childName;
  final int classId;

  /// 'literacy' (Hindi sessions) or 'english' (sessions with `lang == 'en'`).
  final String subject;

  /// Change this to fetch again (the profile bumps it on every reload).
  final int reloadToken;

  /// Passed to the report screen: called after a "Check in class" capture saved something.
  final VoidCallback? onEvidenceSaved;
  @override
  State<VoiceSessionsCard> createState() => _VoiceSessionsCardState();
}

class _VoiceSessionsCardState extends State<VoiceSessionsCard> {
  static const _shown = 5;
  List<Map<String, dynamic>>? _sessions;
  bool _hidden = false;
  bool _showAll = false;
  int _seq = 0;

  Map<String, dynamic>?
  _focus; // GET home_focus body; null = not loaded or not available
  int _focusSeq = 0;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
    _loadFocus();
  }

  @override
  void didUpdateWidget(VoiceSessionsCard old) {
    super.didUpdateWidget(old);
    if (old.reloadToken != widget.reloadToken ||
        old.childId != widget.childId ||
        old.subject != widget.subject) {
      if (old.childId != widget.childId || old.subject != widget.subject) {
        _focus = null;
      }
      _load();
      _loadFocus();
    }
  }

  String get _focusPath =>
      '/v1/children/${widget.childId}/home_focus?subject=${widget.subject}';

  Future<void> _loadFocus() async {
    final seq = ++_focusSeq;
    try {
      final r = await Api.i.get(_focusPath);
      if (!mounted || seq != _focusSeq) return;
      // The offline copy may predate a change just saved: use it only when nothing is shown.
      if (r is Map && r['offline'] == true && _focus != null) return;
      if (r is Map && r['plan'] is Map) {
        setState(() => _focus = r.cast<String, dynamic>());
      }
    } catch (_) {
      // Old server (404) or offline with no cached copy: keep what is shown, else hide the header.
    }
  }

  /// PUT (stage chosen) or DELETE (back to automatic). Needs the network; a failure is a snackbar.
  Future<void> _saveFocus(
    ({String stage, String note, int days})? choice,
  ) async {
    setState(() => _saving = true);
    try {
      final r = choice == null
          ? await Api.i.delete(_focusPath)
          : await Api.i.putJson('/v1/children/${widget.childId}/home_focus', {
              'subject': widget.subject,
              'stage': choice.stage,
              if (choice.note.isNotEmpty) 'note': choice.note,
              'days': choice.days,
            });
      if (!mounted) return;
      if (r is Map && r['plan'] is Map) {
        setState(() => _focus = r.cast<String, dynamic>());
      }
      _snack(
        choice == null
            ? tr('Back to automatic focus', 'फ़ोकस फिर से अपने-आप तय होगा')
            : tr(
                'Home practice focus saved',
                'घर के अभ्यास का फ़ोकस सहेजा गया',
              ),
      );
      await _loadFocus(); // refresh (and the offline copy)
    } catch (e) {
      if (mounted) _snack(friendlyError(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _snack(String text) {
    final m = ScaffoldMessenger.of(context);
    m.hideCurrentSnackBar();
    m.showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _change() async {
    final plan = _mp(_focus?['plan']);
    final override = _mp(_focus?['override']);
    final choice =
        await showModalBottomSheet<({String stage, String note, int days})>(
          context: context,
          isScrollControlled: true,
          backgroundColor: Ks.paper,
          shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
          ),
          builder: (_) => _FocusSheet(
            childName: widget.childName,
            stage: (override['stage'] ?? plan['focus_stage']) as String?,
            note: override['note'] as String? ?? '',
          ),
        );
    if (choice != null && mounted) await _saveFocus(choice);
  }

  Future<void> _load() async {
    final seq = ++_seq;
    try {
      final r = await Api.i.get(
        '/v1/children/${widget.childId}/voice_sessions',
      );
      final list = r is List
          ? r
          : (r is Map && r['sessions'] is List ? r['sessions'] as List : null);
      if (!mounted || seq != _seq) return;
      if (list == null) {
        setState(() => _hidden = _sessions == null);
        return;
      }
      final sessions =
          list
              .whereType<Map>()
              .map((e) => e.cast<String, dynamic>())
              .where(
                (s) => voiceSubject(s['lang'] as String?) == widget.subject,
              )
              .toList()
            ..sort(
              (a, b) => '${b['started_at'] ?? ''}'.compareTo(
                '${a['started_at'] ?? ''}',
              ),
            );
      setState(() {
        _sessions = sessions;
        _hidden = false;
      });
    } catch (_) {
      // 404 (route not deployed yet), offline with no cached copy, ... : keep the last list if any
      if (!mounted || seq != _seq) return;
      if (_sessions == null) setState(() => _hidden = true);
    }
  }

  void _open(Map<String, dynamic> s) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => VoiceReportScreen(
          sessionId: '${s['id']}',
          childId: widget.childId,
          childName: widget.childName,
          classId: widget.classId,
          onEvidenceSaved: widget.onEvidenceSaved,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sessions = _sessions;
    final focus = _focus;
    final showSessions = !_hidden && sessions != null;
    if (!showSessions && focus == null) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (focus != null) ..._focusPart(focus),
        if (showSessions) ..._sessionsPart(sessions),
      ],
    );
  }

  // ---- home practice focus

  List<Widget> _focusPart(Map<String, dynamic> focus) {
    final plan = _mp(focus['plan']);
    final override = _mp(focus['override']);
    final overridden = override.isNotEmpty;
    final stage = (plan['focus_stage'] ?? override['stage']) as String?;
    final source = overridden
        ? ''
        : voiceFocusSourceLabel(plan['source'] as String?);
    final reason = pick(plan, 'reason').trim();
    final note = '${override['note'] ?? ''}'.trim();
    final until = voiceDay(override['until']);
    final history = _list(focus['history'])
        .where(
          (h) =>
              h['lang'] == null ||
              voiceSubject(h['lang'] as String?) == widget.subject,
        )
        .toList();
    return [
      SectionTitle(tr('Home practice focus', 'घर के अभ्यास का फ़ोकस')),
      Card(
        margin: const EdgeInsets.only(bottom: 14),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 2),
                    child: Icon(
                      Icons.center_focus_strong_rounded,
                      color: Ks.accent,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          tr('Next session', 'अगला सत्र'),
                          style: const TextStyle(color: Ks.muted, fontSize: 13),
                        ),
                        Text(
                          voiceStageLabel(stage),
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        if (overridden)
                          Text(
                            until.isEmpty
                                ? tr('Set by you', 'आपने तय किया')
                                : trf(
                                    'Set by you until {date}',
                                    '{date} तक आपने तय किया',
                                    {'date': until},
                                  ),
                            style: const TextStyle(
                              color: Ks.accent,
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        if (overridden && note.isNotEmpty)
                          Text('“$note”', style: const TextStyle(fontSize: 14)),
                        if (!overridden &&
                            (source.isNotEmpty || reason.isNotEmpty))
                          Text(
                            [
                              source,
                              reason,
                            ].where((t) => t.isNotEmpty).join(': '),
                            style: const TextStyle(
                              color: Ks.muted,
                              fontSize: 14,
                            ),
                          ),
                        if (plan['placement'] == true)
                          Text(
                            tr(
                              'Saathi will first find the right level (about 2 minutes).',
                              'साथी पहले सही स्तर पता करेगा (लगभग 2 मिनट)।',
                            ),
                            style: const TextStyle(
                              color: Ks.muted,
                              fontSize: 14,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 4,
                children: [
                  TextButton.icon(
                    onPressed: _saving ? null : _change,
                    icon: const Icon(Icons.tune_rounded, size: 18),
                    label: Text(tr('Change', 'बदलें')),
                  ),
                  if (overridden)
                    TextButton.icon(
                      onPressed: _saving ? null : () => _saveFocus(null),
                      icon: const Icon(Icons.autorenew_rounded, size: 18),
                      label: Text(tr('Back to automatic', 'फिर से अपने-आप')),
                    ),
                  if (_saving)
                    const Padding(
                      padding: EdgeInsets.all(12),
                      child: SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    ),
                ],
              ),
              if (history.isNotEmpty) ...[
                const Divider(height: 12, color: Ks.line),
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 2),
                  child: Text(
                    tr('Recent sessions', 'हाल के सत्र'),
                    style: const TextStyle(
                      color: Ks.muted,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                for (final h in history.take(8)) _trendRow(h),
              ],
            ],
          ),
        ),
      ),
    ];
  }

  /// One history row: date · focus stage (ladder dots) · accuracy · ✓ mastered → next stage.
  Widget _trendRow(Map<String, dynamic> h) {
    final stage = h['focus_stage'] as String?;
    final next = h['next_focus_stage'] as String?;
    final pct = voiceAccuracyPct(h['focus_accuracy']);
    final mastered = h['mastered'] == true;
    final moves = next != null && next.isNotEmpty && next != stage;
    final id = h['session_id'];
    final row = Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          SizedBox(
            width: 64,
            child: Text(
              voiceDay(h['date']),
              style: const TextStyle(color: Ks.muted, fontSize: 13),
            ),
          ),
          _LadderDots(stage: stage),
          const SizedBox(width: 8),
          Expanded(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: voiceStageLabel(stage),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  if (moves)
                    TextSpan(
                      text: ' → ${voiceStageLabel(next)}',
                      style: const TextStyle(color: Ks.muted),
                    ),
                ],
              ),
              style: const TextStyle(fontSize: 14),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (pct != null)
            Padding(
              padding: const EdgeInsets.only(left: 6),
              child: Text(
                '$pct%',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: voiceAccuracyColor(pct),
                ),
              ),
            ),
          SizedBox(
            width: 24,
            child: mastered
                ? Tooltip(
                    message: tr('Mastered', 'पक्का हुआ'),
                    child: const Icon(
                      Icons.check_circle_rounded,
                      size: 18,
                      color: Ks.green,
                    ),
                  )
                : null,
          ),
        ],
      ),
    );
    if (id == null) return row;
    return InkWell(onTap: () => _open({'id': id}), child: row);
  }

  // ---- session list

  List<Widget> _sessionsPart(List<Map<String, dynamic>> sessions) {
    final visible = _showAll ? sessions : sessions.take(_shown).toList();
    return [
      SectionTitle(
        tr('Voice sessions with Saathi (home)', 'साथी के साथ आवाज़ सत्र (घर)'),
      ),
      Card(
        clipBehavior: Clip.antiAlias,
        margin: const EdgeInsets.only(bottom: 14),
        child: sessions.isEmpty
            ? Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    const Icon(Icons.mic_none_rounded, color: Ks.muted),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        tr('No voice sessions yet', 'अभी कोई आवाज़ सत्र नहीं'),
                        style: const TextStyle(color: Ks.muted),
                      ),
                    ),
                  ],
                ),
              )
            : Column(
                children: [
                  for (var i = 0; i < visible.length; i++) ...[
                    if (i > 0) const Divider(height: 1, color: Ks.line),
                    _row(visible[i]),
                  ],
                  if (sessions.length > _shown)
                    TextButton(
                      onPressed: () => setState(() => _showAll = !_showAll),
                      child: Text(
                        _showAll
                            ? tr('Show fewer', 'कम दिखाएँ')
                            : trf(
                                'Show all ({sessionsCount})',
                                'सभी दिखाएँ ({sessionsCount})',
                                {'sessionsCount': sessions.length},
                              ),
                      ),
                    ),
                ],
              ),
      ),
    ];
  }

  Widget _row(Map<String, dynamic> s) {
    final pct = voiceAccuracyPct(s['accuracy']);
    final items = s['items'] is num ? (s['items'] as num).toInt() : 0;
    final active = s['status'] == 'active';
    final top = [
      voiceWhen(s['started_at']),
      voiceLangLabel(s['lang'] as String?),
      if (active) tr('In progress', 'चल रहा है'),
    ].where((t) => t.isNotEmpty).join(' · ');
    final detail = trf(
      '{minutes} min · {items} items · '
          '{highest_stage}',
      '{minutes} मिनट · {items} प्रश्न · '
          '{highest_stage}',
      {
        'minutes': voiceMinutes(s['minutes']),
        'items': items,
        'highest_stage': voiceStageLabel(s['highest_stage'] as String?),
      },
    );
    return InkWell(
      onTap: () => _open(s),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(14, 12, 8, 12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    top,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text(
                    detail,
                    style: const TextStyle(color: Ks.muted, fontSize: 14),
                  ),
                  if (pct != null) ...[
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Expanded(
                          child: VoiceBar(
                            value: pct / 100,
                            color: voiceAccuracyColor(pct),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          trf('{pct}% right', '{pct}% सही', {'pct': pct}),
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: voiceAccuracyColor(pct),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: Ks.muted),
          ],
        ),
      ),
    );
  }
}

Map<String, dynamic> _mp(dynamic v) =>
    v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};

List<Map<String, dynamic>> _list(dynamic v) => v is List
    ? v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

/// Five small steps, filled up to [stage]: shows at a glance how far up the ladder a session was.
class _LadderDots extends StatelessWidget {
  const _LadderDots({required this.stage});
  final String? stage;
  @override
  Widget build(BuildContext context) {
    final at = voiceStages.indexOf(stage ?? '');
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        for (var i = 0; i < voiceStages.length; i++)
          Container(
            width: 5,
            height: 5.0 + i * 2.5,
            margin: const EdgeInsets.only(right: 2),
            decoration: BoxDecoration(
              color: i <= at ? Ks.accent : Ks.line,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
      ],
    );
  }
}

/// "Change" sheet: one of the five stages, an optional note and 7 or 14 days.
/// Pops `(stage, note, days)`, or null when closed.
class _FocusSheet extends StatefulWidget {
  const _FocusSheet({required this.childName, this.stage, this.note = ''});
  final String childName;
  final String? stage;
  final String note;
  @override
  State<_FocusSheet> createState() => _FocusSheetState();
}

class _FocusSheetState extends State<_FocusSheet> {
  late String? _stage = voiceStages.contains(widget.stage)
      ? widget.stage
      : null;
  late final _note = TextEditingController(text: widget.note);
  int _days = 7;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final stage = _stage;
    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                trf(
                  'Home practice focus for {name}',
                  '{name} के घर के अभ्यास का फ़ोकस',
                  {'name': widget.childName},
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text(
                tr(
                  'Saathi will practise this stage at home until the date below.',
                  'नीचे दी गई तारीख तक साथी घर पर यही स्तर अभ्यास कराएगा।',
                ),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
              const SizedBox(height: 12),
              RadioGroup<String>(
                groupValue: stage,
                onChanged: (v) => setState(() => _stage = v),
                child: Column(
                  children: [
                    for (final s in voiceStages)
                      RadioListTile<String>(
                        value: s,
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        activeColor: Ks.accent,
                        title: Text(
                          voiceStageLabel(s),
                          style: const TextStyle(fontSize: 16),
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _note,
                maxLength: 200,
                maxLines: 2,
                minLines: 1,
                decoration: InputDecoration(
                  labelText: tr('Note (optional)', 'नोट (वैकल्पिक)'),
                  hintText: tr(
                    'e.g. Practise letter sounds this week',
                    'जैसे: इस हफ़्ते अक्षरों की ध्वनि का अभ्यास',
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                tr('For how long', 'कितने दिन'),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                children: [
                  for (final d in const [7, 14])
                    ChoiceChip(
                      label: Text(
                        trf('{days} days', '{days} दिन', {'days': d}),
                      ),
                      selected: _days == d,
                      onSelected: (_) => setState(() => _days = d),
                    ),
                ],
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: stage == null
                    ? null
                    : () => Navigator.of(context).pop((
                        stage: stage,
                        note: _note.text.trim(),
                        days: _days,
                      )),
                child: Text(tr('Save', 'सहेजें')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
