import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';

/// Short day for an ISO date (`2026-10-27` → "27 Oct" / "27 अक्टू"); '' when it can't be read.
String shortDay(Object? iso) {
  final d = DateTime.tryParse('${iso ?? ''}');
  if (d == null) return '';
  final en = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  final hi = [
    'जन', 'फ़र', 'मार्च', 'अप्रै', 'मई', 'जून', //
    'जुला', 'अग', 'सित', 'अक्टू', 'नव', 'दिस',
  ];
  return '${d.day} ${tr(en[d.month - 1], hi[d.month - 1])}';
}

int? _int(Object? v) => v is num ? v.toInt() : int.tryParse('${v ?? ''}');

List<Map<String, dynamic>> _rows(Object? v) => v is List
    ? v.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

/// "Follow-ups" card on the board: who to re-check, who is not moving, who missed group time, who
/// has not been checked lately and whose status is about to fade. Collapsed it is one row of
/// count chips; tap to see the children, tap a child to open their profile (the 2-minute probe).
/// Data: `GET /v1/classes/{id}/followups?subject=` (docs/teacher_loop_contract.md). Hides itself
/// when the call fails with nothing cached (e.g. an older server without the route) or when
/// every list is empty.
class BoardFollowupsCard extends StatefulWidget {
  const BoardFollowupsCard({
    super.key,
    required this.classId,
    required this.subject,
    required this.onOpenChild,
    required this.onOpenOutcomes,
    this.reloadToken = 0,
  });
  final int classId;
  final String subject;

  /// Gets `{id, first_name}`, the shape the board's own child chips pass.
  final void Function(Map<String, dynamic> child) onOpenChild;
  final VoidCallback onOpenOutcomes;

  /// Change this to fetch again (the board bumps it on every reload).
  final int reloadToken;
  @override
  State<BoardFollowupsCard> createState() => _BoardFollowupsCardState();
}

class _Section {
  const _Section(this.key, this.icon, this.color, this.bg);
  final String key;
  final IconData icon;
  final Color color;
  final Color bg;
}

/// Most urgent first; the order the chips and sections appear in.
const _sections = [
  _Section('recheck', Icons.fact_check_rounded, Ks.accent, Ks.accentSoft),
  _Section('stuck', Icons.sync_problem_rounded, Ks.rose, Ks.roseSoft),
  _Section('missed', Icons.event_busy_rounded, Ks.amber, Ks.amberSoft),
  _Section(
    'not_checked',
    Icons.visibility_off_rounded,
    Ks.muted,
    Color(0xFFF1EEE7),
  ),
  _Section('fading', Icons.hourglass_bottom_rounded, Ks.amber, Ks.amberSoft),
];

class _BoardFollowupsCardState extends State<BoardFollowupsCard> {
  static const _preview = 5;
  Map<String, dynamic>? _data;
  bool _hidden = false;
  bool _expanded = false;
  final Set<String> _showAll = {};
  int _seq = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(BoardFollowupsCard old) {
    super.didUpdateWidget(old);
    final other =
        old.classId != widget.classId || old.subject != widget.subject;
    if (other) {
      // Another class or subject: never show the previous one's children.
      _data = null;
      _hidden = false;
      _expanded = false;
      _showAll.clear();
    }
    if (other || old.reloadToken != widget.reloadToken) _load();
  }

  Future<void> _load() async {
    final seq = ++_seq;
    try {
      final r = await Api.i.get(
        '/v1/classes/${widget.classId}/followups?subject=${widget.subject}',
      );
      if (!mounted || seq != _seq) return;
      if (r is! Map) {
        setState(() => _hidden = _data == null);
        return;
      }
      setState(() {
        _data = r.cast<String, dynamic>();
        _hidden = false;
      });
    } catch (_) {
      // 404 (route not deployed yet), offline with no cached copy, ...: keep the last copy if any.
      if (!mounted || seq != _seq) return;
      if (_data == null) setState(() => _hidden = true);
    }
  }

  String _title(String key) => switch (key) {
    'recheck' => tr('Re-check today', 'आज फिर जाँचें'),
    'stuck' => tr('Not moving', 'आगे नहीं बढ़ रहे'),
    'missed' => tr('Missed group time', 'समूह का समय छूटा'),
    'not_checked' => tr('Not checked lately', 'कई दिन से जाँच नहीं'),
    _ => tr('Fading soon', 'जल्द पुराना होगा'),
  };

  /// Short chip label, e.g. "Re-check 3".
  String _chipLabel(String key, int n) => switch (key) {
    'recheck' => tr('Re-check $n', 'फिर जाँचें $n'),
    'stuck' => tr('Not moving $n', 'अटके $n'),
    'missed' => tr('Missed $n', 'छूटे $n'),
    'not_checked' => tr('Not checked $n', 'जाँच नहीं $n'),
    _ => tr('Fading $n', 'पुराना $n'),
  };

  /// One line under the section title saying what the list means.
  String _hint(String key) => switch (key) {
    'recheck' => tr(
      'Taught in a group, not checked since. A 2-minute check shows if it worked.',
      'समूह में पढ़ाया, उसके बाद जाँच नहीं हुई। 2 मिनट की जाँच से पता चलेगा कि असर हुआ या नहीं।',
    ),
    'stuck' => tr(
      'Three or more group sessions on the same lesson and not on track yet.',
      'एक ही सबक पर तीन या ज़्यादा बार समूह में पढ़े, फिर भी अभी ठीक नहीं।',
    ),
    'missed' => tr(
      'Absent on the days their group was taught.',
      'जिन दिनों उनका समूह पढ़ाया गया, उस दिन अनुपस्थित थे।',
    ),
    'not_checked' => tr(
      'At most one classroom check in the last 14 days.',
      'पिछले 14 दिनों में कक्षा में एक या कोई जाँच नहीं।',
    ),
    _ => tr(
      'Their last check is getting old. Check again to keep the status.',
      'आख़िरी जाँच पुरानी हो रही है। स्थिति बनाए रखने के लिए फिर जाँचें।',
    ),
  };

  String _daysAgo(int? d) {
    if (d == null) return '';
    if (d <= 0) return tr('taught today', 'आज पढ़ाया');
    if (d == 1) return tr('taught yesterday', 'कल पढ़ाया');
    return tr('taught $d days ago', '$d दिन पहले पढ़ाया');
  }

  String _status(Object? s) =>
      Ks.statusLabel['$s'] ?? Ks.statusLabel['not_started']!;

  /// Detail lines for one child row: [main, extra?].
  List<String> _lines(String key, Map<String, dynamic> r) {
    final lesson = cpTitle(r);
    String withLesson(String s) => lesson.isEmpty ? s : '$lesson · $s';
    switch (key) {
      case 'recheck':
        return [
          withLesson(_daysAgo(_int(r['days_since']))),
          if (r['has_probe'] == true)
            tr('2-minute check ready', '2 मिनट की जाँच तैयार'),
        ];
      case 'stuck':
        final n = _int(r['sessions']) ?? 0;
        final alt = '${r['alt_activity_title_hi'] ?? ''}'.trim();
        final tip = pick(r, 'suggestion').trim();
        return [
          withLesson(
            tr(
              '$n sessions, still ${_status(r['status']).toLowerCase()}',
              '$n बार, अब भी ${_status(r['status'])}',
            ),
          ),
          if (alt.isNotEmpty)
            tr('Try instead: $alt', 'इसके बजाय आज़माएँ: $alt')
          else if (tip.isNotEmpty)
            tip,
        ];
      case 'missed':
        final m = _int(r['missed']) ?? 0;
        final of = _int(r['of']) ?? 0;
        return [
          withLesson(
            tr(
              'missed $m of $of group sessions',
              '$of में से $m समूह सत्र छूटे',
            ),
          ),
        ];
      case 'not_checked':
        final n = _int(r['checks_14d']) ?? 0;
        final last = shortDay(r['last_checked']);
        return [
          n == 0
              ? tr('No check in 14 days', '14 दिन में कोई जाँच नहीं')
              : tr('$n check in 14 days', '14 दिन में $n जाँच'),
          if (last.isNotEmpty) tr('Last checked $last', 'आख़िरी जाँच $last'),
        ];
      default:
        final d = _int(r['expires_in_days']) ?? 0;
        return [
          withLesson(
            d <= 0
                ? tr(
                    '${_status(r['status'])}, fades today',
                    '${_status(r['status'])}, आज पुराना होगा',
                  )
                : tr(
                    '${_status(r['status'])}, fades in $d days',
                    '${_status(r['status'])}, $d दिन में पुराना होगा',
                  ),
          ),
        ];
    }
  }

  void _open(Map<String, dynamic> r) {
    final id = _int(r['child_id']);
    if (id == null) return;
    widget.onOpenChild({'id': id, 'first_name': '${r['first_name'] ?? ''}'});
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    if (_hidden || d == null) return const SizedBox.shrink();
    final lists = {for (final s in _sections) s.key: _rows(d[s.key])};
    final present = _sections.where((s) => lists[s.key]!.isNotEmpty).toList();
    if (present.isEmpty) return const SizedBox.shrink();
    final total = present.fold<int>(0, (n, s) => n + lists[s.key]!.length);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
              child: Row(
                children: [
                  const Icon(Icons.flag_rounded, color: Ks.accent),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      tr('Follow-ups ($total)', 'आगे क्या करें ($total)'),
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 16,
                        color: Ks.ink,
                      ),
                    ),
                  ),
                  if (d['offline'] == true)
                    Tooltip(
                      message: tr('Saved copy', 'सहेजी हुई कॉपी'),
                      child: const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 6),
                        child: Icon(
                          Icons.cloud_off_rounded,
                          size: 18,
                          color: Ks.amber,
                        ),
                      ),
                    ),
                  SizedBox(
                    width: 48,
                    height: 48,
                    child: Icon(
                      _expanded
                          ? Icons.expand_less_rounded
                          : Icons.expand_more_rounded,
                      color: Ks.muted,
                    ),
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final s in present) _countChip(s, lists[s.key]!.length),
              ],
            ),
          ),
          if (_expanded)
            for (final s in present) _section(s, lists[s.key]!),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 4),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                style: TextButton.styleFrom(
                  minimumSize: const Size(48, 48),
                  foregroundColor: Ks.accent,
                ),
                onPressed: widget.onOpenOutcomes,
                icon: const Icon(Icons.insights_rounded),
                label: Text(tr('Did it work?', 'क्या असर हुआ?')),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Count pill; tapping it opens the card.
  Widget _countChip(_Section s, int n) => Semantics(
    button: true,
    label: '${_title(s.key)}: $n',
    excludeSemantics: true,
    child: Material(
      color: s.bg,
      shape: const StadiumBorder(),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => setState(() => _expanded = true),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 44),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(s.icon, size: 18, color: s.color),
                const SizedBox(width: 6),
                Text(
                  _chipLabel(s.key, n),
                  style: TextStyle(
                    color: s.color,
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  Widget _section(_Section s, List<Map<String, dynamic>> rows) {
    final all = _showAll.contains(s.key);
    final shown = all ? rows : rows.take(_preview).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(height: 1, color: Ks.line),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 2),
          child: Row(
            children: [
              Icon(s.icon, size: 20, color: s.color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${_title(s.key)} (${rows.length})',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                    color: Ks.ink,
                  ),
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(44, 0, 16, 4),
          child: Text(
            _hint(s.key),
            style: const TextStyle(color: Ks.muted, fontSize: 13),
          ),
        ),
        for (final r in shown) _row(s, r),
        if (rows.length > _preview)
          Padding(
            padding: const EdgeInsets.only(left: 36),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                style: TextButton.styleFrom(
                  minimumSize: const Size(48, 48),
                  foregroundColor: Ks.accent,
                ),
                onPressed: () => setState(
                  () => all ? _showAll.remove(s.key) : _showAll.add(s.key),
                ),
                child: Text(
                  all
                      ? tr('Show less', 'कम दिखाएँ')
                      : tr(
                          'See all (${rows.length})',
                          'सभी देखें (${rows.length})',
                        ),
                ),
              ),
            ),
          ),
        const SizedBox(height: 4),
      ],
    );
  }

  Widget _row(_Section s, Map<String, dynamic> r) {
    final lines = _lines(s.key, r);
    final roll = _int(r['roll_no']);
    final name = '${r['first_name'] ?? ''}';
    return InkWell(
      onTap: () => _open(r),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(
            children: [
              CircleAvatar(
                radius: 16,
                backgroundColor: s.bg,
                child: Text(
                  roll == null ? '' : '$roll',
                  style: TextStyle(
                    color: s.color,
                    fontSize: 13,
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
                      name,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Ks.ink,
                      ),
                    ),
                    if (lines.isNotEmpty && lines.first.isNotEmpty)
                      Text(
                        lines.first,
                        style: const TextStyle(color: Ks.muted, fontSize: 14),
                      ),
                    for (final l in lines.skip(1))
                      Text(
                        l,
                        style: TextStyle(
                          color: s.color,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
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
}
