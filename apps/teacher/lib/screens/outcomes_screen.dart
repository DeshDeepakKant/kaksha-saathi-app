import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import '../widgets/board_followups.dart' show shortDay;
import 'level_screen.dart';

/// "Did it work?": every group taught in the last 6 weeks (newest first) with how many children
/// moved up once re-checked, each child's status before → after, and which activities moved
/// children. Data: `GET /v1/classes/{id}/outcomes?subject=&days=42`
/// (docs/teacher_loop_contract.md). Counts and statuses come from the server; nothing is inferred here.
class OutcomesScreen extends StatefulWidget {
  const OutcomesScreen({
    super.key,
    required this.classId,
    required this.subject,
  });
  final int classId;
  final String subject;
  @override
  State<OutcomesScreen> createState() => _OutcomesScreenState();
}

int _n(Object? v) => v is num ? v.toInt() : int.tryParse('${v ?? ''}') ?? 0;

List<Map<String, dynamic>> _maps(Object? v) => v is List
    ? v.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

class _OutcomesScreenState extends State<OutcomesScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  bool _missing = false; // the server has no outcomes route yet (404)

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// [silent] keeps what is on screen (pull-to-refresh, coming back from a child profile).
  Future<void> _load({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final r = await Api.i.get(
        '/v1/classes/${widget.classId}/outcomes?subject=${widget.subject}&days=42',
      );
      if (!mounted) return;
      if (r is! Map) throw ApiError('', 0);
      setState(() {
        _data = r.cast<String, dynamic>();
        _error = null;
        _missing = false;
      });
    } catch (e) {
      if (!mounted) return;
      if (_data == null) {
        setState(() {
          _missing = e is ApiError && e.status == 404;
          _error = e is ApiError && e.status >= 400 && e.status < 500
              ? e.message
              : tr(
                  "Can't reach the server right now. Check your internet and try again.",
                  'सर्वर से जुड़ नहीं पा रहे। इंटरनेट देखें और दोबारा कोशिश करें।',
                );
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openChild(Map<String, dynamic> c) async {
    final id = c['child_id'];
    if (id is! num) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => LevelScreen(
          childId: id.toInt(),
          childName: '${c['first_name'] ?? ''}',
          classId: widget.classId,
          subject: widget.subject,
        ),
      ),
    );
    // A re-check on the profile changes "after": refresh quietly.
    if (mounted) _load(silent: true);
  }

  /// Keeps pull-to-refresh working when the body is a spinner, an error or an empty state.
  Widget _scrollable(Widget child) => LayoutBuilder(
    builder: (context, c) => ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [SizedBox(height: c.maxHeight, child: child)],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final subject = widget.subject == 'numeracy'
        ? tr('Maths', 'गणित')
        : widget.subject == 'literacy'
        ? tr('Hindi', 'हिंदी')
        : widget.subject;
    return Scaffold(
      appBar: AppBar(
        title: Text(trf('Did it work? · {subject}', 'क्या असर हुआ? · {subject}', {'subject': subject})),
      ),
      body: RefreshIndicator(
        onRefresh: () => _load(silent: _data != null),
        child: _loading && _data == null
            ? _scrollable(const Loading())
            : _data == null
            ? _scrollable(_errorView())
            : _body(_data!),
      ),
    );
  }

  Widget _errorView() => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        EmptyState(
          icon: _missing ? Icons.update_rounded : Icons.cloud_off_rounded,
          text: _missing
              ? tr(
                  'Results are not available on this server yet.',
                  'यह सुविधा अभी इस सर्वर पर उपलब्ध नहीं है।',
                )
              : (_error ?? ''),
        ),
        if (!_missing)
          SizedBox(
            width: 220,
            child: FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Try again', 'फिर कोशिश करें')),
            ),
          ),
      ],
    ),
  );

  Widget _body(Map<String, dynamic> d) {
    final sessions = _maps(d['sessions']);
    final activities = _maps(d['activities']);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      children: [
        if (d['offline'] == true)
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Ks.amberSoft,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                const Icon(Icons.cloud_off_rounded, color: Ks.amber),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    tr(
                      'Offline — showing the last saved results.',
                      'ऑफलाइन — पिछली बार के नतीजे दिख रहे हैं।',
                    ),
                    style: const TextStyle(color: Ks.amber),
                  ),
                ),
              ],
            ),
          ),
        Text(
          tr(
            'Groups you marked Done in the last 6 weeks. A child counts once they are checked again on that lesson.',
            'पिछले 6 हफ़्तों में जिन समूहों को "किया" दबाया। बच्चा तभी गिना जाता है जब उसी सबक पर उसकी फिर जाँच हो।',
          ),
          style: const TextStyle(color: Ks.muted, fontSize: 14),
        ),
        const SizedBox(height: 12),
        if (sessions.isEmpty)
          EmptyState(
            icon: Icons.groups_rounded,
            text: tr(
              'No group sessions yet. After teaching a group, tap "Done" on its plan card.',
              'अभी कोई समूह सत्र नहीं। समूह को पढ़ाने के बाद योजना कार्ड पर "किया" दबाएँ।',
            ),
          )
        else ...[
          SectionTitle(tr('Group sessions', 'समूह सत्र')),
          for (final s in sessions) _sessionCard(s),
        ],
        if (activities.isNotEmpty) ...[
          const SizedBox(height: 8),
          SectionTitle(
            tr(
              'Activities that moved children',
              'जिन गतिविधियों से बच्चे आगे बढ़े',
            ),
          ),
          Card(
            child: Column(
              children: [
                for (var i = 0; i < activities.length; i++) ...[
                  if (i > 0) const Divider(height: 1, color: Ks.line),
                  _activityRow(activities[i]),
                ],
              ],
            ),
          ),
        ],
      ],
    );
  }

  /// "4 of 6 moved up · 1 not re-checked" (zero parts other than "moved up" are left out).
  String _summary(Map<String, dynamic> s) {
    final members = _n(s['members']);
    final up = _n(s['moved_up']);
    final same = _n(s['same']);
    final down = _n(s['moved_down']);
    final not = _n(s['not_rechecked']);
    return [
      trf('{up} of {members} moved up', '{members} में से {up} आगे बढ़े', {'up': up, 'members': members}),
      if (same > 0) trf('{same} same', '{same} वहीं', {'same': same}),
      if (down > 0) trf('{down} slipped', '{down} पीछे गए', {'down': down}),
      if (not > 0) trf('{not} not re-checked', '{not} की फिर जाँच नहीं', {'not': not}),
    ].join(' · ');
  }

  Widget _sessionCard(Map<String, dynamic> s) {
    final kids = _maps(s['children']);
    final act = '${s['activity_title_hi'] ?? ''}'.trim();
    final day = shortDay(s['done_on']);
    final members = _n(s['members']);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        shape: const Border(),
        collapsedShape: const Border(),
        tilePadding: const EdgeInsetsDirectional.fromSTEB(16, 6, 12, 6),
        childrenPadding: const EdgeInsets.only(bottom: 8),
        title: Text(
          cpTitle(s).isEmpty ? '${s['checkpoint_id'] ?? ''}' : cpTitle(s),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (day.isNotEmpty || act.isNotEmpty)
              Text(
                [if (day.isNotEmpty) day, if (act.isNotEmpty) act].join(' · '),
                style: const TextStyle(color: Ks.muted, fontSize: 14),
              ),
            const SizedBox(height: 4),
            Text(
              _summary(s),
              style: const TextStyle(
                color: Ks.ink,
                fontSize: 15,
                fontWeight: FontWeight.w600,
              ),
            ),
            if (members > 0) ...[const SizedBox(height: 8), _bar(s, members)],
          ],
        ),
        children: [
          if (kids.isEmpty)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                tr('No children listed.', 'कोई बच्चा नहीं।'),
                style: const TextStyle(color: Ks.muted),
              ),
            ),
          for (final c in kids) _childRow(c),
        ],
      ),
    );
  }

  /// Proportion bar: moved up / same / slipped / not re-checked (colour plus the text above).
  Widget _bar(Map<String, dynamic> s, int members) {
    final parts = <(int, Color)>[
      (_n(s['moved_up']), Ks.green),
      (_n(s['same']), Ks.amber),
      (_n(s['moved_down']), Ks.rose),
      (_n(s['not_rechecked']), Ks.line),
    ].where((p) => p.$1 > 0).toList();
    if (parts.isEmpty) return const SizedBox.shrink();
    return ClipRRect(
      borderRadius: BorderRadius.circular(4),
      child: SizedBox(
        height: 8,
        child: Row(
          children: [
            for (final p in parts)
              Expanded(
                flex: p.$1,
                child: Container(color: p.$2),
              ),
          ],
        ),
      ),
    );
  }

  Widget _childRow(Map<String, dynamic> c) {
    final change = '${c['change'] ?? ''}';
    final before = '${c['before'] ?? 'not_started'}';
    final after = c['after'];
    final (IconData icon, Color color) = switch (change) {
      'up' => (Icons.arrow_upward_rounded, Ks.green),
      'down' => (Icons.arrow_downward_rounded, Ks.rose),
      'same' => (Icons.arrow_forward_rounded, Ks.muted),
      _ => (Icons.more_horiz_rounded, Ks.muted),
    };
    return InkWell(
      onTap: () => _openChild(c),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(16, 8, 8, 8),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${c['first_name'] ?? ''}',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Ks.ink,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        StatusChip(before, compact: true),
                        Icon(icon, size: 18, color: color),
                        if (after is String && after.isNotEmpty)
                          StatusChip(after, compact: true)
                        else
                          _notRechecked(),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: Ks.muted),
            ],
          ),
        ),
      ),
    );
  }

  Widget _notRechecked() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
    decoration: BoxDecoration(
      border: Border.all(color: Ks.line),
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      tr('Not re-checked yet', 'अभी फिर जाँच नहीं'),
      style: const TextStyle(
        fontSize: 13,
        color: Ks.muted,
        fontWeight: FontWeight.w600,
      ),
    ),
  );

  Widget _activityRow(Map<String, dynamic> a) {
    final up = _n(a['moved_up']);
    final rechecked = _n(a['rechecked']);
    final sessions = _n(a['sessions']);
    final kids = _n(a['children']);
    final title = '${a['title_hi'] ?? ''}'.trim();
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 56),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(
          children: [
            CircleAvatar(
              radius: 18,
              backgroundColor: up > 0
                  ? Ks.greenSoft
                  : Ks.statusBg['not_started'],
              child: Text(
                '$up',
                style: TextStyle(
                  color: up > 0 ? Ks.green : Ks.muted,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title.isEmpty ? '${a['activity_id'] ?? ''}' : title,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Ks.ink,
                    ),
                  ),
                  Text(
                    trf(
                      '{up} of {rechecked} re-checked moved up · {sessions} sessions, {kids} children',
                      'फिर जाँचे गए {rechecked} में से {up} आगे बढ़े · {sessions} सत्र, {kids} बच्चे', {'up': up, 'rechecked': rechecked, 'sessions': sessions, 'kids': kids},
                    ),
                    style: const TextStyle(color: Ks.muted, fontSize: 14),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
