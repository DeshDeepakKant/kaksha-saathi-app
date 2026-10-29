import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

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

/// Shrinks [child] (laid out at the full width) so it is at most [maxHeight] tall, but never
/// below [minScale]; below that it keeps [minScale] and is taller than [maxHeight], so wrap it
/// in a scroll view. The child is laid out at width / scale, so it uses the whole row after
/// shrinking and long paragraphs shrink less than a plain FittedBox would.
class VoiceFit extends SingleChildRenderObjectWidget {
  const VoiceFit({
    super.key,
    required this.maxHeight,
    this.minScale = 0.6,
    super.child,
  });
  final double maxHeight;
  final double minScale;

  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderVoiceFit(maxHeight, minScale);

  @override
  void updateRenderObject(BuildContext context, RenderObject renderObject) {
    (renderObject as _RenderVoiceFit)
      ..maxHeight = maxHeight
      ..minScale = minScale;
  }
}

class _RenderVoiceFit extends RenderBox
    with RenderObjectWithChildMixin<RenderBox> {
  _RenderVoiceFit(this._maxHeight, this._minScale);

  double _maxHeight;
  double _minScale;
  double _scale = 1;

  set maxHeight(double v) {
    if (v == _maxHeight) return;
    _maxHeight = v;
    markNeedsLayout();
  }

  set minScale(double v) {
    if (v == _minScale) return;
    _minScale = v;
    markNeedsLayout();
  }

  /// The scale and the child's size (at width / scale) for width [w].
  (double, Size) _fit(double w, Size Function(double) at) {
    var cs = at(w);
    var scale = 1.0;
    if (cs.height > _maxHeight && _maxHeight > 0) {
      scale = (_maxHeight / cs.height).clamp(_minScale, 1.0);
      // More room per line once shrunk: lay out at width / scale, then fit the new height.
      cs = at(w / scale);
      if (cs.height * scale > _maxHeight) {
        scale = (_maxHeight / cs.height).clamp(_minScale, scale);
        cs = at(w / scale);
      }
    }
    return (scale, cs);
  }

  static BoxConstraints _tight(double w) =>
      BoxConstraints(minWidth: w, maxWidth: w);

  double _width(BoxConstraints c) => c.hasBoundedWidth ? c.maxWidth : 0.0;

  @override
  void performLayout() {
    final c = child;
    if (c == null) {
      size = constraints.smallest;
      return;
    }
    final w = _width(constraints);
    final (scale, cs) = _fit(w, (cw) {
      c.layout(_tight(cw), parentUsesSize: true);
      return c.size;
    });
    _scale = scale;
    size = constraints.constrain(Size(w, cs.height * scale));
  }

  @override
  Size computeDryLayout(BoxConstraints constraints) {
    final c = child;
    if (c == null) return constraints.smallest;
    final w = _width(constraints);
    final (scale, cs) = _fit(w, (cw) => c.getDryLayout(_tight(cw)));
    return constraints.constrain(Size(w, cs.height * scale));
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final c = child;
    if (c == null) return;
    context.pushTransform(
      needsCompositing,
      offset,
      Matrix4.diagonal3Values(_scale, _scale, 1),
      c.paint,
    );
  }

  @override
  void applyPaintTransform(RenderBox c, Matrix4 transform) {
    transform.multiply(Matrix4.diagonal3Values(_scale, _scale, 1));
  }

  @override
  bool hitTestChildren(BoxHitTestResult result, {required Offset position}) =>
      child != null &&
      result.addWithPaintTransform(
        transform: Matrix4.diagonal3Values(_scale, _scale, 1),
        position: position,
        hitTest: (r, p) => child!.hitTest(r, position: p),
      );

  @override
  double computeMinIntrinsicHeight(double width) =>
      child?.getMinIntrinsicHeight(width) ?? 0;
  @override
  double computeMaxIntrinsicHeight(double width) =>
      child?.getMaxIntrinsicHeight(width) ?? 0;
  @override
  double computeMinIntrinsicWidth(double height) =>
      child?.getMinIntrinsicWidth(height) ?? 0;
  @override
  double computeMaxIntrinsicWidth(double height) =>
      child?.getMaxIntrinsicWidth(height) ?? 0;
}
