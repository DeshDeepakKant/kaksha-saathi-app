import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// Gold for learned stars; on the green node it is ~3.7:1 (non-text contrast needs 3:1).
const journeyGold = Color(0xFFFFC83D);

/// Parent-facing word for a milestone state (contract: learned / working / next / later).
String journeyStateLabel(String state) => switch (state) {
  'learned' => tr('Learned', 'सीख लिया'),
  'working' => tr('Working on it now', 'अभी इस पर काम चल रहा है'),
  'next' => tr('Next step', 'अगला कदम'),
  _ => tr('Later', 'बाद में'),
};

/// Chapter heading from the server's `chapter` (number, text or `{title_hi, title_en}`).
String journeyChapterLabel(Object? c) {
  if (c is Map) return cpTitle(c);
  final s = (c ?? '').toString().trim();
  if (s.isEmpty) return '';
  if (int.tryParse(s) != null) return tr('Chapter $s', 'अध्याय $s');
  return s;
}

/// The learning journey as a board-game trail: one node per milestone in roadmap order, grouped
/// by chapter, with the road coloured green where the child has already walked.
class JourneyPath extends StatelessWidget {
  const JourneyPath({
    super.key,
    required this.milestones,
    this.currentIndex,
    this.currentKey,
  });

  final List<Map<String, dynamic>> milestones;

  /// The milestone to highlight and scroll to (first "working", else first "next").
  final int? currentIndex;
  final GlobalKey? currentKey;

  static const _railWidth = 60.0;

  String _state(int i) => (milestones[i]['state'] ?? 'later').toString();
  bool _learned(int i) =>
      i >= 0 && i < milestones.length && _state(i) == 'learned';

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    String? lastChapter;
    for (var i = 0; i < milestones.length; i++) {
      final chapter = milestones[i]['chapter'];
      if (i == 0 || chapter?.toString() != lastChapter) {
        final label = journeyChapterLabel(chapter);
        if (label.isNotEmpty) {
          rows.add(
            _ChapterRow(
              label: label,
              railWidth: _railWidth,
              railDone: _learned(i - 1) && _learned(i),
              first: i == 0,
            ),
          );
        }
      }
      lastChapter = chapter?.toString();
      rows.add(
        _MilestoneRow(
          key: i == currentIndex ? currentKey : null,
          m: milestones[i],
          railWidth: _railWidth,
          topDone: _learned(i - 1) && _learned(i),
          bottomDone: _learned(i) && _learned(i + 1),
          isFirst: i == 0 && journeyChapterLabel(chapter).isEmpty,
          isLast: i == milestones.length - 1,
          current: i == currentIndex,
        ),
      );
    }
    rows.add(_FinishRow(railWidth: _railWidth));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: rows,
    );
  }
}

class _Rail extends StatelessWidget {
  const _Rail({required this.done, this.visible = true});
  final bool done;
  final bool visible;
  @override
  Widget build(BuildContext context) => Center(
    child: Container(
      width: 6,
      decoration: BoxDecoration(
        color: !visible ? Colors.transparent : (done ? Ks.green : Ks.line),
        borderRadius: BorderRadius.circular(3),
      ),
    ),
  );
}

class _ChapterRow extends StatelessWidget {
  const _ChapterRow({
    required this.label,
    required this.railWidth,
    required this.railDone,
    required this.first,
  });
  final String label;
  final double railWidth;
  final bool railDone;
  final bool first;

  @override
  Widget build(BuildContext context) => IntrinsicHeight(
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: railWidth,
          child: first
              ? const Center(child: Text('🚩', style: TextStyle(fontSize: 22)))
              : _Rail(done: railDone),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(4, 14, 0, 8),
            child: Semantics(
              header: true,
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: Ks.muted,
                  letterSpacing: 0.2,
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class _MilestoneRow extends StatelessWidget {
  const _MilestoneRow({
    super.key,
    required this.m,
    required this.railWidth,
    required this.topDone,
    required this.bottomDone,
    required this.isFirst,
    required this.isLast,
    required this.current,
  });

  final Map<String, dynamic> m;
  final double railWidth;
  final bool topDone;
  final bool bottomDone;
  final bool isFirst;
  final bool isLast;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final state = (m['state'] ?? 'later').toString();
    final title = cpTitle(m);
    final nipun = (m['nipun_ref'] ?? '').toString().trim();
    final (Color bg, Color border, Color fg) = switch (state) {
      'learned' => (Ks.card, Ks.line, Ks.green),
      'working' => (Ks.amberSoft, Ks.amber, Ks.amber),
      'next' => (Ks.accentSoft, Ks.accentSoft, Ks.accent),
      _ => (Ks.card, Ks.line, Ks.muted),
    };
    return MergeSemantics(
      child: Semantics(
        label: '$title. ${journeyStateLabel(state)}.',
        excludeSemantics: true,
        child: IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: railWidth,
                child: Column(
                  children: [
                    Expanded(
                      child: _Rail(done: topDone, visible: !isFirst),
                    ),
                    _Node(state: state, current: current),
                    Expanded(child: _Rail(done: bottomDone)),
                  ],
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 56),
                    padding: const EdgeInsets.fromLTRB(14, 10, 12, 10),
                    decoration: BoxDecoration(
                      color: bg,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        color: border,
                        width: state == 'working' ? 2 : 1,
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          title,
                          style: TextStyle(
                            fontSize: 16,
                            height: 1.35,
                            fontWeight: state == 'later'
                                ? FontWeight.w500
                                : FontWeight.w600,
                            color: state == 'later' ? Ks.muted : Ks.ink,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Wrap(
                          spacing: 8,
                          runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Text(
                              journeyStateLabel(state),
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w700,
                                color: fg,
                              ),
                            ),
                            if (nipun.isNotEmpty) _NipunChip(ref: nipun),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Node extends StatelessWidget {
  const _Node({required this.state, required this.current});
  final String state;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final size = current ? 46.0 : 38.0;
    final (
      Color fill,
      Color ring,
      IconData icon,
      Color iconColor,
    ) = switch (state) {
      'learned' => (Ks.green, Ks.green, Icons.star_rounded, journeyGold),
      'working' => (Ks.amberSoft, Ks.amber, Icons.star_half_rounded, Ks.amber),
      'next' => (Ks.card, Ks.accent, Icons.star_outline_rounded, Ks.accent),
      _ => (Ks.card, Ks.line, Icons.star_border_rounded, Ks.muted),
    };
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: fill,
        shape: BoxShape.circle,
        border: Border.all(color: ring, width: current ? 3 : 2),
        boxShadow: current
            ? const [
                BoxShadow(color: Ks.amberSoft, blurRadius: 0, spreadRadius: 5),
              ]
            : null,
      ),
      child: Icon(icon, color: iconColor, size: size * 0.62),
    );
  }
}

class _NipunChip extends StatelessWidget {
  const _NipunChip({required this.ref});
  final String ref;
  @override
  Widget build(BuildContext context) => Tooltip(
    message: 'NIPUN Bharat: $ref',
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: Ks.card,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Ks.accent),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.verified_rounded, size: 13, color: Ks.accent),
          SizedBox(width: 4),
          Text(
            'NIPUN',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Ks.accent,
            ),
          ),
        ],
      ),
    ),
  );
}

class _FinishRow extends StatelessWidget {
  const _FinishRow({required this.railWidth});
  final double railWidth;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 6),
    child: Row(
      children: [
        SizedBox(
          width: railWidth,
          child: const Center(
            child: Text('🏆', style: TextStyle(fontSize: 26)),
          ),
        ),
        Expanded(
          child: Text(
            tr('End of this year’s path', 'इस साल के रास्ते का अंत'),
            style: const TextStyle(color: Ks.muted, fontSize: 14),
          ),
        ),
      ],
    ),
  );
}
