import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'gate_screen.dart';
import 'history_screen.dart';
import 'session_screen.dart';
import '../l10n.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  Map<String, dynamic>? _child;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      await Api.i.fetchChild();
      setState(() => _child = Api.i.profile);
    } on ApiError catch (e) {
      if (e.status == 401) {
        await Api.i.logout();
        if (mounted) {
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(builder: (_) => const GateScreen()),
            (_) => false,
          );
        }
        return;
      }
      setState(() => _error = e.toString());
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    Api.i.fetchPack().catchError((_) {});
    Api.i.fetchHistory();
  }

  Future<void> _start() async {
    try {
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => SessionScreen(offline: Api.i.offline),
        ),
      );
    } catch (_) {}
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final profile = _child;
    final c = (profile?['child'] as Map?)?.cast<String, dynamic>();
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Kaksha Saathi', 'कक्षा साथी')),
        actions: [
          TextButton(
            onPressed: () => Lang.set(Lang.isHi ? 'en' : 'hi'),
            child: Text(Lang.isHi ? 'EN' : 'हिं'),
          ),
          IconButton(
            icon: const Icon(Icons.history_rounded),
            tooltip: tr('Past practice', 'पिछले अभ्यास'),
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => const HistoryScreen())),
          ),
          IconButton(
            icon: const Icon(Icons.logout_rounded),
            onPressed: () async {
              await Api.i.logout();
              if (!context.mounted) return;
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const GateScreen()),
                (_) => false,
              );
            },
          ),
        ],
      ),
      body: _loading
          ? const Loading()
          : _error != null
          ? EmptyState(icon: Icons.wifi_off_rounded, text: _error!)
          : ListView(
              padding: const EdgeInsets.all(18),
              children: [
                if (profile != null && c != null) ...[
                  Row(
                    children: [
                      CircleAvatar(
                        radius: 30,
                        backgroundColor: Ks.accentSoft,
                        child: Text(
                          '${c['roll_no']}',
                          style: const TextStyle(
                            color: Ks.accent,
                            fontSize: 22,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              tr(
                                'Hello, ${c['first_name']}!',
                                'नमस्ते, ${c['first_name']}!',
                              ),
                              style: Theme.of(context).textTheme.titleLarge
                                  ?.copyWith(fontSize: 26),
                            ),
                            Text(
                              c['class'] ?? '',
                              style: const TextStyle(color: Ks.muted),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  if (((profile['streak'] as num?) ?? 0) > 0)
                    Container(
                      margin: const EdgeInsets.only(bottom: 14),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Ks.amberSoft,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.local_fire_department_rounded,
                            color: Ks.amber,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            tr(
                              '${profile['streak']}-day practice streak — well done!',
                              '${profile['streak']} दिन लगातार अभ्यास — शाबाश!',
                            ),
                            style: const TextStyle(
                              color: Ks.amber,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  SectionTitle(
                    tr('What to practise today', 'आज क्या अभ्यास करें'),
                  ),
                  for (final f
                      in ((profile['focus'] as List?) ?? const [])
                          .cast<Map<String, dynamic>>())
                    Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: ListTile(
                        leading: Icon(
                          Icons.headphones_rounded,
                          color: Ks.statusColor[f['status']] ?? Ks.accent,
                        ),
                        title: Text(
                          cpTitle(f),
                          style: const TextStyle(fontSize: 16),
                        ),
                        subtitle: Text(
                          pick(f, 'label'),
                          style: TextStyle(
                            color: Ks.statusColor[f['status']] ?? Ks.muted,
                          ),
                        ),
                      ),
                    ),
                  const SizedBox(height: 18),
                  _startCard(),
                  const SizedBox(height: 12),
                  Text(
                    tr(
                      'About 25–30 minutes · keep the mic on · you can pause anytime',
                      'लगभग 25–30 मिनट · माइक चालू रखें · बीच में रुक सकते हैं',
                    ),
                    style: TextStyle(color: Ks.muted, fontSize: 13),
                  ),
                ],
              ],
            ),
    );
  }

  Widget _startCard() {
    final off = Api.i.offline;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Icon(Icons.record_voice_over_rounded, size: 54, color: Ks.accent),
            const SizedBox(height: 8),
            Text(
              tr('Practise with Saathi', 'साथी के साथ अभ्यास'),
              style: Theme.of(context).textTheme.titleMedium
                  ?.copyWith(fontSize: 22),
            ),
            const SizedBox(height: 4),
            Text(
              tr(
                'Press the big mic button and answer by speaking.',
                'बड़े माइक बटन को दबाएँ और बोलकर बताएँ।',
              ),
              textAlign: TextAlign.center,
              style: TextStyle(color: Ks.muted),
            ),
            if (off)
              Padding(
                padding: EdgeInsets.only(top: 6),
                child: Text(
                  tr(
                    'No internet — tap practice will run',
                    'इंटरनेट नहीं — टैप अभ्यास चलेगा',
                  ),
                  style: TextStyle(color: Ks.amber, fontSize: 13),
                ),
              ),
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: _start,
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(66),
              ),
              icon: const Icon(Icons.play_arrow_rounded, size: 28),
              label: Text(
                tr('Start practice', 'अभ्यास शुरू करें'),
                style: TextStyle(fontSize: 20),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
