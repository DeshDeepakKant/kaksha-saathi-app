import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

// Shared pieces of the syllabus screen: topic classification, the stacked progress bar,
// the counts line, the legend, chapter cards, topic rows and the topic bottom sheet.

/// Colours that are readable on white. `Ks.amber` is only ~2:1 as text, so amber text uses
/// [amberText] (>= 4.5:1) and amber fills use [amberBar] (>= 3:1 against white).
class SylColors {
  static const amberText = Color(0xFF8A5A00);
  static const amberBar = Color(0xFFB77A12);
  static const greyBar = Color(0xFF8A9694);
  static const track = Color(0xFFEFEBE2);
}

int sylInt(dynamic v) => v is num ? v.toInt() : 0;

List<Map<String, dynamic>> sylMaps(dynamic v) => v is List
    ? v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
    : <Map<String, dynamic>>[];

/// One place that defines how a topic is classified, used by the totals, the filter chips and
/// the topic state chip:
///  - done: `pct_done >= 0.8` (80% or more of the class is on track),
///  - in progress: not done, but at least one child has evidence (any status but not_started),
///  - not started: no child has evidence yet.
enum TopicState { done, inProgress, notStarted }

const sylDoneThreshold = 0.8;

class SylCounts {
  const SylCounts(
    this.onTrack,
    this.practice,
    this.struggling,
    this.notStarted,
  );
  final int onTrack;
  final int practice;
  final int struggling;
  final int notStarted;

  factory SylCounts.of(Map<String, dynamic> topic) {
    final c = topic['counts'];
    if (c is! Map) return const SylCounts(0, 0, 0, 0);
    return SylCounts(
      sylInt(c['on_track']),
      sylInt(c['needs_practice']),
      sylInt(c['needs_intervention']),
      sylInt(c['not_started']),
    );
  }

  int get total => onTrack + practice + struggling + notStarted;
  int get started => onTrack + practice + struggling;

  SylCounts operator +(SylCounts o) => SylCounts(
    onTrack + o.onTrack,
    practice + o.practice,
    struggling + o.struggling,
    notStarted + o.notStarted,
  );
}

double sylPctDone(Map<String, dynamic> topic) {
  final c = SylCounts.of(topic);
  final raw = topic['pct_done'];
  if (raw is num) {
    final v = raw.toDouble();
    return v > 1 ? v / 100 : v; // tolerate a 0-100 scale
  }
  return c.total == 0 ? 0 : c.onTrack / c.total;
}

TopicState sylTopicState(Map<String, dynamic> topic) {
  final c = SylCounts.of(topic);
  if (c.total > 0 && sylPctDone(topic) >= sylDoneThreshold) {
    return TopicState.done;
  }
  final assessed = sylInt(topic['assessed']);
  if (c.started > 0 || assessed > 0) return TopicState.inProgress;
  return TopicState.notStarted;
}

String sylStateLabel(TopicState s) => switch (s) {
  TopicState.done => tr('Done', 'पूरा'),
  TopicState.inProgress => tr('In progress', 'चल रहा है'),
  TopicState.notStarted => tr('Not started', 'शुरू नहीं'),
};

IconData sylStateIcon(TopicState s) => switch (s) {
  TopicState.done => Icons.check_circle_rounded,
  TopicState.inProgress => Icons.timelapse_rounded,
  TopicState.notStarted => Icons.circle_outlined,
};

/// Icon colour for a state (icons are decoration; the label always carries the meaning).
Color sylStateColor(TopicState s) => switch (s) {
  TopicState.done => Ks.green,
  TopicState.inProgress => SylColors.amberBar,
  TopicState.notStarted => SylColors.greyBar,
};

Color sylSegmentColor(String status) => switch (status) {
  'on_track' => Ks.green,
  'needs_practice' => SylColors.amberBar,
  'needs_intervention' => Ks.rose,
  _ => SylColors.greyBar,
};

String sylChapterName(String? raw) {
  final s = (raw ?? '').trim();
  return s.isEmpty ? tr('Other topics', 'अन्य विषय') : s;
}

/// "8 done · 3 practising · 2 struggling · 17 not started" as plain text (for screen readers).
String sylCountsText(SylCounts c) => [
  trf('{onTrack} done', '{onTrack} पूरा', {'onTrack': c.onTrack}),
  trf('{practice} practising', '{practice} अभ्यास में', {'practice': c.practice}),
  trf('{struggling} struggling', '{struggling} कठिनाई में', {'struggling': c.struggling}),
  trf('{notStarted} not started', '{notStarted} शुरू नहीं', {'notStarted': c.notStarted}),
].join(' · ');

/// Stacked bar: on track (green), needs practice (amber), needs attention (red), not started (grey).
class SylStackedBar extends StatelessWidget {
  const SylStackedBar({super.key, required this.counts, this.height = 10});
  final SylCounts counts;
  final double height;

  @override
  Widget build(BuildContext context) {
    final parts = <(String, int)>[
      ('on_track', counts.onTrack),
      ('needs_practice', counts.practice),
      ('needs_intervention', counts.struggling),
      ('not_started', counts.notStarted),
    ].where((p) => p.$2 > 0).toList();
    final children = <Widget>[];
    for (var i = 0; i < parts.length; i++) {
      if (i > 0) children.add(Container(width: 2, color: Ks.card));
      children.add(
        Expanded(
          flex: parts[i].$2,
          child: Container(color: sylSegmentColor(parts[i].$1)),
        ),
      );
    }
    return Semantics(
      label: sylCountsText(counts),
      child: ExcludeSemantics(
        child: ClipRRect(
          borderRadius: BorderRadius.circular(height),
          child: SizedBox(
            height: height,
            child: parts.isEmpty
                ? Container(color: SylColors.track)
                : Row(children: children),
          ),
        ),
      ),
    );
  }
}

/// The four numbers with a status icon each, so colour is never the only signal.
class SylCountsLine extends StatelessWidget {
  const SylCountsLine({super.key, required this.counts, this.size = 14});
  final SylCounts counts;
  final double size;

  @override
  Widget build(BuildContext context) {
    Widget item(String status, String text) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          Ks.statusIcon[status],
          size: size + 2,
          color: sylSegmentColor(status),
        ),
        const SizedBox(width: 4),
        Text(
          text,
          style: TextStyle(fontSize: size, color: Ks.ink, height: 1.2),
        ),
      ],
    );
    return Wrap(
      spacing: 12,
      runSpacing: 4,
      children: [
        item(
          'on_track',
          trf('{onTrack} done', '{onTrack} पूरा', {'onTrack': counts.onTrack}),
        ),
        item(
          'needs_practice',
          trf('{practice} practising', '{practice} अभ्यास में', {'practice': counts.practice}),
        ),
        item(
          'needs_intervention',
          trf(
            '{struggling} struggling',
            '{struggling} कठिनाई में', {'struggling': counts.struggling},
          ),
        ),
        item(
          'not_started',
          trf(
            '{notStarted} not started',
            '{notStarted} शुरू नहीं', {'notStarted': counts.notStarted},
          ),
        ),
      ],
    );
  }
}

class SylTag extends StatelessWidget {
  const SylTag(this.text, {super.key, this.icon, this.bg, this.fg = Ks.ink});
  final String text;
  final IconData? icon;
  final Color? bg;
  final Color fg;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(
      color: bg ?? Ks.statusBg['not_started'],
      borderRadius: BorderRadius.circular(999),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 14, color: fg),
          const SizedBox(width: 4),
        ],
        Flexible(
          child: Text(
            text,
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              color: fg,
              height: 1.2,
            ),
          ),
        ),
      ],
    ),
  );
}

/// Explains the three topic states and the bar colours.
class SylLegend extends StatelessWidget {
  const SylLegend({super.key});

  @override
  Widget build(BuildContext context) {
    Widget row(TopicState s, String text) => Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(sylStateIcon(s), size: 17, color: sylStateColor(s)),
          const SizedBox(width: 6),
          Expanded(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '${sylStateLabel(s)}: ',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  TextSpan(text: text),
                ],
              ),
              style: const TextStyle(
                fontSize: 13.5,
                color: Ks.ink,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Ks.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Ks.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          row(
            TopicState.done,
            tr(
              '80% or more of the children are on track.',
              'कम से कम 80% बच्चे ठीक चल रहे हैं।',
            ),
          ),
          row(
            TopicState.inProgress,
            tr(
              'some children have been checked.',
              'कुछ बच्चों की जाँच हो चुकी है।',
            ),
          ),
          row(
            TopicState.notStarted,
            tr(
              'no child has been checked yet.',
              'अभी किसी बच्चे की जाँच नहीं हुई।',
            ),
          ),
          const SizedBox(height: 4),
          Text(
            tr(
              'Bar: green on track, amber practising, red struggling, grey not started.',
              'पट्टी: हरा ठीक, पीला अभ्यास में, लाल कठिनाई में, स्लेटी शुरू नहीं।',
            ),
            style: const TextStyle(
              fontSize: 12.5,
              color: Ks.muted,
              height: 1.3,
            ),
          ),
        ],
      ),
    );
  }
}

/// Small "Done / In progress / Not started" label with an icon.
class SylStateTag extends StatelessWidget {
  const SylStateTag(this.state, {super.key});
  final TopicState state;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(sylStateIcon(state), size: 16, color: sylStateColor(state)),
      const SizedBox(width: 4),
      Text(
        sylStateLabel(state),
        style: const TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: Ks.ink,
        ),
      ),
    ],
  );
}

String sylNipun(Map<String, dynamic> topic) {
  final n = topic['nipun_ref'];
  if (n == null) return '';
  final s = n.toString().trim();
  return s;
}

List<Widget> sylTopicTags(Map<String, dynamic> topic) {
  final nipun = sylNipun(topic);
  return [
    if (nipun.isNotEmpty)
      SylTag(
        'NIPUN $nipun',
        icon: Icons.flag_rounded,
        bg: Ks.accentSoft,
        fg: Ks.accent,
      ),
    if (topic['custom'] == true)
      SylTag(
        tr('Custom', 'अपना जोड़ा'),
        icon: Icons.edit_note_rounded,
        bg: Ks.amberSoft,
        fg: SylColors.amberText,
      ),
  ];
}

class SylTopicTile extends StatelessWidget {
  const SylTopicTile({super.key, required this.topic, required this.onTap});
  final Map<String, dynamic> topic;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final counts = SylCounts.of(topic);
    final state = sylTopicState(topic);
    final tags = sylTopicTags(topic);
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 12, 12, 12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    cpTitle(topic),
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Ks.ink,
                      height: 1.3,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [SylStateTag(state), ...tags],
                  ),
                  const SizedBox(height: 8),
                  SylStackedBar(counts: counts),
                  const SizedBox(height: 8),
                  if (counts.total == 0)
                    Text(
                      tr(
                        'No children in this class yet.',
                        'इस कक्षा में अभी कोई बच्चा नहीं।',
                      ),
                      style: const TextStyle(fontSize: 13.5, color: Ks.muted),
                    )
                  else
                    SylCountsLine(counts: counts),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: Ks.muted),
          ],
        ),
      ),
    );
  }
}

/// A chapter: header with the combined bar, topics shown when [open].
class SylChapterCard extends StatelessWidget {
  const SylChapterCard({
    super.key,
    required this.name,
    required this.topics,
    required this.open,
    required this.onToggle,
    required this.onTopicTap,
  });
  final String name;
  final List<Map<String, dynamic>> topics;
  final bool open;
  final VoidCallback onToggle;
  final void Function(Map<String, dynamic>) onTopicTap;

  @override
  Widget build(BuildContext context) {
    var counts = const SylCounts(0, 0, 0, 0);
    var done = 0;
    for (final t in topics) {
      counts = counts + SylCounts.of(t);
      if (sylTopicState(t) == TopicState.done) done++;
    }
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Semantics(
            button: true,
            expanded: open,
            child: InkWell(
              onTap: onToggle,
              child: Padding(
                padding: const EdgeInsetsDirectional.fromSTEB(16, 12, 8, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            sylChapterName(name),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 2),
                          Text(
                            trf(
                              '{done} of {topicsCount} topics done',
                              '{topicsCount} में से {done} विषय पूरे', {'done': done, 'topicsCount': topics.length},
                            ),
                            style: const TextStyle(
                              fontSize: 13.5,
                              color: Ks.muted,
                            ),
                          ),
                          const SizedBox(height: 8),
                          SylStackedBar(counts: counts, height: 8),
                        ],
                      ),
                    ),
                    Icon(
                      open
                          ? Icons.expand_less_rounded
                          : Icons.expand_more_rounded,
                      color: Ks.muted,
                      size: 28,
                    ),
                  ],
                ),
              ),
            ),
          ),
          if (open)
            for (final t in topics) ...[
              const Divider(height: 1, color: Ks.line),
              SylTopicTile(topic: t, onTap: () => onTopicTap(t)),
            ],
        ],
      ),
    );
  }
}

/// Bottom sheet for one topic. Pops with `'check'`, `'up'`, `'down'`, or (custom topics only)
/// `'rename'` / `'remove'`. [canMoveUp] / [canMoveDown] are false at the ends of the chapter.
class SylTopicSheet extends StatelessWidget {
  const SylTopicSheet({
    super.key,
    required this.topic,
    required this.chapter,
    this.canMoveUp = false,
    this.canMoveDown = false,
  });
  final Map<String, dynamic> topic;
  final String chapter;
  final bool canMoveUp;
  final bool canMoveDown;

  @override
  Widget build(BuildContext context) {
    final counts = SylCounts.of(topic);
    final state = sylTopicState(topic);
    final pct = (sylPctDone(topic) * 100).round();
    final custom = topic['custom'] == true;

    Widget line(String status, String label, int n) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(Ks.statusIcon[status], size: 22, color: sylSegmentColor(status)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontSize: 16, color: Ks.ink),
            ),
          ),
          Text(
            '$n',
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Ks.ink,
            ),
          ),
        ],
      ),
    );

    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              sylChapterName(chapter),
              style: const TextStyle(fontSize: 13.5, color: Ks.muted),
            ),
            const SizedBox(height: 2),
            Text(cpTitle(topic), style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [SylStateTag(state), ...sylTopicTags(topic)],
            ),
            const SizedBox(height: 14),
            SylStackedBar(counts: counts, height: 12),
            const SizedBox(height: 10),
            if (counts.total == 0)
              Text(
                tr(
                  'No children in this class yet.',
                  'इस कक्षा में अभी कोई बच्चा नहीं।',
                ),
                style: const TextStyle(color: Ks.muted),
              )
            else ...[
              line(
                'on_track',
                tr('Done (on track)', 'पूरा (ठीक चल रहा है)'),
                counts.onTrack,
              ),
              line(
                'needs_practice',
                tr('Practising', 'अभ्यास में'),
                counts.practice,
              ),
              line(
                'needs_intervention',
                tr('Struggling', 'कठिनाई में'),
                counts.struggling,
              ),
              line(
                'not_started',
                tr('Not started', 'शुरू नहीं'),
                counts.notStarted,
              ),
              const SizedBox(height: 4),
              Text(
                trf(
                  '{pct}% of {total} children are on track.',
                  '{total} में से {pct}% बच्चे ठीक चल रहे हैं।', {'pct': pct, 'total': counts.total},
                ),
                style: const TextStyle(fontSize: 14, color: Ks.muted),
              ),
            ],
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: () => Navigator.pop(context, 'check'),
              icon: const Icon(Icons.fact_check_rounded),
              label: Text(tr('Check now', 'अभी जाँचें')),
            ),
            const SizedBox(height: 10),
            // Order within the chapter (the order the topics are taught in).
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: canMoveUp
                        ? () => Navigator.pop(context, 'up')
                        : null,
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(0, 52),
                    ),
                    icon: const Icon(Icons.arrow_upward_rounded),
                    label: Text(tr('Move up', 'ऊपर करें')),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: canMoveDown
                        ? () => Navigator.pop(context, 'down')
                        : null,
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(0, 52),
                    ),
                    icon: const Icon(Icons.arrow_downward_rounded),
                    label: Text(tr('Move down', 'नीचे करें')),
                  ),
                ),
              ],
            ),
            if (custom) ...[
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => Navigator.pop(context, 'rename'),
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(0, 52),
                      ),
                      icon: const Icon(Icons.edit_rounded),
                      label: Text(tr('Rename', 'नाम बदलें')),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => Navigator.pop(context, 'remove'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: Ks.rose,
                        minimumSize: const Size(0, 52),
                      ),
                      icon: const Icon(Icons.delete_outline_rounded),
                      label: Text(tr('Remove', 'हटाएँ')),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
