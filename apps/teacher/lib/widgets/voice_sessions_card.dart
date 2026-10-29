import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../screens/voice_report_screen.dart';
import '../theme.dart';

/// "Voice sessions with Saathi (home)" on the child profile: the child's recent 30-minute voice
/// sessions (date, language, minutes, items, accuracy, highest stage); tap one for the report.
/// Data: `GET /v1/children/{id}/voice_sessions`. Hides itself when the call fails (for example a
/// server without the voice feature), so the profile never shows an error for it.
class VoiceSessionsCard extends StatefulWidget {
  const VoiceSessionsCard({
    super.key,
    required this.childId,
    required this.childName,
    required this.classId,
    this.reloadToken = 0,
    this.onEvidenceSaved,
  });
  final int childId;
  final String childName;
  final int classId;

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

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(VoiceSessionsCard old) {
    super.didUpdateWidget(old);
    if (old.reloadToken != widget.reloadToken ||
        old.childId != widget.childId) {
      _load();
    }
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
          list.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
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
    if (_hidden || sessions == null) return const SizedBox.shrink();
    final visible = _showAll ? sessions : sessions.take(_shown).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(
          tr(
            'Voice sessions with Saathi (home)',
            'साथी के साथ आवाज़ सत्र (घर)',
          ),
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
                          tr(
                            'No voice sessions yet',
                            'अभी कोई आवाज़ सत्र नहीं',
                          ),
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
                                  'सभी दिखाएँ ({sessionsCount})', {'sessionsCount': sessions.length},
                                ),
                        ),
                      ),
                  ],
                ),
        ),
      ],
    );
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
          '{highest_stage}', {'minutes': voiceMinutes(s['minutes']), 'items': items, 'highest_stage': voiceStageLabel(s['highest_stage'] as String?)},
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
