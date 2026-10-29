import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// What the session is doing right now, as shown to the child.
enum VoiceMicState { talking, listening, thinking, paused, idle }

/// Big status indicator: a pulsing mic with a level meter while listening, Saathi talking,
/// or thinking.
class VoiceMicIndicator extends StatefulWidget {
  const VoiceMicIndicator({
    super.key,
    required this.state,
    required this.level,
    required this.speaking,
    this.compact = false,
  });
  final VoiceMicState state;
  final ValueNotifier<double> level;
  final ValueNotifier<bool> speaking;

  /// Smaller mic and no hint line, for short screens where the item needs the room.
  final bool compact;

  @override
  State<VoiceMicIndicator> createState() => _VoiceMicIndicatorState();
}

class _VoiceMicIndicatorState extends State<VoiceMicIndicator>
    with SingleTickerProviderStateMixin {
  late final _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  );

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(VoiceMicIndicator old) {
    super.didUpdateWidget(old);
    _sync();
  }

  void _sync() {
    final on =
        widget.state == VoiceMicState.listening ||
        widget.state == VoiceMicState.talking;
    if (on && !_pulse.isAnimating) {
      _pulse.repeat(reverse: true);
    } else if (!on && _pulse.isAnimating) {
      _pulse.stop();
      _pulse.value = 0;
    }
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final (Color color, IconData icon, String label) = switch (s) {
      VoiceMicState.listening => (
        Ks.rose,
        Icons.mic_rounded,
        tr('Listening… speak now', 'सुन रहा हूँ… अब बोलो'),
      ),
      VoiceMicState.talking => (
        Ks.accent,
        Icons.record_voice_over_rounded,
        tr('Saathi is talking…', 'साथी बोल रहा है…'),
      ),
      VoiceMicState.thinking => (
        Ks.amber,
        Icons.hourglass_top_rounded,
        tr('Saathi is thinking…', 'साथी सोच रहा है…'),
      ),
      VoiceMicState.paused => (
        Ks.muted,
        Icons.pause_rounded,
        tr('Paused', 'रुका हुआ'),
      ),
      VoiceMicState.idle => (Ks.muted, Icons.mic_none_rounded, ''),
    };
    return Semantics(
      liveRegion: true,
      label: label,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            width: widget.compact ? 72 : 84,
            height: widget.compact ? 72 : 84,
            child: AnimatedBuilder(
              animation: Listenable.merge([_pulse, widget.level]),
              builder: (_, _) {
                final lv = s == VoiceMicState.listening
                    ? widget.level.value
                    : 0.0;
                final ring =
                    58 +
                    22 *
                        (s == VoiceMicState.listening
                            ? lv
                            : _pulse.value * 0.5);
                return Stack(
                  alignment: Alignment.center,
                  children: [
                    Container(
                      width: ring,
                      height: ring,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: color.withValues(
                          alpha: 0.18 + 0.12 * _pulse.value,
                        ),
                      ),
                    ),
                    Container(
                      width: 58,
                      height: 58,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: color,
                      ),
                      child: s == VoiceMicState.thinking
                          ? const Padding(
                              padding: EdgeInsets.all(16),
                              child: CircularProgressIndicator(
                                strokeWidth: 3,
                                color: Colors.white,
                              ),
                            )
                          : Icon(icon, color: Colors.white, size: 32),
                    ),
                  ],
                );
              },
            ),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: widget.compact ? 17 : 19,
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
                if (s == VoiceMicState.listening) ...[
                  const SizedBox(height: 8),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 150),
                    child: _LevelMeter(widget.level),
                  ),
                  if (!widget.compact) ...[
                    const SizedBox(height: 4),
                    ValueListenableBuilder<bool>(
                      valueListenable: widget.speaking,
                      builder: (_, on, _) => Text(
                        on
                            ? tr('I can hear you 👂', 'सुनाई दे रहा है 👂')
                            : tr('Waiting for your voice', 'आवाज़ का इंतज़ार'),
                        style: const TextStyle(fontSize: 14, color: Ks.muted),
                      ),
                    ),
                  ],
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LevelMeter extends StatelessWidget {
  const _LevelMeter(this.level);
  final ValueNotifier<double> level;

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<double>(
    valueListenable: level,
    builder: (_, v, _) => Row(
      children: [
        for (var i = 0; i < 10; i++)
          Expanded(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 90),
              margin: const EdgeInsets.symmetric(horizontal: 1.5),
              height: 8.0 + i * 1.6,
              decoration: BoxDecoration(
                color: v * 10 > i ? (i < 7 ? Ks.green : Ks.amber) : Ks.line,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
          ),
      ],
    ),
  );
}
