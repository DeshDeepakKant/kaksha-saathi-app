import 'package:flutter/material.dart';

import '../api.dart';
import '../api_voice.dart';
import '../l10n.dart';
import '../theme.dart';
import 'voice_report_screen.dart';

/// Past 30-minute voice sessions; tapping one opens its report.
class VoiceHistoryScreen extends StatefulWidget {
  const VoiceHistoryScreen({super.key});
  @override
  State<VoiceHistoryScreen> createState() => _VoiceHistoryScreenState();
}

class _VoiceHistoryScreenState extends State<VoiceHistoryScreen> {
  late Future<List<Map<String, dynamic>>> _f = Api.i.voiceSessions();

  Future<void> _refresh() async {
    final f = Api.i.voiceSessions();
    setState(() => _f = f);
    try {
      await f;
    } catch (_) {}
  }

  static int _pct(Object? v) {
    final a = (v as num?)?.toDouble() ?? 0;
    return (a <= 1 ? a * 100 : a).round().clamp(0, 100);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Voice sessions', 'आवाज़ वाले सत्र'))),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (_, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Loading();
          }
          final Widget child;
          if (snap.hasError) {
            child = EmptyState(
              icon: Icons.cloud_off_rounded,
              text: voiceErrorText(snap.error!),
            );
          } else if ((snap.data ?? const []).isEmpty) {
            child = EmptyState(
              icon: Icons.record_voice_over_rounded,
              text: tr(
                'No voice sessions yet. Start one from the home screen!',
                'अभी कोई आवाज़ वाला सत्र नहीं हुआ। होम स्क्रीन से शुरू करें!',
              ),
            );
          } else {
            final rows = snap.data!;
            return RefreshIndicator(
              onRefresh: _refresh,
              child: ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: rows.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (_, i) => _row(rows[i]),
              ),
            );
          }
          // Keep pull-to-refresh available on the empty / error states too.
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [const SizedBox(height: 80), child],
            ),
          );
        },
      ),
    );
  }

  Widget _row(Map<String, dynamic> s) {
    final at = DateTime.tryParse(s['started_at'] as String? ?? '')?.toLocal();
    final when = at == null
        ? ''
        : '${at.day}/${at.month} · ${at.hour.toString().padLeft(2, '0')}:'
              '${at.minute.toString().padLeft(2, '0')}';
    final active = s['status'] == 'active';
    final lang = s['lang'] == 'en' ? 'English' : 'हिंदी';
    final minutes = (s['minutes'] as num?)?.round() ?? 0;
    final items = (s['items'] as num?)?.round() ?? 0;
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: s['id'] == null
            ? null
            : () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) =>
                      VoiceReportScreen(sessionId: s['id'] as Object),
                ),
              ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.record_voice_over_rounded,
                    color: Ks.accent,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    when,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(width: 8),
                  Text(lang, style: const TextStyle(color: Ks.muted)),
                  const Spacer(),
                  if (active)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: Ks.amberSoft,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        tr('In progress', 'चल रहा है'),
                        style: const TextStyle(
                          color: Ks.amber,
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                        ),
                      ),
                    )
                  else
                    const Icon(Icons.chevron_right_rounded, color: Ks.muted),
                ],
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 14,
                runSpacing: 4,
                children: [
                  Text(tr('$minutes min', '$minutes मिनट')),
                  Text(tr('$items questions', '$items सवाल')),
                  Text(
                    tr(
                      '${_pct(s['accuracy'])}% right',
                      '${_pct(s['accuracy'])}% सही',
                    ),
                  ),
                  if ((s['highest_stage'] as String?)?.isNotEmpty == true)
                    Text(
                      voiceStageLabel(s['highest_stage'] as String?),
                      style: const TextStyle(
                        color: Ks.accent,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
