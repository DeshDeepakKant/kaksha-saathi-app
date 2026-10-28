import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// Per-word reading status colours (assess.py: correct | close | wrong | missed | extra).
Color voiceWordColor(String? status) => switch (status) {
  'correct' => Ks.green,
  'close' => Ks.amber,
  'wrong' || 'missed' => Ks.rose,
  'extra' => Ks.muted,
  _ => Ks.ink,
};

List<Map<String, dynamic>> voiceWords(dynamic words) =>
    ((words as List?) ?? const [])
        .whereType<Map>()
        .map((w) => w.cast<String, dynamic>())
        .toList();

/// Words as one paragraph, each coloured by its status. [useHeard] shows what the child said
/// (missed words appear struck through in the target spelling); otherwise the target words.
class VoiceWordsText extends StatelessWidget {
  const VoiceWordsText({
    super.key,
    required this.words,
    required this.style,
    this.useHeard = false,
    this.textAlign = TextAlign.start,
  });
  final List<Map<String, dynamic>> words;
  final TextStyle style;
  final bool useHeard;
  final TextAlign textAlign;

  @override
  Widget build(BuildContext context) {
    final spans = <TextSpan>[];
    for (final w in words) {
      final status = w['status'] as String?;
      if (!useHeard && status == 'extra') continue;
      final heard = (w['heard'] ?? '').toString();
      final target = (w['target'] ?? '').toString();
      final missed = status == 'missed' || (useHeard && heard.isEmpty);
      final text = useHeard && heard.isNotEmpty ? heard : target;
      if (text.isEmpty) continue;
      if (spans.isNotEmpty) spans.add(const TextSpan(text: ' '));
      spans.add(
        TextSpan(
          text: text,
          style: TextStyle(
            color: voiceWordColor(status),
            fontWeight: status == 'correct' ? FontWeight.w700 : null,
            decoration: missed
                ? (useHeard
                      ? TextDecoration.lineThrough
                      : TextDecoration.underline)
                : null,
            decorationColor: Ks.rose,
            decorationThickness: 2,
          ),
        ),
      );
    }
    return Text.rich(
      TextSpan(style: style, children: spans),
      textAlign: textAlign,
    );
  }
}

/// Small legend so the colours are never the only signal.
class VoiceWordsLegend extends StatelessWidget {
  const VoiceWordsLegend({super.key});
  @override
  Widget build(BuildContext context) {
    Widget dot(Color c, String label) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(color: c, shape: BoxShape.circle),
        ),
        const SizedBox(width: 5),
        Text(label, style: TextStyle(fontSize: 13, color: c)),
      ],
    );
    return Wrap(
      spacing: 14,
      runSpacing: 4,
      alignment: WrapAlignment.center,
      children: [
        dot(Ks.green, tr('read right', 'सही पढ़ा')),
        dot(Ks.amber, tr('almost', 'लगभग')),
        dot(Ks.rose, tr('try again', 'फिर से')),
      ],
    );
  }
}

/// What the child should say for [item], shown big. [words] (from the last answer to this
/// item) colours a reading item word by word.
class VoiceItemView extends StatelessWidget {
  const VoiceItemView({super.key, required this.item, this.words = const []});
  final Map<String, dynamic> item;
  final List<Map<String, dynamic>> words;

  static String instruction(String? kind) => switch (kind) {
    'read_letter' => tr('Read this letter', 'यह अक्षर पढ़ो'),
    'say_sound' => tr('Listen and say the sound', 'सुनो और आवाज़ बोलो'),
    'build_word' => tr(
      'Join the sounds and say the word',
      'आवाज़ें जोड़कर शब्द बोलो',
    ),
    'read_word' => tr('Read this word', 'यह शब्द पढ़ो'),
    'make_sentence' => tr(
      'Say a sentence with these words',
      'इन शब्दों से एक वाक्य बोलो',
    ),
    'read_sentence' => tr('Read the sentence', 'वाक्य पढ़ो'),
    'read_paragraph' => tr('Read the story aloud', 'कहानी ज़ोर से पढ़ो'),
    'answer_question' => tr('Answer the question', 'सवाल का जवाब दो'),
    _ => tr('Listen to Saathi and answer', 'साथी को सुनो और जवाब दो'),
  };

  @override
  Widget build(BuildContext context) {
    final kind = item['kind'] as String?;
    final d = ((item['display'] as Map?) ?? const {}).cast<String, dynamic>();
    final text = (d['text'] ?? '').toString().trim();
    final tiles = ((d['tiles'] as List?) ?? const []).map((e) => '$e').toList();
    final useWords = ((d['words'] as List?) ?? const [])
        .map((e) => '$e')
        .toList();
    final question = (d['question'] ?? '').toString().trim();
    final coloured = words.isNotEmpty;

    Widget body;
    if (kind == 'build_word' && tiles.isNotEmpty) {
      body = Wrap(
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: 8,
        runSpacing: 10,
        children: [
          for (var i = 0; i < tiles.length; i++) ...[
            if (i > 0)
              const Text('+', style: TextStyle(fontSize: 34, color: Ks.muted)),
            _Tile(tiles[i]),
          ],
          const Text(
            '= ?',
            style: TextStyle(
              fontSize: 38,
              color: Ks.accent,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      );
    } else if (kind == 'make_sentence' && useWords.isNotEmpty) {
      body = Wrap(
        alignment: WrapAlignment.center,
        spacing: 10,
        runSpacing: 10,
        children: [for (final w in useWords) _Tile(w, size: 32)],
      );
    } else if (kind == 'answer_question' && question.isNotEmpty) {
      body = Text(
        question,
        textAlign: TextAlign.center,
        style: const TextStyle(
          fontSize: 28,
          height: 1.5,
          fontWeight: FontWeight.w700,
          color: Ks.ink,
        ),
      );
    } else if (text.isNotEmpty) {
      final double size = switch (kind) {
        'read_letter' || 'say_sound' => text.characters.length <= 2 ? 140 : 72,
        'read_word' => 72,
        'read_sentence' => 36,
        'read_paragraph' => 25,
        _ => text.length <= 3 ? 110 : (text.length <= 12 ? 60 : 30),
      };
      final paragraph = kind == 'read_paragraph' || text.length > 60;
      final style = TextStyle(
        fontSize: size,
        height: paragraph ? 1.7 : 1.25,
        fontWeight: paragraph ? FontWeight.w500 : FontWeight.w700,
        color: Ks.ink,
      );
      final align = paragraph ? TextAlign.start : TextAlign.center;
      body = coloured
          ? VoiceWordsText(words: words, style: style, textAlign: align)
          : Text(text, textAlign: align, style: style);
    } else {
      body = const Text('👂', style: TextStyle(fontSize: 90));
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          instruction(kind),
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontSize: 17,
            color: Ks.muted,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 14),
        body,
        if (coloured && text.isNotEmpty) ...[
          const SizedBox(height: 14),
          const VoiceWordsLegend(),
        ],
      ],
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile(this.text, {this.size = 54});
  final String text;
  final double size;
  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.symmetric(
      horizontal: size * 0.4,
      vertical: size * 0.18,
    ),
    decoration: BoxDecoration(
      color: Ks.accentSoft,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: Ks.accent, width: 2),
    ),
    child: Text(
      text,
      style: TextStyle(
        fontSize: size,
        fontWeight: FontWeight.w700,
        color: Ks.ink,
        height: 1.2,
      ),
    ),
  );
}
