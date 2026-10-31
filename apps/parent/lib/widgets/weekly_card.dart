import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// `GET /v1/parent/weekly` (docs/parent_insights_contract.md), read defensively: missing fields
/// become empty, and `practice_days` may arrive as a count or as a list of ISO dates.
class WeeklyData {
  WeeklyData._({
    required this.raw,
    required this.start,
    required this.end,
    required this.days,
    required this.practiceDays,
    required this.voiceMinutes,
    required this.learned,
    required this.working,
    required this.next,
    required this.tip,
  });

  factory WeeklyData.from(Map<String, dynamic> m) {
    final start = _date(m['week_start']);
    final end = _date(m['week_end']);
    final pd = m['practice_days'];
    Set<int>? days;
    var count = 0;
    if (pd is List) {
      final found = <int>{};
      for (final v in pd) {
        final d = _date(v);
        if (d == null) continue;
        if (start != null && d.isBefore(start)) continue;
        if (end != null && d.isAfter(end)) continue;
        found.add(d.weekday - 1);
      }
      days = found.isEmpty && pd.isNotEmpty ? null : found;
      count = days?.length ?? pd.length;
    } else if (pd is num) {
      count = pd.round();
    }
    return WeeklyData._(
      raw: m,
      start: start,
      end: end,
      days: days,
      practiceDays: count.clamp(0, 7),
      voiceMinutes: ((m['voice_minutes'] as num?) ?? 0).round(),
      learned: _maps(m['learned']),
      working: _maps(m['working_on']),
      next: _maps(m['next']),
      tip: (m['tip'] as Map?)?.cast<String, dynamic>(),
    );
  }

  final Map<String, dynamic> raw;
  final DateTime? start;
  final DateTime? end;

  /// Practised weekdays, 0 = Monday … 6 = Sunday; null when only a count was sent.
  final Set<int>? days;
  final int practiceDays;
  final int voiceMinutes;
  final List<Map<String, dynamic>> learned;
  final List<Map<String, dynamic>> working;
  final List<Map<String, dynamic>> next;
  final Map<String, dynamic>? tip;

  String get line => pick(raw, 'line').trim();

  /// Nothing happened this week yet (brand-new child or a quiet week).
  bool get isQuiet =>
      practiceDays == 0 &&
      voiceMinutes == 0 &&
      learned.isEmpty &&
      working.isEmpty &&
      next.isEmpty &&
      tip == null;

  static DateTime? _date(Object? v) {
    if (v is! String || v.isEmpty) return null;
    final d = DateTime.tryParse(v);
    return d == null ? null : DateTime(d.year, d.month, d.day);
  }

  static List<Map<String, dynamic>> _maps(Object? v) =>
      ((v as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .where((e) => cpTitle(e).trim().isNotEmpty)
          .toList();
}

const _monthsEn = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];
const _monthsHi = [
  'जनवरी', 'फ़रवरी', 'मार्च', 'अप्रैल', 'मई', 'जून', //
  'जुलाई', 'अगस्त', 'सितंबर', 'अक्टूबर', 'नवंबर', 'दिसंबर',
];
const _daysEn = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const _daysHi = ['सो', 'मं', 'बु', 'गु', 'शु', 'श', 'र'];

String _day(DateTime d) =>
    '${d.day} ${tr(_monthsEn[d.month - 1], _monthsHi[d.month - 1])}';

/// "27 Oct – 2 Nov" (Hindi month names in Hindi); empty when the server sent no dates.
String weekRange(DateTime? start, DateTime? end) {
  if (start == null && end == null) return '';
  if (start == null || end == null) return _day((start ?? end)!);
  return '${_day(start)} – ${_day(end)}';
}

String weeklyName(String name) =>
    name.trim().isNotEmpty ? name.trim() : tr('Your child', 'आपका बच्चा');

/// The card's opening sentence: the server line, else a gentle template.
String weeklyLine(WeeklyData w, String name) {
  if (w.line.isNotEmpty) return w.line;
  final n = weeklyName(name);
  if (w.isQuiet) {
    return trf(
      'A new week is a fresh start. Try one short practice with {n} today.',
      'नया हफ़्ता, नई शुरुआत। आज {n} के साथ एक छोटा-सा अभ्यास करें।', {'n': n},
    );
  }
  return trf('Here is {n}\'s week.', 'यह रहा {n} का हफ़्ता।', {'n': n});
}

String _practiceText(int n) {
  if (n == 0) {
    return tr(
      'No practice at home yet this week. Even 5 minutes helps.',
      'इस हफ़्ते घर पर अभी अभ्यास नहीं हुआ। 5 मिनट भी काफ़ी हैं।',
    );
  }
  if (n == 1) {
    return tr(
      'Practised at home on 1 day this week',
      'इस हफ़्ते 1 दिन घर पर अभ्यास किया',
    );
  }
  return trf(
    'Practised at home on {n} days this week',
    'इस हफ़्ते {n} दिन घर पर अभ्यास किया', {'n': n},
  );
}

String _join(List<Map<String, dynamic>> l) => l.map(cpTitle).join(', ');

/// What "Read aloud" says: the line, then the three lists.
String weeklySpeech(WeeklyData w, String name) {
  final parts = [weeklyLine(w, name)];
  if (w.learned.isNotEmpty) {
    parts.add(
      trf(
        'Learned this week: {join}.',
        'इस हफ़्ते सीखा: {join}।', {'join': _join(w.learned)},
      ),
    );
  }
  if (w.working.isNotEmpty) {
    parts.add(
      trf(
        'Working on: {join}.',
        'अभी सीख रहे हैं: {join}।', {'join': _join(w.working)},
      ),
    );
  }
  if (w.next.isNotEmpty) {
    parts.add(trf('Next: {join}.', 'आगे सीखेंगे: {join}।', {'join': _join(w.next)}));
  }
  return parts.join(' ');
}

/// Plain-text version of the card (WhatsApp caption fallback / clipboard).
String weeklyShareText(WeeklyData w, String name) {
  final n = weeklyName(name);
  final dates = weekRange(w.start, w.end);
  final b = StringBuffer()
    ..writeln(
      trf("{n}'s week", '{n} का हफ़्ता', {'n': n}) + (dates.isEmpty ? '' : ' ($dates)'),
    )
    ..writeln(weeklyLine(w, name))
    ..writeln(_practiceText(w.practiceDays));
  void list(String label, List<Map<String, dynamic>> l) {
    if (l.isEmpty) return;
    b.writeln();
    b.writeln('$label:');
    for (final m in l) {
      b.writeln('• ${cpTitle(m)}');
    }
  }

  list(tr('Learned this week', 'इस हफ़्ते सीखा'), w.learned);
  list(tr('Working on', 'अभी सीख रहे हैं'), w.working);
  list(tr('Next', 'आगे सीखेंगे'), w.next);
  final t = w.tip;
  if (t != null) {
    final explain = pick(t, 'explain').trim();
    final game = pick(t, 'game').trim();
    if (explain.isNotEmpty || game.isNotEmpty) {
      b.writeln();
      if (explain.isNotEmpty) b.writeln('💡 $explain');
      if (game.isNotEmpty) {
        b.writeln('${tr('1-minute game', '1 मिनट का खेल')}: $game');
      }
    }
  }
  b
    ..writeln()
    ..write(tr('- Kaksha Saathi', '- कक्षा साथी'));
  return b.toString();
}

/// The weekly summary card. Wrapped in a [RepaintBoundary] keyed by [boundaryKey] on a solid
/// paper background so it can be captured as a PNG and shared.
class WeeklyCard extends StatelessWidget {
  const WeeklyCard({
    super.key,
    required this.data,
    required this.name,
    this.boundaryKey,
  });

  final WeeklyData data;
  final String name;
  final GlobalKey? boundaryKey;

  @override
  Widget build(BuildContext context) {
    final w = data;
    final n = weeklyName(name);
    final dates = weekRange(w.start, w.end);
    final t = w.tip;
    return RepaintBoundary(
      key: boundaryKey,
      child: ColoredBox(
        color: Ks.paper,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Container(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 14),
            decoration: BoxDecoration(
              color: Ks.card,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: Ks.line),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Text('🌱', style: TextStyle(fontSize: 32)),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            trf("{n}'s week", '{n} का हफ़्ता', {'n': n}),
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                          if (dates.isNotEmpty)
                            Text(
                              dates,
                              style: const TextStyle(
                                color: Ks.muted,
                                fontSize: 15,
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  weeklyLine(w, name),
                  style: const TextStyle(
                    fontSize: 17,
                    height: 1.5,
                    color: Ks.ink,
                  ),
                ),
                const SizedBox(height: 16),
                _practice(w),
                if (w.voiceMinutes > 0) ...[
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      const Icon(
                        Icons.record_voice_over_rounded,
                        color: Ks.accent,
                        size: 22,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          trf(
                            'Talked with Saathi for {voiceMinutes} minutes',
                            'साथी के साथ {voiceMinutes} मिनट बात की', {'voiceMinutes': w.voiceMinutes},
                          ),
                          style: const TextStyle(fontSize: 16, color: Ks.ink),
                        ),
                      ),
                    ],
                  ),
                ],
                if (w.learned.isNotEmpty)
                  _section(
                    tr('Learned this week', 'इस हफ़्ते सीखा'),
                    Icons.star_rounded,
                    Ks.green,
                    Ks.greenSoft,
                    w.learned,
                  ),
                if (w.working.isNotEmpty)
                  _section(
                    tr('Working on', 'अभी सीख रहे हैं'),
                    Icons.trending_up_rounded,
                    Ks.amber,
                    Ks.amberSoft,
                    w.working,
                  ),
                if (w.next.isNotEmpty)
                  _section(
                    tr('Next', 'आगे सीखेंगे'),
                    Icons.flag_rounded,
                    Ks.accent,
                    Ks.accentSoft,
                    w.next,
                  ),
                if (t != null) _tip(t),
                const SizedBox(height: 14),
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: Text(
                    tr('Kaksha Saathi', 'कक्षा साथी'),
                    style: const TextStyle(
                      color: Ks.muted,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _practice(WeeklyData w) {
    final days = w.days;
    final labels = [for (var i = 0; i < 7; i++) tr(_daysEn[i], _daysHi[i])];
    final text = _practiceText(w.practiceDays);
    return Semantics(
      label: text,
      child: ExcludeSemantics(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.home_rounded, color: Ks.accent, size: 22),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    text,
                    style: const TextStyle(fontSize: 16, color: Ks.ink),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                for (var i = 0; i < 7; i++)
                  _dot(
                    days != null ? days.contains(i) : i < w.practiceDays,
                    // With only a count we don't know which days, so no weekday labels.
                    days != null ? labels[i] : null,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _dot(bool on, String? label) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 32,
        height: 32,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: on ? Ks.green : Ks.card,
          border: Border.all(color: on ? Ks.green : Ks.line, width: 2),
        ),
        child: on
            ? const Icon(Icons.check_rounded, color: Colors.white, size: 20)
            : null,
      ),
      if (label != null) ...[
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: Ks.muted, fontSize: 13)),
      ],
    ],
  );

  Widget _section(
    String label,
    IconData icon,
    Color fg,
    Color bg,
    List<Map<String, dynamic>> items,
  ) => Padding(
    padding: const EdgeInsets.only(top: 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(999),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 18, color: fg),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  color: fg,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 6),
        for (final m in items)
          Padding(
            padding: const EdgeInsetsDirectional.only(start: 6, top: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 9),
                  child: Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: fg,
                      shape: BoxShape.circle,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    cpTitle(m),
                    style: const TextStyle(fontSize: 16, color: Ks.ink),
                  ),
                ),
              ],
            ),
          ),
      ],
    ),
  );

  Widget _tip(Map<String, dynamic> t) {
    final explain = pick(t, 'explain').trim();
    final game = pick(t, 'game').trim();
    final example = (t['example'] ?? '').toString().trim();
    if (explain.isEmpty && game.isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Ks.accentSoft,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('💡 A tip for home', '💡 घर के लिए एक सुझाव'),
            style: const TextStyle(
              color: Ks.accent,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          if (explain.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(explain, style: const TextStyle(fontSize: 16, color: Ks.ink)),
          ],
          if (example.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              trf('Example: {example}', 'उदाहरण: {example}', {'example': example}),
              style: const TextStyle(
                fontSize: 15,
                color: Ks.ink,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          if (game.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              tr('🎲 1-minute game', '🎲 1 मिनट का खेल'),
              style: const TextStyle(
                color: Ks.accent,
                fontSize: 15,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 2),
            Text(game, style: const TextStyle(fontSize: 16, color: Ks.ink)),
          ],
        ],
      ),
    );
  }
}
