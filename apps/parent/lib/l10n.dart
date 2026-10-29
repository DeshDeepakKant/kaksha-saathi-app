import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:shared_preferences/shared_preferences.dart';

/// UI language. English is the default, Hindi the alternate; 21 more Indian languages read a
/// machine-translated table from `assets/i18n/<code>.json` (key = the English string, built by
/// `tool/l10n_translate.py`). A string missing from a table shows in English.
///
/// Only the app's own text (labels, buttons, messages) follows it. Classroom content (activity
/// steps, probe questions, practice words, tutor speech) follows [ContentLang], which stays Hindi
/// unless the user picks another learning language.
class Lang {
  Lang._();

  static final ValueNotifier<String> code = ValueNotifier('en');
  static bool get isHi => code.value == 'hi';

  /// Urdu, Kashmiri and Sindhi are written right to left.
  static bool get isRtl => const {'ur', 'ks', 'sd'}.contains(code.value);

  /// Locale for Flutter's own widget strings (date picker, tooltips). Flutter has no Material
  /// strings for some languages, so those borrow a close neighbour's.
  static Locale get locale => Locale(_materialLang[code.value] ?? code.value, 'IN');

  static const _materialLang = {
    'brx': 'hi', 'doi': 'hi', 'kok': 'hi', 'mai': 'hi', 'sa': 'hi', 'sat': 'hi', //
    'ks': 'ur', 'sd': 'ur', 'mni': 'bn',
  };

  /// Every locale [locale] can return, for `MaterialApp.supportedLocales`.
  static const supportedLocales = [
    Locale('en', 'IN'), Locale('hi', 'IN'), Locale('bn', 'IN'), Locale('mr', 'IN'), //
    Locale('te', 'IN'), Locale('ta', 'IN'), Locale('gu', 'IN'), Locale('kn', 'IN'),
    Locale('ml', 'IN'), Locale('or', 'IN'), Locale('pa', 'IN'), Locale('as', 'IN'),
    Locale('ur', 'IN'), Locale('ne', 'IN'),
  ];

  /// Bundled fonts for scripts phones often lack (Santali Ol Chiki, Manipuri Meetei Mayek).
  static const fontFallback = ['NotoSansOlChiki', 'NotoSansMeeteiMayek'];

  /// English string -> translation for the current language (empty for English and Hindi).
  static Map<String, String> _table = const {};

  /// Call after `SharedPreferences.setPrefix`. A missing or unreadable value keeps English.
  static Future<void> load() async {
    try {
      final p = await SharedPreferences.getInstance();
      final saved = p.getString('lang');
      if (saved != null && _known(saved)) {
        _table = await _loadTable(saved);
        code.value = saved;
      }
    } catch (_) {}
  }

  /// Switch the UI language and remember it. Unknown codes fall back to English.
  static Future<void> set(String c) async {
    if (!_known(c)) c = 'en';
    if (c == code.value) return;
    _table = await _loadTable(c);
    code.value = c;
    _rebuildAll();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString('lang', c);
    } catch (_) {}
  }

  static bool _known(String c) => appLanguages().any((l) => l.code == c);

  static Future<Map<String, String>> _loadTable(String c) async {
    if (c == 'en' || c == 'hi') return const {};
    try {
      final raw = jsonDecode(await rootBundle.loadString('assets/i18n/$c.json')) as Map;
      return {for (final e in raw.entries) '${e.key}': '${e.value}'};
    } catch (_) {
      return const {}; // no table: English
    }
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

/// The 23 app languages for the picker, in display order. `beta`: Flutter has no Material
/// strings for it and its machine translation is the least checked.
/// One entry of the App Language picker.
typedef AppLanguage = ({String code, String nativeName, String englishName, bool beta});

List<AppLanguage> appLanguages() => const [
  (code: 'en', nativeName: 'English', englishName: 'English', beta: false),
  (code: 'hi', nativeName: 'हिंदी', englishName: 'Hindi', beta: false),
  (code: 'bn', nativeName: 'বাংলা', englishName: 'Bengali', beta: false),
  (code: 'mr', nativeName: 'मराठी', englishName: 'Marathi', beta: false),
  (code: 'te', nativeName: 'తెలుగు', englishName: 'Telugu', beta: false),
  (code: 'ta', nativeName: 'தமிழ்', englishName: 'Tamil', beta: false),
  (code: 'gu', nativeName: 'ગુજરાતી', englishName: 'Gujarati', beta: false),
  (code: 'kn', nativeName: 'ಕನ್ನಡ', englishName: 'Kannada', beta: false),
  (code: 'ml', nativeName: 'മലയാളം', englishName: 'Malayalam', beta: false),
  (code: 'or', nativeName: 'ଓଡ଼ିଆ', englishName: 'Odia', beta: false),
  (code: 'pa', nativeName: 'ਪੰਜਾਬੀ', englishName: 'Punjabi', beta: false),
  (code: 'as', nativeName: 'অসমীয়া', englishName: 'Assamese', beta: false),
  (code: 'ur', nativeName: 'اردو', englishName: 'Urdu', beta: false),
  (code: 'sa', nativeName: 'संस्कृतम्', englishName: 'Sanskrit', beta: true),
  (code: 'ne', nativeName: 'नेपाली', englishName: 'Nepali', beta: false),
  (code: 'kok', nativeName: 'कोंकणी', englishName: 'Konkani', beta: true),
  (code: 'mai', nativeName: 'मैथिली', englishName: 'Maithili', beta: true),
  (code: 'doi', nativeName: 'डोगरी', englishName: 'Dogri', beta: true),
  (code: 'sd', nativeName: 'سنڌي', englishName: 'Sindhi', beta: true),
  (code: 'ks', nativeName: 'کٲشُر', englishName: 'Kashmiri', beta: true),
  (code: 'brx', nativeName: 'बड़ो', englishName: 'Bodo', beta: true),
  (code: 'mni', nativeName: 'ꯃꯤꯇꯩꯂꯣꯟ', englishName: 'Manipuri', beta: true),
  (code: 'sat', nativeName: 'ᱥᱟᱱᱛᱟᱲᱤ', englishName: 'Santali', beta: true),
];

/// `tr('Save', 'सहेजें')` — English first, Hindi second. Other languages look the English up.
String tr(String en, String hi) => switch (Lang.code.value) {
  'en' => en,
  'hi' => hi,
  // An English string used with two Hindi meanings ('Close') can have one entry per meaning.
  _ => Lang._table['$en␟$hi'] ?? Lang._table[en] ?? en,
};

/// `trf('Hello, {name}!', 'नमस्ते, {name}!', {'name': n})` — [tr] with `{placeholders}`, so the
/// English template stays a stable lookup key. An unknown placeholder is left as written.
String trf(String en, String hi, Map<String, Object?> args) => tr(en, hi).replaceAllMapped(
  _placeholder,
  (m) => args.containsKey(m[1]) ? '${args[m[1]]}' : m[0]!,
);

final _placeholder = RegExp(r'\{(\w+)\}');

/// Learning-content language (activity text, checkpoint names, speech). Hindi by default; set
/// from the user's saved preference. [titles] maps checkpoint id -> name in that language.
class ContentLang {
  ContentLang._();

  static final ValueNotifier<String> code = ValueNotifier('hi');
  static Map<String, String> titles = const {};

  static void apply(String c, Map titles) {
    ContentLang.titles = {for (final e in titles.entries) '${e.key}': '${e.value}'};
    code.value = c;
    Lang._rebuildAll(); // cpTitle() is context-free too
  }
}

/// Server field in the selected language (`<base>_en` / `<base>_hi`); Hindi when no English is sent.
String pick(Map m, String base) {
  // The server adds `<base>_<code>` (e.g. line_ta) for other languages; use it when it was sent.
  final c = Lang.code.value;
  final own = (c == 'en' || c == 'hi') ? null : m['${base}_$c'];
  if (own is String && own.isNotEmpty) return own;
  final hi = (m['${base}_hi'] ?? '') as String;
  if (Lang.isHi) return hi;
  final en = m['${base}_en'];
  return (en is String && en.isNotEmpty) ? en : hi;
}

/// Checkpoint/lesson title: in the learning language when that is neither Hindi nor English
/// (and a title was sent), else in the UI language.
String cpTitle(Map m) {
  final c = ContentLang.code.value;
  if (c != 'hi' && c != 'en') {
    final t = ContentLang.titles['${m['checkpoint_id'] ?? m['id']}'];
    if (t != null && t.isNotEmpty) return t;
  }
  return pick(m, 'title');
}

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
        // Another language picked in settings: neither half is selected.
        selected: {if (c == 'en' || c == 'hi') c},
        emptySelectionAllowed: true,
        onSelectionChanged: (s) {
          if (s.isNotEmpty) Lang.set(s.first);
        },
      ),
    );
  }
}
