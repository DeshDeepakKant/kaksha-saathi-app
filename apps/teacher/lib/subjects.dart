import 'package:flutter/material.dart';

import 'l10n.dart';

/// The three built-in subjects, in tab order. The server's `/subjects` list adds custom ones.
const builtinSubjectKeys = ['numeracy', 'literacy', 'english'];

/// Display name of a subject key; custom subjects use [fallback] (their server name) or the key.
String subjectLabel(String key, {String? fallback}) => switch (key) {
  'numeracy' => tr('Maths', 'गणित'),
  'literacy' => tr('Hindi', 'हिंदी'),
  'english' => tr('English', 'अंग्रेज़ी'),
  _ => (fallback != null && fallback.isNotEmpty) ? fallback : key,
};

IconData subjectIcon(String key) => switch (key) {
  'numeracy' => Icons.calculate_rounded,
  'literacy' => Icons.menu_book_rounded,
  'english' => Icons.translate_rounded,
  _ => Icons.auto_stories_rounded,
};
