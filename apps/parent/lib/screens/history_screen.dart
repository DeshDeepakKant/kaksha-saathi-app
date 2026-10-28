import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../l10n.dart';
import 'voice_history_screen.dart';

class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});
  @override
  Widget build(BuildContext context) {
    final h = Api.i.history;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Previous practice', 'पिछला अभ्यास'))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: Card(
              child: ListTile(
                minVerticalPadding: 14,
                leading: const Icon(
                  Icons.record_voice_over_rounded,
                  color: Ks.accent,
                  size: 30,
                ),
                title: Text(
                  tr('30-minute voice sessions', '30 मिनट के आवाज़ वाले सत्र'),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                subtitle: Text(
                  tr(
                    'Reports from talking with Saathi',
                    'साथी से बातचीत की रिपोर्ट',
                  ),
                ),
                trailing: const Icon(Icons.chevron_right_rounded),
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const VoiceHistoryScreen()),
                ),
              ),
            ),
          ),
          Expanded(child: _practiceList(h)),
        ],
      ),
    );
  }

  Widget _practiceList(List<dynamic> h) {
    return h.isEmpty
        ? EmptyState(
            icon: Icons.history_toggle_off_rounded,
            text: tr(
              'No practice yet. Start for the first time!',
              'अभी कोई अभ्यास नहीं हुआ। पहली बार शुरू करें!',
            ),
          )
        : ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: h.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (_, i) {
              final s = (h[i] as Map).cast<String, dynamic>();
              final at = DateTime.tryParse(s['started_at'] as String? ?? '')
                  ?.toLocal();
              final when = at == null ? '' : '${at.day}/${at.month}';
              return Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(
                            Icons.headphones_rounded,
                            color: Ks.accent,
                            size: 20,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            when,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          const Spacer(),
                          Text(
                            tr(
                              '${s['activities']} activities',
                              '${s['activities']} गतिविधियाँ',
                            ),
                            style: const TextStyle(color: Ks.muted),
                          ),
                        ],
                      ),
                      if ((s['summary_hi'] as String?)?.isNotEmpty == true)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            s['summary_hi'],
                            style: const TextStyle(fontSize: 15),
                          ),
                        ),
                    ],
                  ),
                ),
              );
            },
          );
  }
}
