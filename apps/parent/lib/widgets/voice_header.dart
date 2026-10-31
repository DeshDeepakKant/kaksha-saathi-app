import 'dart:async';

import 'package:flutter/material.dart';

import '../api_voice.dart';
import '../l10n.dart';
import '../theme.dart';

/// Elapsed / remaining time toward the target, extrapolated locally from the last server value.
/// Ticks on its own so the session screen does not rebuild every second.
class VoiceClock extends StatefulWidget {
  const VoiceClock({
    super.key,
    required this.elapsedS,
    required this.since,
    required this.targetMinutes,
    this.running = true,
  });
  final double elapsedS;
  final DateTime since;
  final int targetMinutes;

  /// False while paused: shows [elapsedS] as is.
  final bool running;

  /// Seconds elapsed now, given the last server value and when it arrived.
  static double now(double elapsedS, DateTime since) =>
      elapsedS + DateTime.now().difference(since).inMilliseconds / 1000;

  @override
  State<VoiceClock> createState() => _VoiceClockState();
}

class _VoiceClockState extends State<VoiceClock> {
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  static String _mmss(double s) {
    final v = s.clamp(0, 99 * 60).round();
    return '${v ~/ 60}:${(v % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final target = widget.targetMinutes * 60.0;
    final e = widget.running
        ? VoiceClock.now(widget.elapsedS, widget.since)
        : widget.elapsedS;
    final left = target - e;
    return Semantics(
      label: trf('{mmss} done, {mmss2} left', '{mmss} हुए, {mmss2} बाकी', {
        'mmss': _mmss(e),
        'mmss2': _mmss(left),
      }),
      child: Row(
        children: [
          const Icon(Icons.timer_outlined, size: 20, color: Ks.accent),
          const SizedBox(width: 6),
          Text(
            '${_mmss(e)} / ${_mmss(target)}',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: Ks.ink,
              fontFeatures: [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            flex: 2,
            child: LinearProgressIndicator(
              value: target <= 0 ? 0 : (e / target).clamp(0.0, 1.0),
              minHeight: 8,
              borderRadius: BorderRadius.circular(99),
              color: Ks.accent,
              backgroundColor: Ks.accentSoft,
            ),
          ),
          const SizedBox(width: 10),
          Flexible(
            child: Text(
              left > 0
                  ? trf('{mmss} left', '{mmss} बाकी', {'mmss': _mmss(left)})
                  : tr('Time up', 'समय पूरा'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 14, color: Ks.muted),
            ),
          ),
        ],
      ),
    );
  }
}

/// The reading ladder. The child's focus stage is highlighted; the current item's stage, when it
/// is a warm-up or challenge step away from the focus, is outlined.
class VoiceLadder extends StatelessWidget {
  const VoiceLadder({super.key, required this.stage, this.focus});
  final String? stage;

  /// The session's focus stage; null on an older server (then [stage] is highlighted).
  final String? focus;

  @override
  Widget build(BuildContext context) {
    final cur = voiceStages.indexOf(stage ?? '');
    final f = voiceStages.indexOf(focus ?? '');
    final at = f >= 0 ? f : cur;
    return Row(
      children: [
        for (var i = 0; i < voiceStages.length; i++)
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(
                right: i == voiceStages.length - 1 ? 0 : 4,
              ),
              child: Column(
                children: [
                  Container(
                    height: 8,
                    decoration: BoxDecoration(
                      color: i < at
                          ? Ks.green
                          : (i == at
                                ? Ks.accent
                                : (i == cur ? Ks.amberSoft : Ks.line)),
                      borderRadius: BorderRadius.circular(99),
                      border: i == cur && i != at
                          ? Border.all(color: Ks.amber, width: 1.5)
                          : null,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    voiceStageLabel(voiceStages[i]),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 11.5,
                      color: i == at
                          ? Ks.accent
                          : (i == cur ? Ks.amber : Ks.muted),
                      fontWeight: i == at || i == cur
                          ? FontWeight.w700
                          : FontWeight.w400,
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
