import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// UI language. English is the default, Hindi the alternate.
///
/// Only the app's own text (labels, buttons, messages) and checkpoint names follow it.
/// Classroom content (activity steps, probe questions, practice words, tutor speech) stays
/// Hindi: children are taught in Hindi and the reviewed library is written in Hindi.
class Lang {
  Lang._();

  static final ValueNotifier<String> code = ValueNotifier('en');
  static bool get isHi => code.value == 'hi';
  static Locale get locale =>
      isHi ? const Locale('hi', 'IN') : const Locale('en', 'IN');

  /// Call after `SharedPreferences.setPrefix`. A missing or unreadable value keeps English.
  static Future<void> load() async {
    try {
      final p = await SharedPreferences.getInstance();
      final saved = p.getString('lang');
      if (saved == 'hi' || saved == 'en') code.value = saved!;
    } catch (_) {}
  }

  static Future<void> set(String c) async {
    if (c == code.value) return;
    code.value = c;
    _rebuildAll();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString('lang', c);
    } catch (_) {}
  }

  /// `tr()` is context-free, so every mounted widget must rebuild to pick up the change.
  /// Rebuilding in place keeps navigation and screen state.
  static void _rebuildAll() {
    void visit(Element e) {
      e.markNeedsBuild();
      e.visitChildren(visit);
    }

    WidgetsBinding.instance.rootElement?.visitChildren(visit);
  }
}

/// `tr('Save', 'सहेजें')` — English first, Hindi second.
String tr(String en, String hi) => Lang.isHi ? hi : en;

/// Server field in the selected language (`<base>_en` / `<base>_hi`); Hindi when no English is sent.
String pick(Map m, String base) {
  final hi = (m['${base}_hi'] ?? '') as String;
  if (Lang.isHi) return hi;
  final en = m['${base}_en'];
  return (en is String && en.isNotEmpty) ? en : hi;
}

/// Checkpoint/lesson title in the selected language.
String cpTitle(Map m) => pick(m, 'title');

/// Compact English | हिंदी switch.
class LangToggle extends StatelessWidget {
  const LangToggle({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: Lang.code,
      builder: (_, c, _) => SegmentedButton<String>(
        showSelectedIcon: false,
        segments: const [
          ButtonSegment(value: 'en', label: Text('English')),
          ButtonSegment(value: 'hi', label: Text('हिंदी')),
        ],
        selected: {c},
        onSelectionChanged: (s) => Lang.set(s.first),
      ),
    );
  }
}
