import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';

/// Home cards for the parent insights (docs/parent_insights_contract.md): this week at school,
/// teacher-noticed moments, mistake tips and the links to Journey / Weekly. Each card takes the
/// server map as given and reads its text aloud; none of them shows scores or group labels.

/// Voice for [text]: Devanagari is always read in Hindi (a missing English field falls back to
/// Hindi), anything else follows the app language.
String speechLang(String text) =>
    RegExp(r'[ऀ-ॿ]').hasMatch(text) ? 'hi' : (Lang.isHi ? 'hi' : 'en');

/// [text] without a leading emoji (server lines start with ⭐ / 🌱; the card already shows one,
/// and some voices read the emoji name aloud).
String plainLine(String text) =>
    text.replaceFirst(RegExp(r'^[^\p{L}\p{N}“"]+', unicode: true), '').trim();

/// "Listen" / "Stop" button. Only one card speaks at a time; starting another stops the first.
class ReadAloudButton extends StatefulWidget {
  const ReadAloudButton({
    super.key,
    required this.text,
    this.color = Ks.accent,
  });
  final String text;
  final Color color;
  @override
  State<ReadAloudButton> createState() => _ReadAloudButtonState();
}

class _ReadAloudButtonState extends State<ReadAloudButton> {
  /// The button that is speaking now, if any.
  static final ValueNotifier<Object?> _speaking = ValueNotifier(null);

  @override
  void initState() {
    super.initState();
    _speaking.addListener(_changed);
  }

  @override
  void dispose() {
    _speaking.removeListener(_changed);
    if (_speaking.value == this) {
      _speaking.value = null;
      Speak.stop();
    }
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  Future<void> _toggle() async {
    if (_speaking.value == this) {
      _speaking.value = null;
      await Speak.stop();
      return;
    }
    _speaking.value = this;
    final text = plainLine(widget.text);
    await Speak.say(text, speechLang(text));
    if (_speaking.value == this) _speaking.value = null;
  }

  @override
  Widget build(BuildContext context) {
    final on = _speaking.value == this;
    return OutlinedButton.icon(
      onPressed: widget.text.trim().isEmpty ? null : _toggle,
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 48),
        foregroundColor: widget.color,
        backgroundColor: Colors.white,
        side: BorderSide(color: widget.color.withValues(alpha: 0.5)),
        padding: const EdgeInsets.symmetric(horizontal: 16),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
      icon: Icon(on ? Icons.stop_rounded : Icons.volume_up_rounded, size: 22),
      label: Text(on ? tr('Stop', 'रोकें') : tr('Listen', 'सुनें')),
    );
  }
}

/// Small rounded label (topic, example). [mono] uses a fixed-width face for worked examples.
class InsightChip extends StatelessWidget {
  const InsightChip(
    this.text, {
    super.key,
    this.icon,
    this.color = Ks.accent,
    this.background = Ks.accentSoft,
    this.mono = false,
  });
  final String text;
  final IconData? icon;
  final Color color;
  final Color background;
  final bool mono;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
    decoration: BoxDecoration(
      color: background,
      borderRadius: BorderRadius.circular(10),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (icon != null) ...[
          Icon(icon, size: 17, color: color),
          const SizedBox(width: 6),
        ],
        Flexible(
          child: Text(
            text,
            style: TextStyle(
              color: color,
              fontSize: mono ? 16 : 15,
              fontWeight: FontWeight.w600,
              fontFamily: mono ? 'monospace' : null,
              fontFamilyFallback: mono ? const ['NotoSansDevanagari'] : null,
            ),
          ),
        ),
      ],
    ),
  );
}

/// Shared card frame: emoji, heading, optional close button, body.
class _InsightFrame extends StatelessWidget {
  const _InsightFrame({
    required this.emoji,
    required this.title,
    required this.children,
    this.color = Ks.card,
    this.onDismiss,
  });
  final String emoji;
  final String title;
  final List<Widget> children;
  final Color color;
  final VoidCallback? onDismiss;
  @override
  Widget build(BuildContext context) => Card(
    color: color,
    margin: const EdgeInsets.only(bottom: 12),
    child: Padding(
      padding: EdgeInsetsDirectional.fromSTEB(16, 14, onDismiss == null ? 16 : 4, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ExcludeSemantics(
                child: Text(emoji, style: const TextStyle(fontSize: 26)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              if (onDismiss != null)
                IconButton(
                  onPressed: onDismiss,
                  tooltip: tr('Hide this', 'इसे हटाएँ'),
                  icon: const Icon(Icons.close_rounded, color: Ks.muted),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Padding(
            padding: EdgeInsetsDirectional.only(end: onDismiss == null ? 0 : 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: children,
            ),
          ),
        ],
      ),
    ),
  );
}

String _chapterTitle(Map t) {
  final ch = t['chapter'];
  final title = cpTitle(t);
  if (ch == null || '$ch'.trim().isEmpty) return title;
  return '${tr('Chapter', 'अध्याय')} $ch · $title';
}

/// "This week at school": the server's one-line summary, the class topic and read-aloud.
class SchoolWeekCard extends StatelessWidget {
  const SchoolWeekCard(this.week, {super.key});
  final Map<String, dynamic> week;

  /// Whether the card has anything to show (the contract sends both topics null when unknown).
  static bool hasContent(Map<String, dynamic>? w) =>
      w != null && (w['class_topic'] is Map || w['child_focus'] is Map);

  @override
  Widget build(BuildContext context) {
    final topic =
        (week['class_topic'] ?? week['child_focus']) as Map? ?? const {};
    final chip = _chapterTitle(topic);
    var line = pick(week, 'line').trim();
    if (line.isEmpty) line = chip;
    return _InsightFrame(
      emoji: '🏫',
      title: tr('This week at school', 'इस हफ़्ते स्कूल में'),
      children: [
        Text(line, style: const TextStyle(fontSize: 18, height: 1.5)),
        if (chip.isNotEmpty && chip != line) ...[
          const SizedBox(height: 10),
          InsightChip(chip, icon: Icons.menu_book_rounded),
        ],
        const SizedBox(height: 12),
        ReadAloudButton(text: line),
      ],
    );
  }
}

/// Quiet stand-in while "This week at school" loads, so Home does not wait for it.
class SchoolWeekPlaceholder extends StatelessWidget {
  const SchoolWeekPlaceholder({super.key});
  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 12),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(
              strokeWidth: 2.5,
              color: Ks.accent,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              tr(
                'Checking what the class is learning…',
                'देख रहे हैं कि कक्षा में क्या पढ़ाया जा रहा है…',
              ),
              style: const TextStyle(color: Ks.muted),
            ),
          ),
        ],
      ),
    ),
  );
}

/// A lesson the child has learned or is getting better at, as the teacher recorded it.
class CelebrationCard extends StatelessWidget {
  const CelebrationCard(this.moment, {super.key, this.onDismiss});
  final Map<String, dynamic> moment;
  final VoidCallback? onDismiss;
  @override
  Widget build(BuildContext context) {
    final better = moment['move'] == 'getting_better';
    var line = plainLine(pick(moment, 'line'));
    if (line.isEmpty) line = cpTitle(moment);
    return _InsightFrame(
      emoji: better ? '🌱' : '⭐',
      title: better
          ? tr('Getting better', 'पकड़ बढ़ रही है')
          : tr('Well done!', 'शाबाश!'),
      color: Ks.amberSoft,
      onDismiss: onDismiss,
      children: [
        Text(line, style: const TextStyle(fontSize: 18, height: 1.5)),
        const SizedBox(height: 12),
        ReadAloudButton(text: line, color: Ks.amber),
      ],
    );
  }
}

/// A school day the child missed: the server's gentle line, what the class did and the 5-minute
/// home version (numbered steps, materials).
class CatchUpCard extends StatelessWidget {
  const CatchUpCard(this.moment, {super.key, this.onDismiss});
  final Map<String, dynamic> moment;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final act = (moment['activity'] as Map?)?.cast<String, dynamic>();
    final classDid = pick(moment, 'class_did').trim();
    final line = pick(moment, 'line').trim();
    List<String> stepsIn(String key) => ((act?[key] as List?) ?? const [])
        .map((s) => '$s'.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final hiSteps = stepsIn('steps_hi');
    final enSteps = Lang.isHi ? const <String>[] : stepsIn('steps_en');
    final steps = enSteps.isNotEmpty ? enSteps : hiSteps;
    final materials = act == null ? '' : pick(act, 'materials').trim();
    final actTitle = act == null ? '' : cpTitle(act);
    final minutes = (act?['minutes'] as num?)?.toInt() ?? 5;

    final speech = [
      if (line.isNotEmpty) line,
      if (classDid.isNotEmpty) classDid,
      if (actTitle.isNotEmpty) '$actTitle.',
      if (materials.isNotEmpty) '${tr('You need', 'चाहिए')}: $materials.',
      for (var i = 0; i < steps.length; i++) '${i + 1}. ${steps[i]}',
    ].join(' ');

    return _InsightFrame(
      emoji: '🌱',
      title: tr('Catch up at home', 'घर पर छूटा काम'),
      color: Ks.accentSoft,
      onDismiss: onDismiss,
      children: [
        if (line.isNotEmpty)
          Text(
            line,
            style: const TextStyle(
              fontSize: 18,
              height: 1.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        if (classDid.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(classDid, style: const TextStyle(fontSize: 16, height: 1.45)),
        ],
        if (act != null) ...[
          const SizedBox(height: 12),
          Row(
            children: [
              const Icon(Icons.timer_outlined, size: 20, color: Ks.accent),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  actTitle.isEmpty
                      ? trf(
                          '{minutes}-minute home version',
                          'घर पर {minutes} मिनट का तरीका', {'minutes': minutes},
                        )
                      : trf(
                          '{minutes}-minute home version: {actTitle}',
                          'घर पर {minutes} मिनट: {actTitle}', {'minutes': minutes, 'actTitle': actTitle},
                        ),
                  style: const TextStyle(
                    color: Ks.accent,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          if (materials.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '${tr('You need', 'चाहिए')}: $materials',
              style: const TextStyle(fontSize: 16),
            ),
          ],
          const SizedBox(height: 6),
          for (var i = 0; i < steps.length; i++)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 26,
                    height: 26,
                    alignment: Alignment.center,
                    decoration: const BoxDecoration(
                      color: Ks.accent,
                      shape: BoxShape.circle,
                    ),
                    child: Text(
                      '${i + 1}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      steps[i],
                      style: const TextStyle(fontSize: 17, height: 1.45),
                    ),
                  ),
                ],
              ),
            ),
        ],
        const SizedBox(height: 12),
        ReadAloudButton(text: speech),
      ],
    );
  }
}

/// One mistake the teacher saw: what the child does, a worked example, a 1-minute game.
class TipCard extends StatelessWidget {
  const TipCard(this.tip, {super.key});
  final Map<String, dynamic> tip;
  @override
  Widget build(BuildContext context) {
    final explain = pick(tip, 'explain').trim();
    final game = pick(tip, 'game').trim();
    final example = '${tip['example'] ?? ''}'.trim();
    final title = cpTitle(tip).trim();
    return _InsightFrame(
      emoji: '💡',
      title: title.isEmpty ? tr('A small mistake', 'एक छोटी गलती') : title,
      children: [
        if (explain.isNotEmpty)
          Text(explain, style: const TextStyle(fontSize: 17, height: 1.5)),
        if (example.isNotEmpty) ...[
          const SizedBox(height: 8),
          InsightChip(
            example,
            mono: true,
            color: Ks.ink,
            background: const Color(0xFFF1EEE7),
          ),
        ],
        if (game.isNotEmpty) ...[
          const SizedBox(height: 12),
          Row(
            children: [
              const Icon(Icons.extension_rounded, size: 20, color: Ks.accent),
              const SizedBox(width: 6),
              Text(
                tr('1-minute game', '1 मिनट का खेल'),
                style: const TextStyle(
                  color: Ks.accent,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(game, style: const TextStyle(fontSize: 17, height: 1.5)),
          const SizedBox(height: 12),
          ReadAloudButton(text: game),
        ],
      ],
    );
  }
}

/// Large tappable row that opens another insights screen.
class InsightLinkTile extends StatelessWidget {
  const InsightLinkTile({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 10),
    clipBehavior: Clip.antiAlias,
    child: InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 64),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: Ks.accentSoft,
                child: Icon(icon, color: Ks.accent),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: Ks.muted),
            ],
          ),
        ),
      ),
    ),
  );
}
