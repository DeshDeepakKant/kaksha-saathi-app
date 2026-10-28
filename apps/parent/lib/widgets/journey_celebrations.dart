import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';

/// Warm card colour for celebrations; ink text on it is far above 4.5:1.
const _starBg = Color(0xFFFFF4D6);
const _starLine = Color(0xFFF1D9A0);

/// "⭐ Teacher noticed" cards for steps learned recently (contract `celebrations`), each with a
/// read-aloud button.
class JourneyCelebrations extends StatefulWidget {
  const JourneyCelebrations({super.key, required this.items});

  /// `[{checkpoint_id, title_hi, title_en, at, line_hi, line_en}]`.
  final List<Map<String, dynamic>> items;

  @override
  State<JourneyCelebrations> createState() => _JourneyCelebrationsState();
}

class _JourneyCelebrationsState extends State<JourneyCelebrations> {
  int? _speaking;

  @override
  void dispose() {
    if (_speaking != null) Speak.stop();
    super.dispose();
  }

  String _line(Map<String, dynamic> c) {
    final line = pick(c, 'line');
    return line.trim().isNotEmpty
        ? line
        : tr('Learned: ${cpTitle(c)}', 'सीख लिया: ${cpTitle(c)}');
  }

  Future<void> _toggle(int i) async {
    if (_speaking == i) {
      await Speak.stop();
      if (mounted) setState(() => _speaking = null);
      return;
    }
    setState(() => _speaking = i);
    await Speak.say(_line(widget.items[i]), Lang.isHi ? 'hi' : 'en');
    if (mounted && _speaking == i) setState(() => _speaking = null);
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionTitle(tr('⭐ Well done!', '⭐ शाबाश!')),
        for (var i = 0; i < widget.items.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Container(
              padding: const EdgeInsets.fromLTRB(14, 10, 4, 10),
              decoration: BoxDecoration(
                color: _starBg,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: _starLine),
              ),
              child: Row(
                children: [
                  const ExcludeSemantics(
                    child: Text('⭐', style: TextStyle(fontSize: 28)),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _line(widget.items[i]),
                          style: const TextStyle(
                            fontSize: 16,
                            height: 1.4,
                            color: Ks.ink,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        if (pick(widget.items[i], 'line').trim().isNotEmpty &&
                            cpTitle(widget.items[i]).isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              cpTitle(widget.items[i]),
                              style: const TextStyle(
                                fontSize: 14,
                                color: Ks.muted,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () => _toggle(i),
                    tooltip: _speaking == i
                        ? tr('Stop', 'रोकें')
                        : tr('Read aloud', 'सुनाएँ'),
                    icon: Icon(
                      _speaking == i
                          ? Icons.stop_rounded
                          : Icons.volume_up_rounded,
                      color: Ks.accent,
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
