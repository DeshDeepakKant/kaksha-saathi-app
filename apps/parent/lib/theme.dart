import 'package:flutter/material.dart';

import 'l10n.dart';

/// Kaksha Saathi design tokens (shared with the parent app, copied because they are separate
/// Flutter projects; keep the two files in sync).
class Ks {
  static const ink = Color(0xFF1D2B2A);
  static const paper = Color(0xFFFBF8F2);
  static const card = Colors.white;
  static const accent = Color(0xFF0F6B5C); // deep teal — primary action
  static const accentSoft = Color(0xFFE3F0EC);
  static const amber = Color(0xFFE7A13B); // needs practice
  static const amberSoft = Color(0xFFFCF0DC);
  static const rose = Color(0xFFC4494A); // needs intervention
  static const roseSoft = Color(0xFFFAE5E4);
  static const green = Color(0xFF2E7D4F); // on track
  static const greenSoft = Color(0xFFE4F2E8);
  static const muted = Color(0xFF5C6B69);
  static const line = Color(0xFFE6E0D4);

  static const statusColor = {
    'on_track': green,
    'needs_practice': amber,
    'needs_intervention': rose,
    'not_started': muted,
  };
  static const statusBg = {
    'on_track': greenSoft,
    'needs_practice': amberSoft,
    'needs_intervention': roseSoft,
    'not_started': Color(0xFFF1EEE7),
  };
  static const statusIcon = {
    'on_track': Icons.check_circle_rounded,
    'needs_practice': Icons.error_rounded,
    'needs_intervention': Icons.cancel_rounded,
    'not_started': Icons.circle_outlined,
  };
  static Map<String, String> get statusLabel => {
    'on_track': tr('Doing well', 'ठीक चल रहा है'),
    'needs_practice': tr('Needs practice', 'अभ्यास चाहिए'),
    'needs_intervention': tr('Needs attention', 'ध्यान चाहिए'),
    'not_started': tr('Not assessed yet', 'अभी जाँच नहीं'),
  };

  static ThemeData theme() {
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: accent,
        primary: accent,
        surface: paper,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: paper,
      fontFamily: 'NotoSansDevanagari',
    );
    return base.copyWith(
      textTheme: base.textTheme.copyWith(
        bodyLarge: base.textTheme.bodyLarge?.copyWith(
          fontSize: 17,
          height: 1.5,
          color: ink,
        ),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(
          fontSize: 16,
          height: 1.45,
          color: ink,
        ),
        titleLarge: base.textTheme.titleLarge?.copyWith(
          fontSize: 22,
          fontWeight: FontWeight.w700,
          color: ink,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: ink,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(56),
          textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          side: const BorderSide(color: line),
          textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: card,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 16,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: line),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: accent, width: 2),
        ),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: paper,
        foregroundColor: ink,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: 21,
          fontWeight: FontWeight.w700,
          color: ink,
          fontFamily: 'NotoSansDevanagari',
        ),
      ),
      cardTheme: CardThemeData(
        color: card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: const BorderSide(color: line),
        ),
        margin: EdgeInsets.zero,
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
      ),
    );
  }
}

/// Status chip: icon + colour + label (never colour alone).
class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key, this.compact = false});
  final String status;
  final bool compact;
  @override
  Widget build(BuildContext context) {
    final s = Ks.statusColor.containsKey(status) ? status : 'not_started';
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 12,
        vertical: compact ? 4 : 7,
      ),
      decoration: BoxDecoration(
        color: Ks.statusBg[s],
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Ks.statusIcon[s],
            size: compact ? 15 : 18,
            color: Ks.statusColor[s],
          ),
          const SizedBox(width: 6),
          Text(
            Ks.statusLabel[s]!,
            style: TextStyle(
              fontSize: compact ? 13 : 15,
              color: Ks.statusColor[s],
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 10, top: 6),
    child: Row(
      children: [
        Expanded(
          child: Text(text, style: Theme.of(context).textTheme.titleMedium),
        ),
        ?trailing,
      ],
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.text});
  final IconData icon;
  final String text;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 48, color: Ks.muted),
          const SizedBox(height: 12),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Ks.muted, fontSize: 16),
          ),
        ],
      ),
    ),
  );
}

class Loading extends StatelessWidget {
  const Loading({super.key, this.label});
  final String? label;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(color: Ks.accent),
          const SizedBox(height: 14),
          Text(
            label ?? tr('Loading…', 'लोड हो रहा है…'),
            style: const TextStyle(color: Ks.muted),
          ),
        ],
      ),
    ),
  );
}
