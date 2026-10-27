import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// "Progress over time" card for one child: one stacked bar per week showing how many lessons were
/// on track / needed practice / needed attention at the end of that week, plus a plain-language
/// caption. [points] are the `points` of `GET /children/{id}/timeline`. Hides itself when there is
/// too little data to say anything (fewer than two weeks, or nothing assessed yet).
class TrendCard extends StatelessWidget {
  const TrendCard({super.key, required this.points});
  final List<Map<String, dynamic>> points;

  static int _n(Map<String, dynamic> p, String k) =>
      (p[k] as num?)?.toInt() ?? 0;

  @override
  Widget build(BuildContext context) {
    if (points.length < 2 || points.every((p) => _n(p, 'assessed') == 0)) {
      return const SizedBox.shrink();
    }
    final first = _n(points.first, 'on_track');
    final last = _n(points.last, 'on_track');
    final weeks = points.length;
    final needsFirst =
        _n(points.first, 'needs_practice') +
        _n(points.first, 'needs_intervention');
    final needsLast =
        _n(points.last, 'needs_practice') +
        _n(points.last, 'needs_intervention');
    final caption = first == last
        ? tr(
            'On track: $last lessons, no change in $weeks weeks',
            'ठीक चल रहे: $last सबक, $weeks हफ़्तों में कोई बदलाव नहीं',
          )
        : tr(
            'On track: $first → $last in $weeks weeks',
            'ठीक चल रहे: $first → $last, $weeks हफ़्तों में',
          );
    final caption2 = tr(
      'Needing help: $needsFirst → $needsLast',
      'मदद चाहिए: $needsFirst → $needsLast',
    );
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Semantics(
          label: '$caption. $caption2',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                caption,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: Ks.green,
                ),
              ),
              Text(
                caption2,
                style: const TextStyle(fontSize: 13, color: Ks.muted),
              ),
              const SizedBox(height: 10),
              ExcludeSemantics(
                child: SizedBox(
                  height: 110,
                  width: double.infinity,
                  child: CustomPaint(painter: _TrendPainter(points)),
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 14,
                runSpacing: 4,
                children: [
                  _legend(Ks.green, tr('Doing well', 'ठीक चल रहा है')),
                  _legend(Ks.amber, tr('Needs practice', 'अभ्यास चाहिए')),
                  _legend(Ks.rose, tr('Needs attention', 'ध्यान चाहिए')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _legend(Color c, String label) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(
          color: c,
          borderRadius: BorderRadius.circular(3),
        ),
      ),
      const SizedBox(width: 5),
      Text(label, style: const TextStyle(fontSize: 12, color: Ks.muted)),
    ],
  );
}

class _TrendPainter extends CustomPainter {
  _TrendPainter(this.points);
  final List<Map<String, dynamic>> points;

  static const _labelH = 16.0;

  int _n(Map<String, dynamic> p, String k) => (p[k] as num?)?.toInt() ?? 0;

  @override
  void paint(Canvas canvas, Size size) {
    final chartH = size.height - _labelH;
    var maxV = 1;
    for (final p in points) {
      final t =
          _n(p, 'on_track') +
          _n(p, 'needs_practice') +
          _n(p, 'needs_intervention');
      if (t > maxV) maxV = t;
    }
    final slot = size.width / points.length;
    final barW = (slot * 0.56).clamp(8.0, 40.0);
    final base = Paint()..color = Ks.line;
    canvas.drawRect(Rect.fromLTWH(0, chartH, size.width, 1), base);
    for (var i = 0; i < points.length; i++) {
      final p = points[i];
      final x = slot * i + (slot - barW) / 2;
      var y = chartH;
      final segs = [
        (_n(p, 'on_track'), Ks.green),
        (_n(p, 'needs_practice'), Ks.amber),
        (_n(p, 'needs_intervention'), Ks.rose),
      ];
      for (final s in segs) {
        if (s.$1 <= 0) continue;
        final h = chartH * 0.92 * s.$1 / maxV;
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromLTWH(x, y - h, barW, h - 1),
            const Radius.circular(3),
          ),
          Paint()..color = s.$2,
        );
        y -= h;
      }
      final d = DateTime.tryParse('${p['week_end'] ?? ''}');
      final tp = TextPainter(
        text: TextSpan(
          text: d == null ? '' : '${d.day}/${d.month}',
          style: const TextStyle(fontSize: 11, color: Ks.muted),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(slot * i + (slot - tp.width) / 2, chartH + 3));
    }
  }

  @override
  bool shouldRepaint(_TrendPainter old) => old.points != points;
}
