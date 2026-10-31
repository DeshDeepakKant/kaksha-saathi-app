import 'package:flutter/material.dart';

import '../api.dart';
import '../api_insights.dart';
import '../theme.dart';
import '../tts.dart';
import '../widgets/insight_cards.dart';
import 'gate_screen.dart';
import 'journey_screen.dart';
import 'settings_screen.dart';
import 'voice_history_screen.dart';
import 'voice_session_screen.dart';
import 'weekly_screen.dart';
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

  // Parent insights (docs/parent_insights_contract.md). Each loads on its own after the profile;
  // a failed or empty call just hides its card.
  Map<String, dynamic>? _week;
  bool _weekLoading = false;
  List<Map<String, dynamic>> _moments = const [];
  List<Map<String, dynamic>> _tips = const [];
  Set<String> _dismissed = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    Speak.stop();
    super.dispose();
  }

  /// Profile first (the full-screen spinner only shows before the first one), then the insight
  /// cards in parallel. Pull-to-refresh waits for all of them.
  Future<void> _load() async {
    setState(() {
      _loading = _child == null;
      _error = null;
    });
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
      _failed(e.toString());
    } catch (e) {
      _failed(e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    if (mounted && _child != null) await _loadInsights();
  }

  /// Keeps an already-shown Home on a failed refresh; shows the error only with nothing to show.
  void _failed(String message) {
    if (!mounted) return;
    if (_child == null) {
      setState(() => _error = message);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr(
              'Could not refresh. Showing the last update.',
              'नया नहीं ला सके। पिछली जानकारी दिखा रहे हैं।',
            ),
          ),
        ),
      );
    }
  }

  Future<void> _loadInsights() {
    setState(() => _weekLoading = _week == null);
    return Future.wait([
      _fill(Api.i.schoolWeek, (v) {
        _week = v;
        _weekLoading = false;
      }),
      _fill(() async {
        final dismissed = dismissedMoments();
        final moments = await Api.i.moments();
        _dismissed = await dismissed;
        return moments;
      }, (v) => _moments = v ?? const []),
      _fill(Api.i.tips, (v) => _tips = (v ?? const []).take(3).toList()),
    ]);
  }

  /// Runs one insight call; any error counts as "nothing to show".
  Future<void> _fill<T>(
    Future<T> Function() call,
    void Function(T?) set,
  ) async {
    T? v;
    try {
      v = await call();
    } catch (_) {}
    if (mounted) setState(() => set(v));
  }

  void _dismiss(Map<String, dynamic> m) {
    final key = momentKey(m);
    setState(() => _dismissed = {..._dismissed, key});
    dismissMoment(key);
  }

  void _open(Widget screen) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));

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
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const VoiceHistoryScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.settings_rounded),
            tooltip: tr('Settings', 'सेटिंग्स'),
            // Language and voice, and Log out.
            onPressed: () => _open(const SettingsScreen()),
          ),
        ],
      ),
      body: _loading
          ? const Loading()
          : RefreshIndicator(
              color: Ks.accent,
              onRefresh: _load,
              child: _error != null
                  ? ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      children: [
                        EmptyState(icon: Icons.wifi_off_rounded, text: _error!),
                      ],
                    )
                  : ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.all(18),
                      children: [
                        if (profile != null && c != null) ...[
                          ..._greeting(profile, c),
                          ..._insightsTop(),
                          _voiceCard(),
                          const SizedBox(height: 18),
                          ..._tipCards(),
                          InsightLinkTile(
                            icon: Icons.auto_awesome_rounded,
                            label: tr('Learning journey ⭐', 'सीखने का सफ़र ⭐'),
                            onTap: () => _open(const JourneyScreen()),
                          ),
                          InsightLinkTile(
                            icon: Icons.calendar_month_rounded,
                            label: tr(
                              "This week's summary",
                              'इस हफ़्ते का सारांश',
                            ),
                            onTap: () => _open(const WeeklyScreen()),
                          ),
                          ..._focusList(profile),
                        ],
                      ],
                    ),
            ),
    );
  }

  List<Widget> _greeting(
    Map<String, dynamic> profile,
    Map<String, dynamic> c,
  ) => [
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
                trf('Hello, {first_name}!', 'नमस्ते, {first_name}!', {'first_name': c['first_name']}),
                style: Theme.of(context).textTheme.titleLarge
                    ?.copyWith(fontSize: 26),
              ),
              Text(c['class'] ?? '', style: const TextStyle(color: Ks.muted)),
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
            const Icon(Icons.local_fire_department_rounded, color: Ks.amber),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                trf(
                  '{streak}-day practice streak: well done!',
                  '{streak} दिन लगातार अभ्यास, शाबाश!', {'streak': profile['streak']},
                ),
                style: const TextStyle(
                  color: Ks.amber,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
      ),
  ];

  /// "This week at school" and up to two "Teacher noticed" moments, above the voice card.
  List<Widget> _insightsTop() {
    final week = _week;
    final moments = _moments
        .where((m) => !_dismissed.contains(momentKey(m)))
        .where((m) => m['kind'] == 'celebration' || m['kind'] == 'catch_up')
        .take(2)
        .toList();
    return [
      if (_weekLoading)
        const SchoolWeekPlaceholder()
      else if (week != null && SchoolWeekCard.hasContent(week))
        SchoolWeekCard(week),
      if (moments.isNotEmpty) ...[
        SectionTitle(tr('Teacher noticed', 'शिक्षक ने देखा')),
        for (final m in moments)
          m['kind'] == 'catch_up'
              ? CatchUpCard(
                  m,
                  key: ValueKey(momentKey(m)),
                  onDismiss: () => _dismiss(m),
                )
              : CelebrationCard(
                  m,
                  key: ValueKey(momentKey(m)),
                  onDismiss: () => _dismiss(m),
                ),
      ],
      const SizedBox(height: 6),
    ];
  }

  List<Widget> _tipCards() => [
    if (_tips.isNotEmpty) ...[
      SectionTitle(tr('Help with a small mistake', 'छोटी गलती में मदद')),
      for (final t in _tips) TipCard(t),
      const SizedBox(height: 6),
    ],
  ];

  /// The child's current lessons from the profile (unchanged content, renamed heading).
  List<Widget> _focusList(Map<String, dynamic> profile) {
    final focus = ((profile['focus'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    if (focus.isEmpty) return const [];
    return [
      const SizedBox(height: 12),
      SectionTitle(tr('Working on now', 'अभी इन पर काम चल रहा है')),
      for (final f in focus)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: ListTile(
            leading: Icon(
              Icons.headphones_rounded,
              color: Ks.statusColor[f['status']] ?? Ks.accent,
            ),
            title: Text(cpTitle(f), style: const TextStyle(fontSize: 16)),
            subtitle: Text(
              pick(f, 'label'),
              style: TextStyle(color: Ks.statusColor[f['status']] ?? Ks.muted),
            ),
          ),
        ),
    ];
  }

  Future<void> _startVoice() async {
    try {
      await Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => const VoiceSessionScreen()));
    } catch (_) {}
    _load();
  }

  /// Entry to the 30-minute voice session (docs/voice_session_contract.md).
  Widget _voiceCard() => Card(
    color: Ks.accent,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    clipBehavior: Clip.antiAlias,
    child: InkWell(
      onTap: _startVoice,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Text('🦉', style: TextStyle(fontSize: 40)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    tr(
                      '30-minute voice session with Saathi',
                      'साथी के साथ 30 मिनट का आवाज़ सत्र',
                    ),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 21,
                      fontWeight: FontWeight.w700,
                      height: 1.3,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              tr(
                'Saathi talks with your child, listens, and moves from letters to reading. You get a report at the end.',
                'साथी बच्चे से बात करता है, सुनता है, और अक्षरों से पढ़ने तक ले जाता है। आख़िर में आपको रिपोर्ट मिलती है।',
              ),
              style: const TextStyle(color: Colors.white, fontSize: 15),
            ),
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: _startVoice,
              style: FilledButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: Ks.accent,
                minimumSize: const Size.fromHeight(60),
              ),
              icon: const Icon(Icons.record_voice_over_rounded, size: 26),
              label: Text(tr('Start voice session', 'आवाज़ सत्र शुरू करें')),
            ),
          ],
        ),
      ),
    ),
  );
}
