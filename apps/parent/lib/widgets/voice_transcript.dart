import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import 'voice_item_view.dart';

/// Live conversation: Saathi on the left, the child on the right (what was heard, coloured
/// per word for reading items). Scrolls to the newest line as lines arrive.
class VoiceTranscript extends StatefulWidget {
  const VoiceTranscript({
    super.key,
    required this.lines,
    this.shrinkWrap = false,
  });
  final List<Map<String, dynamic>> lines;

  /// For use inside another scroll view (the report screen).
  final bool shrinkWrap;

  @override
  State<VoiceTranscript> createState() => _VoiceTranscriptState();
}

class _VoiceTranscriptState extends State<VoiceTranscript> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _toEnd(jump: true);
  }

  @override
  void didUpdateWidget(VoiceTranscript old) {
    super.didUpdateWidget(old);
    if (widget.lines.length != old.lines.length) _toEnd();
  }

  void _toEnd({bool jump = false}) {
    if (widget.shrinkWrap) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      final end = _scroll.position.maxScrollExtent;
      if (jump) {
        _scroll.jumpTo(end);
      } else if ((_scroll.offset - end).abs() > 1) {
        _scroll.animateTo(
          end,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final lines = widget.lines;
    if (lines.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          tr('The conversation will appear here.', 'बातचीत यहाँ दिखेगी।'),
          textAlign: TextAlign.center,
          style: const TextStyle(color: Ks.muted),
        ),
      );
    }
    return ListView.builder(
      controller: widget.shrinkWrap ? null : _scroll,
      shrinkWrap: widget.shrinkWrap,
      physics: widget.shrinkWrap ? const NeverScrollableScrollPhysics() : null,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      itemCount: lines.length,
      itemBuilder: (_, i) => VoiceBubble(line: lines[i]),
    );
  }
}

class VoiceBubble extends StatelessWidget {
  const VoiceBubble({super.key, required this.line});
  final Map<String, dynamic> line;

  @override
  Widget build(BuildContext context) {
    final tutor = line['role'] != 'child';
    final verdict = line['verdict'] as String?;
    final words = voiceWords(line['words']);
    final text = (line['text'] ?? '').toString();
    final bg = tutor
        ? Ks.accentSoft
        : switch (verdict) {
            'correct' => Ks.greenSoft,
            'close' => Ks.amberSoft,
            'wrong' => Ks.roseSoft,
            _ => Ks.card,
          };
    final mark = switch (verdict) {
      'correct' => '✓',
      'close' => '~',
      'wrong' => '✗',
      'silent' => '…',
      'skipped' => '⏭',
      _ => '',
    };
    const style = TextStyle(fontSize: 16, height: 1.45, color: Ks.ink);
    final content = !tutor && words.isNotEmpty
        ? VoiceWordsText(words: words, style: style, useHeard: true)
        : Text(
            text.isEmpty && !tutor
                ? tr('(nothing heard)', '(कुछ सुनाई नहीं दिया)')
                : text,
            style: text.isEmpty
                ? style.copyWith(color: Ks.muted, fontStyle: FontStyle.italic)
                : style,
          );
    final bubble = Flexible(
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          color: bg,
          border: Border.all(color: Ks.line),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(tutor ? 4 : 16),
            bottomRight: Radius.circular(tutor ? 16 : 4),
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Flexible(child: content),
            if (mark.isNotEmpty) ...[
              const SizedBox(width: 8),
              Text(
                mark,
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: voiceWordColor(verdict == 'silent' ? null : verdict),
                ),
              ),
            ],
          ],
        ),
      ),
    );
    return Row(
      mainAxisAlignment: tutor
          ? MainAxisAlignment.start
          : MainAxisAlignment.end,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: tutor
          ? [
              const Text('🦉', style: TextStyle(fontSize: 22)),
              const SizedBox(width: 6),
              bubble,
              const SizedBox(width: 40),
            ]
          : [
              const SizedBox(width: 40),
              bubble,
              const SizedBox(width: 6),
              const Text('🧒', style: TextStyle(fontSize: 22)),
            ],
    );
  }
}
