import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'login_screen.dart';
import '../l10n.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Map<String, dynamic>? _ai;
  Map<String, dynamic>? _content;

  @override
  void initState() {
    super.initState();
    Api.i
        .aiActivity()
        .then((v) => setState(() => _ai = (v as Map).cast<String, dynamic>()))
        .catchError((_) => {});
    Api.i
        .contentStatus()
        .then(
          (v) => setState(() => _content = (v as Map).cast<String, dynamic>()),
        )
        .catchError((_) => {});
  }

  @override
  Widget build(BuildContext context) {
    final me = Api.i.me;
    final caps = (me?['capabilities'] as Map?) ?? {};
    return Scaffold(
      appBar: AppBar(title: Text(tr('Settings', 'सेटिंग्स'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    me?['name'] ?? '',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    me?['school'] ?? '',
                    style: const TextStyle(color: Ks.muted),
                  ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    children: [
                      _cap('AI', caps['ai'] == true),
                      _cap(
                        tr('Voice recognition', 'आवाज़ पहचान'),
                        caps['asr'] == true,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tr('Language', 'भाषा'),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    tr(
                      'App text and lesson names. Classroom activities stay in Hindi.',
                      'ऐप का टेक्स्ट और सबक के नाम। कक्षा की गतिविधियाँ हिंदी में रहती हैं।',
                    ),
                    style: const TextStyle(color: Ks.muted),
                  ),
                  const SizedBox(height: 12),
                  const LangToggle(),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          if (_ai != null) _aiCard(_ai!),
          const SizedBox(height: 12),
          if (_content != null) _contentCard(_content!),
          const SizedBox(height: 12),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: Icon(Icons.privacy_tip_outlined),
                  title: Text(tr('Children\'s data', 'बच्चों का डेटा')),
                  subtitle: Text(
                    tr(
                      'First name and roll number only. Photos are deleted after 7 days. Voice is not saved.',
                      'सिर्फ़ पहला नाम और रोल नंबर। फ़ोटो 7 दिन में हटती हैं। आवाज़ सहेजी नहीं जाती।',
                    ),
                  ),
                ),
                ListTile(
                  leading: Icon(Icons.download_outlined),
                  title: Text(tr('Profile export', 'प्रोफ़ाइल निर्यात')),
                  subtitle: Text(
                    tr(
                      'Download a child\'s profile as JSON (API: /v1/children/{id}/export)',
                      'बच्चे की प्रोफ़ाइल से JSON डाउनलोड (API: /v1/children/{id}/export)',
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: () async {
              await Api.i.logout();
              if (!context.mounted) return;
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const LoginScreen()),
                (_) => false,
              );
            },
            icon: const Icon(Icons.logout_rounded),
            label: Text(tr('Log out', 'लॉगआउट')),
          ),
        ],
      ),
    );
  }

  Widget _cap(String label, bool on) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: on ? Ks.greenSoft : Ks.roseSoft,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      '$label: ${on ? tr('On', 'चालू') : tr('Off (offline mode)', 'बंद (ऑफ़लाइन मोड)')}',
      style: TextStyle(fontSize: 13, color: on ? Ks.green : Ks.rose),
    ),
  );

  Widget _aiCard(Map<String, dynamic> ai) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('AI suggestion ledger', 'AI सुझावों का हिसाब'),
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
          ),
          const SizedBox(height: 8),
          _kv(
            tr('Total suggestions (proposals)', 'कुल सुझाव (प्रस्ताव)'),
            ai['proposals'],
          ),
          _kv(
            tr('Confirmed by teacher', 'शिक्षक ने पुष्टि की'),
            ai['confirmed'],
          ),
          _kv(tr('Rejected', 'रद्द किए'), ai['rejected']),
          _kv(
            tr('Offline / rule-based', 'ऑफ़लाइन/नियम से बने'),
            ai['degraded'],
          ),
          _kv(tr('AI calls', 'AI कॉल'), ai['ai_calls']),
          _kv(tr('Spent today (₹)', 'आज खर्च (₹)'), ai['cost_inr']),
          _kv(
            tr('Budget left (₹)', 'बचा बजट (₹)'),
            Api.i.me?['budget_left_inr'],
          ),
        ],
      ),
    ),
  );

  Widget _contentCard(Map<String, dynamic> c) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('Content', 'सामग्री'),
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
          ),
          const SizedBox(height: 8),
          _kv(tr('Checkpoints', 'जाँच बिंदु (checkpoints)'), c['checkpoints']),
          _kv(
            tr('Activities (reviewed)', 'गतिविधियाँ (जाँची गईं)'),
            '${c['activities_reviewed']} / ${c['activities']}',
          ),
          _kv(
            tr('Home practice questions', 'घर के अभ्यास प्रश्न'),
            c['practice_items'],
          ),
          _kv(tr('Ready check questions', 'तैयार जाँच प्रश्न'), c['probes']),
        ],
      ),
    ),
  );

  Widget _kv(String k, Object? v) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      children: [
        Expanded(
          child: Text(k, style: const TextStyle(color: Ks.muted)),
        ),
        Text(
          '${v ?? '—'}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ],
    ),
  );
}
