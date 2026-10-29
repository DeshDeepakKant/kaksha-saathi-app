import 'package:flutter/material.dart';

import '../l10n.dart';
import '../theme.dart';

/// "Since yesterday" card: who moved up or slipped. Shows a few names, expands to all, dismissible.
/// Each move is `{child_id, first_name, roll_no, direction, from, to}`; `to == null` means on track.
class BoardMovedBanner extends StatefulWidget {
  const BoardMovedBanner({
    super.key,
    required this.moves,
    required this.onDismiss,
  });
  final List<Map<String, dynamic>> moves;
  final VoidCallback onDismiss;
  @override
  State<BoardMovedBanner> createState() => _BoardMovedBannerState();
}

class _BoardMovedBannerState extends State<BoardMovedBanner> {
  static const _preview = 3;
  bool _all = false;

  String _name(Map<String, dynamic> m) => (m['first_name'] ?? '').toString();

  String _dest(Map<String, dynamic> m) {
    final to = m['to'];
    if (to is Map && to.isNotEmpty) return cpTitle(to);
    return tr('On track', 'अपनी गति पर');
  }

  /// The short phrase after the name, e.g. "moved to On track".
  String _phrase(Map<String, dynamic> m) {
    switch (m['direction']) {
      case 'improved':
        return trf('moved to {dest}', '{dest} पर पहुँचा', {'dest': _dest(m)});
      case 'slipped':
        final to = m['to'];
        return (to is Map && to.isNotEmpty)
            ? trf(
                'needs practice: {title}',
                'अभ्यास चाहिए: {title}', {'title': cpTitle(to)},
              )
            : tr('needs practice', 'अभ्यास चाहिए');
      default:
        return trf('moved to {dest}', '{dest} में बदला', {'dest': _dest(m)});
    }
  }

  String _arrow(Map<String, dynamic> m) => switch (m['direction']) {
    'improved' => '↑',
    'slipped' => '↓',
    _ => '→',
  };

  Color _color(Map<String, dynamic> m) => switch (m['direction']) {
    'improved' => Ks.green,
    'slipped' => Ks.rose,
    _ => Ks.muted,
  };

  InlineSpan _span(Map<String, dynamic> m, {required bool withDest}) {
    final c = _color(m);
    return TextSpan(
      children: [
        TextSpan(
          text: _name(m),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        TextSpan(text: withDest ? ' ${_phrase(m)} ' : ' '),
        TextSpan(
          text: _arrow(m),
          style: TextStyle(color: c, fontWeight: FontWeight.w800),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final moves = widget.moves;
    final shown = _all ? moves : moves.take(_preview).toList();
    final more = moves.length - shown.length;
    const base = TextStyle(color: Ks.ink, fontSize: 15, height: 1.4);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: Ks.accentSoft,
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(14, 6, 4, 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.trending_up_rounded, color: Ks.accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    tr('Since yesterday', 'कल से अब तक'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 16,
                      color: Ks.ink,
                    ),
                  ),
                ),
                IconButton(
                  tooltip: tr('Dismiss', 'हटाएँ'),
                  icon: const Icon(Icons.close_rounded),
                  onPressed: widget.onDismiss,
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 10, bottom: 4),
              child: _all
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final m in shown)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text.rich(
                              _span(m, withDest: true),
                              style: base,
                            ),
                          ),
                      ],
                    )
                  : Text.rich(
                      TextSpan(
                        children: [
                          for (var i = 0; i < shown.length; i++) ...[
                            if (i > 0) const TextSpan(text: '  ·  '),
                            _span(shown[i], withDest: true),
                          ],
                          if (more > 0)
                            TextSpan(
                              text: trf('  +{more} more', '  +{more} और', {'more': more}),
                              style: const TextStyle(color: Ks.muted),
                            ),
                        ],
                      ),
                      style: base,
                    ),
            ),
            if (moves.length > _preview)
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton(
                  style: TextButton.styleFrom(
                    minimumSize: const Size(48, 48),
                    foregroundColor: Ks.accent,
                  ),
                  onPressed: () => setState(() => _all = !_all),
                  child: Text(
                    _all
                        ? tr('Show less', 'कम दिखाएँ')
                        : trf(
                            'See all ({movesCount})',
                            'सभी देखें ({movesCount})', {'movesCount': moves.length},
                          ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
