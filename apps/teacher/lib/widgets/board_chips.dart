import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';

/// Tappable child name pill; always at least 48dp tall so it is a real tap target.
class BoardChildChip extends StatelessWidget {
  const BoardChildChip({
    super.key,
    required this.label,
    required this.background,
    required this.onTap,
    this.icon,
    this.iconColor,
    this.semanticLabel,
  });
  final String label;
  final Color background;
  final VoidCallback onTap;
  final IconData? icon;
  final Color? iconColor;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: semanticLabel ?? label,
    excludeSemantics: true,
    child: Material(
      color: background,
      shape: const StadiumBorder(),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (icon != null) ...[
                  Icon(icon, size: 16, color: iconColor ?? Ks.muted),
                  const SizedBox(width: 6),
                ],
                Flexible(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 15, color: Ks.ink),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

/// Small NIPUN learning-outcome tag for a group card.
class BoardNipunBadge extends StatelessWidget {
  const BoardNipunBadge(this.ref, {super.key});
  final String ref;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      color: Ks.accentSoft,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      'NIPUN $ref',
      style: const TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w700,
        color: Ks.accent,
      ),
    ),
  );
}

/// "N waiting to send" chip, visible only while the offline outbox has writes. Tap = send now.
class BoardPendingChip extends StatefulWidget {
  const BoardPendingChip({super.key, this.onFlushed});
  final VoidCallback? onFlushed;
  @override
  State<BoardPendingChip> createState() => _BoardPendingChipState();
}

class _BoardPendingChipState extends State<BoardPendingChip> {
  bool _busy = false;

  Future<void> _flush() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      // The outbox may not define flushOutbox yet; a dynamic call keeps this compiling either way.
      final dynamic api = Api.i;
      await api.flushOutbox();
    } catch (_) {}
    if (!mounted) return;
    setState(() => _busy = false);
    widget.onFlushed?.call();
  }

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<int>(
    valueListenable: Api.i.pendingCount,
    builder: (context, n, _) {
      if (n <= 0) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Semantics(
            button: true,
            child: Material(
              color: Ks.amberSoft,
              shape: const StadiumBorder(),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: _flush,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 48),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Ks.amber,
                                ),
                              )
                            : const Icon(
                                Icons.cloud_upload_outlined,
                                size: 20,
                                color: Ks.amber,
                              ),
                        const SizedBox(width: 8),
                        Text(
                          tr('$n waiting to send', '$n भेजना बाकी'),
                          style: const TextStyle(
                            color: Ks.amber,
                            fontWeight: FontWeight.w600,
                            fontSize: 15,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}
