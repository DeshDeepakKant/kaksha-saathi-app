import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import 'journey_path.dart' show journeyGold;

/// "12 Oct" / "12 अक्टू" from an ISO date; '' when it can't be read.
String journeyShortDate(Object? iso) {
  final d = DateTime.tryParse((iso ?? '').toString());
  if (d == null) return '';
  const en = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  const hi = [
    'जन',
    'फ़र',
    'मार्च',
    'अप्रै',
    'मई',
    'जून',
    'जुला',
    'अग',
    'सित',
    'अक्टू',
    'नव',
    'दिस',
  ];
  return '${d.day} ${(Lang.isHi ? hi : en)[d.month - 1]}';
}

/// Small line of how many steps were learned by each of the last weeks (contract `growth`).
/// Drawn by hand: no chart package.
class JourneyGrowth extends StatelessWidget {
  const JourneyGrowth({super.key, required this.points});

  /// `[{week_end, learned}]`, oldest first.
  final List<Map<String, dynamic>> points;

  @override
  Widget build(BuildContext context) {
    final values = [
      for (final p in points) (p['learned'] as num?)?.round() ?? 0,
    ];
    final labels = [for (final p in points) journeyShortDate(p['week_end'])];
    final caption = tr('Learned steps by week', 'हर हफ़्ते तक सीखे गए कदम');
    final spoken = [
      for (var i = 0; i < values.length; i++) '${labels[i]}: ${values[i]}',
    ].join(', ');
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
        child: Semantics(
          label: '$caption. $spoken',
          excludeSemantics: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(Icons.trending_up_rounded, color: Ks.green),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      caption,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: Ks.ink,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              SizedBox(
                height: 104,
                child: CustomPaint(painter: _GrowthPainter(values)),
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  for (final l in labels)
                    Expanded(
                      child: Text(
                        l,
                        textAlign: TextAlign.center,
                        maxLines: 1,
                        overflow: TextOverflow.fade,
                        softWrap: false,
                        style: const TextStyle(fontSize: 12, color: Ks.muted),
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

class _GrowthPainter extends CustomPainter {
  _GrowthPainter(this.values);
  final List<int> values;

  @override
  void paint(Canvas canvas, Size size) {
    if (values.isEmpty) return;
    const top = 22.0; // room for the count above each dot
    const bottom = 8.0;
    final maxV = values.reduce((a, b) => a > b ? a : b).clamp(1, 1 << 30);
    final slot = size.width / values.length;
    final h = size.height - top - bottom;
    // Points sit in the middle of equal slots so the date row below lines up.
    final pts = [
      for (var i = 0; i < values.length; i++)
        Offset(slot * (i + 0.5), top + h - h * values[i] / maxV),
    ];

    final base = size.height - bottom;
    canvas.drawLine(
      Offset(0, base),
      Offset(size.width, base),
      Paint()
        ..color = Ks.line
        ..strokeWidth = 2,
    );

    if (pts.length > 1) {
      final area = Path()..moveTo(pts.first.dx, base);
      for (final p in pts) {
        area.lineTo(p.dx, p.dy);
      }
      area
        ..lineTo(pts.last.dx, base)
        ..close();
      canvas.drawPath(area, Paint()..color = Ks.greenSoft);

      final line = Path()..moveTo(pts.first.dx, pts.first.dy);
      for (final p in pts.skip(1)) {
        line.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(
        line,
        Paint()
          ..color = Ks.green
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..strokeJoin = StrokeJoin.round
          ..strokeCap = StrokeCap.round,
      );
    }

    for (var i = 0; i < pts.length; i++) {
      final last = i == pts.length - 1;
      canvas.drawCircle(pts[i], last ? 7 : 5, Paint()..color = Ks.green);
      canvas.drawCircle(
        pts[i],
        last ? 4 : 2.5,
        Paint()..color = last ? journeyGold : Ks.card,
      );
      final tp = TextPainter(
        text: TextSpan(
          text: '${values[i]}',
          style: TextStyle(
            fontSize: 12,
            fontWeight: last ? FontWeight.w800 : FontWeight.w600,
            color: Ks.ink,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, pts[i] - Offset(tp.width / 2, tp.height + 7));
      tp.dispose();
    }
  }

  @override
  bool shouldRepaint(_GrowthPainter old) => !listEquals(old.values, values);
}
