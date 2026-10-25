import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../widgets/capture_sheet.dart';
import 'class_picker_screen.dart';
import 'login_screen.dart';
import 'group_plan_screen.dart';
import 'level_screen.dart';
import 'settings_screen.dart';
import '../l10n.dart';

/// Class + subject selection, then the "classroom board": today's groups, on-track, unassessed.
class BoardScreen extends StatefulWidget {
  const BoardScreen({super.key, this.initialClass});
  final Map<String, dynamic>? initialClass;
  @override
  State<BoardScreen> createState() => _BoardScreenState();
}

class _BoardScreenState extends State<BoardScreen> {
  Map<String, dynamic>? _cls;
  String _subject = 'numeracy';
  Map<String, dynamic>? _board;
  bool _loading = true;
  String? _error;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    _cls = widget.initialClass;
    _init();
  }

  Future<void> _init() async {
    try {
      await Api.i.fetchMe();
      final classes = await Api.i.classes();
      if (classes is List && classes.isEmpty) {
        setState(
          () => _error = tr(
            'No class found — connect with your school.',
            'कोई कक्षा नहीं मिली — स्कूल से जोड़ें।',
          ),
        );
      }
      if (classes is List && classes.isNotEmpty) {
        _cls ??= _pickDefault(classes.cast<Map<String, dynamic>>());
      }
    } on ApiError catch (e) {
      if (e.status == 401) {
        await Api.i.logout();
        if (mounted) {
          Navigator.of(context).pushAndRemoveUntil(
            MaterialPageRoute(builder: (_) => const LoginScreen()),
            (_) => false,
          );
        }
        return;
      }
    } catch (_) {}
    await _loadBoard();
  }

  Map<String, dynamic> _pickDefault(List<Map<String, dynamic>> classes) {
    final grade2 = classes.where((c) => c['grade'] == 2).toList();
    return (grade2.isNotEmpty ? grade2.first : classes.first);
  }

  Future<void> _loadBoard({bool showSpinner = true}) async {
    if (_cls == null) {
      setState(() => _loading = false);
      return;
    }
    if (showSpinner) setState(() => _loading = true);
    try {
      final b = await Api.i.board(_cls!['id'] as int, _subject);
      setState(() {
        _board = b as Map<String, dynamic>;
        _offline = b['offline'] == true;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _openPlan() async {
    if (_cls == null) return;
    final plan = await Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(
        builder: (_) => GroupPlanScreen(
          classId: _cls!['id'] as int,
          className: _cls!['label'] as String,
          subject: _subject,
        ),
      ),
    );
    if (plan != null) _loadBoard(showSpinner: false);
  }

  Future<void> _capture() async {
    if (_cls == null) return;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (_) =>
          CaptureSheet(classId: _cls!['id'] as int, subject: _subject),
    );
    if (changed == true) _loadBoard(showSpinner: false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_cls?['label'] ?? tr('Kaksha Saathi', 'कक्षा साथी')),
            if (Api.i.me != null)
              Text(
                Api.i.me!['name'] ?? '',
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w400,
                  color: Ks.muted,
                ),
              ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: tr('Classes', 'कक्षाएँ'),
            icon: const Icon(Icons.swap_horiz_rounded),
            onPressed: () async {
              final c = await Navigator.of(context).push<Map<String, dynamic>>(
                MaterialPageRoute(builder: (_) => const ClassPickerScreen()),
              );
              if (c != null) {
                setState(() {
                  _cls = c;
                  _board = null;
                });
                _init();
              }
            },
          ),
          IconButton(
            tooltip: tr('Settings', 'सेटिंग्स'),
            icon: const Icon(Icons.settings_rounded),
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _loadBoard(),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 110),
          children: [
            _subjectTabs(),
            if (_offline) _offlineBanner(),
            ..._content(),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _capture,
        backgroundColor: Ks.accent,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_a_photo_rounded),
        label: Text(
          tr('Add evidence', 'साक्ष्य जोड़ें'),
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  Widget _subjectTabs() => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: SegmentedButton<String>(
      segments: [
        ButtonSegment(
          value: 'numeracy',
          label: Text(tr('Maths', 'गणित')),
          icon: Icon(Icons.calculate_rounded),
        ),
        ButtonSegment(
          value: 'literacy',
          label: Text(tr('Hindi', 'हिंदी')),
          icon: Icon(Icons.menu_book_rounded),
        ),
      ],
      selected: {_subject},
      onSelectionChanged: (s) {
        setState(() => _subject = s.first);
        _loadBoard();
      },
      showSelectedIcon: false,
      style: ButtonStyle(
        minimumSize: WidgetStateProperty.all(const Size(140, 52)),
        textStyle: WidgetStateProperty.all(
          const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
      ),
    ),
  );

  Widget _offlineBanner() => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: Ks.amberSoft,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      children: [
        Icon(Icons.cloud_off_rounded, color: Ks.amber),
        SizedBox(width: 8),
        Expanded(
          child: Text(
            tr(
              'Offline — showing the last saved board.',
              'ऑफलाइन — पिछली बार का बोर्ड दिख रहा है।',
            ),
            style: TextStyle(color: Ks.amber),
          ),
        ),
      ],
    ),
  );

  List<Widget> _content() {
    if (_loading)
      return [
        Padding(
          padding: EdgeInsets.only(top: 60),
          child: Loading(
            label: tr('Loading class status…', 'कक्षा की स्थिति आ रही है…'),
          ),
        ),
      ];
    if (_error != null)
      return [EmptyState(icon: Icons.error_outline, text: _error!)];
    final b = _board;
    if (b == null)
      return [
        EmptyState(
          icon: Icons.school_outlined,
          text: tr('Class not found.', 'कक्षा नहीं मिली।'),
        ),
      ];
    final groups = (b['groups'] as List).cast<Map<String, dynamic>>();
    final onTrack = (b['on_track'] as List).cast<Map<String, dynamic>>();
    final unassessed = (b['unassessed'] as List).cast<Map<String, dynamic>>();
    return [
      if (groups.isEmpty) ...[
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              children: [
                const Icon(
                  Icons.celebration_rounded,
                  size: 40,
                  color: Ks.green,
                ),
                const SizedBox(height: 8),
                Text(
                  tr(
                    'No new plan needed for any group today — everyone is on track or awaiting checks.',
                    'आज किसी समूह के लिए नई योजना नहीं — सब ट्रैक पर या जाँच बाकी है।',
                  ),
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
              ],
            ),
          ),
        ),
      ],
      SectionTitle(
        tr('Teach these children together', 'इन बच्चों को एक साथ पढ़ाएँ'),
      ),
      ...groups.map(_groupCard),
      if (unassessed.isNotEmpty) ...[
        SectionTitle(tr('Check pending — 3 taps', 'जाँच बाकी — 3 टैप')),
        _unassessedCard(unassessed),
      ],
      if (onTrack.isNotEmpty) ...[
        SectionTitle(
          tr('On track (${onTrack.length})', 'अपनी गति पर (${onTrack.length})'),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final c in onTrack)
                  Chip(
                    avatar: const Icon(
                      Icons.check_rounded,
                      size: 16,
                      color: Ks.green,
                    ),
                    label: Text(c['first_name']),
                    backgroundColor: Ks.greenSoft,
                    side: BorderSide.none,
                    labelStyle: const TextStyle(fontSize: 15),
                    onDeleted: () => _openChild(c),
                    deleteIcon: const Icon(
                      Icons.open_in_new_rounded,
                      size: 16,
                      color: Ks.muted,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    ];
  }

  Future<void> _openChild(Map<String, dynamic> c) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => LevelScreen(
          childId: c['id'] as int,
          childName: c['first_name'] as String,
          classId: _cls!['id'] as int,
          subject: _subject,
        ),
      ),
    );
    _loadBoard(showSpinner: false);
  }

  Widget _groupCard(Map<String, dynamic> g) {
    final status = g['status'] as String? ?? 'needs_practice';
    final reason = g['reason'] as String? ?? '';
    final members = (g['members'] as List).cast<Map<String, dynamic>>();
    final reasonHi = switch (reason) {
      'needs_intervention_root' || 'needs_practice_root' => tr(
        'Foundation gap — start here first',
        'आधार की चूक — पहले यहीं से शुरू करें',
      ),
      'direct' => tr('Struggling in this lesson', 'इसी सबक में कठिनाई'),
      _ => '',
    };
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: _openPlan,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 44,
                    decoration: BoxDecoration(
                      color: Ks.statusColor[status],
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          tr(
                            '${g['chapter']} · ${members.length} children',
                            '${g['chapter']} · ${members.length} बच्चे',
                          ),
                          style: const TextStyle(color: Ks.muted, fontSize: 14),
                        ),
                        Text(
                          cpTitle(g),
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ],
                    ),
                  ),
                  const Icon(Icons.chevron_right_rounded, color: Ks.muted),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final m in members)
                    InkWell(
                      onTap: () => _openChild(m),
                      child: Chip(
                        label: Text(
                          m['first_name'],
                          style: const TextStyle(fontSize: 15),
                        ),
                        backgroundColor: Ks.statusBg[status]!,
                        side: BorderSide.none,
                        visualDensity: VisualDensity.compact,
                      ),
                    ),
                ],
              ),
              if (reasonHi.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(
                      Icons.lightbulb_outline_rounded,
                      size: 16,
                      color: Ks.muted,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        reasonHi,
                        style: const TextStyle(color: Ks.muted, fontSize: 14),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _unassessedCard(List<Map<String, dynamic>> kids) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final c in kids)
                Chip(
                  label: Text(c['first_name']),
                  backgroundColor: Ks.statusBg['not_started'],
                  side: BorderSide.none,
                ),
            ],
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: () => _quickTap(kids),
            icon: const Icon(Icons.touch_app_rounded),
            label: Text(tr('Check in 3 taps', 'तीन टैप में जाँचें')),
          ),
        ],
      ),
    ),
  );

  Future<void> _quickTap(List<Map<String, dynamic>> kids) async {
    final subject0 = _subject;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      builder: (_) => CaptureSheet(
        classId: _cls!['id'] as int,
        subject: subject0,
        presetChildren: kids,
      ),
    );
    if (changed == true) _loadBoard(showSpinner: false);
  }
}
