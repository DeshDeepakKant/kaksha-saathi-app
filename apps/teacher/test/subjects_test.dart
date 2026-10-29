import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kaksha_teacher/l10n.dart';
import 'package:kaksha_teacher/subjects.dart';

void main() {
  setUp(() => Lang.code.value = 'en');

  test('English is a built-in subject with its own label and icon', () {
    expect(builtinSubjectKeys, ['numeracy', 'literacy', 'english']);
    expect(subjectLabel('english'), 'English');
    expect(subjectLabel('numeracy'), 'Maths');
    expect(subjectLabel('literacy'), 'Hindi');
    expect(subjectIcon('english'), Icons.translate_rounded);
    expect(subjectIcon('numeracy'), Icons.calculate_rounded);
    expect(subjectIcon('literacy'), Icons.menu_book_rounded);
  });

  test('labels follow the UI language; custom subjects keep their name', () {
    Lang.code.value = 'hi';
    expect(subjectLabel('english'), 'अंग्रेज़ी');
    expect(subjectLabel('science', fallback: 'Science'), 'Science');
    expect(subjectLabel('science'), 'science');
    expect(subjectIcon('science'), Icons.auto_stories_rounded);
  });
}
