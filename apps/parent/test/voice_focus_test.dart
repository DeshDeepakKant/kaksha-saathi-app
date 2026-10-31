import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kaksha_parent/l10n.dart';
import 'package:kaksha_parent/screens/voice_report_screen.dart';
import 'package:kaksha_parent/widgets/voice_header.dart';

Map<String, dynamic> _report({Map<String, dynamic>? outcome}) => {
  'minutes': 28,
  'items_attempted': 30,
  'accuracy': 0.8,
  'highest_stage': 'word_read',
  'first_try': 20,
  'after_retry': 4,
  'failed': 5,
  'skipped': 1,
  'outcome': ?outcome,
};

Future<void> _pumpReport(WidgetTester t, Map<String, dynamic> r) =>
    t.pumpWidget(
      MaterialApp(
        home: VoiceReportScreen(key: UniqueKey(), sessionId: 1, report: r),
      ),
    );

void main() {
  tearDown(() => Lang.code.value = 'en');

  testWidgets('report shows the focus line from report.outcome', (t) async {
    await _pumpReport(
      t,
      _report(
        outcome: {
          'focus_stage': 'word_build',
          'focus_items': 14,
          'focus_accuracy': 0.86,
          'mastered': true,
          'moved_up_to': 'word_read',
          'next_focus_stage': 'word_read',
          'next_reason_en': 'Ready for reading words.',
          'next_reason_hi': 'अब शब्द पढ़ने की बारी।',
        },
      ),
    );
    expect(find.text('Focus: Making words · 86% right'), findsOneWidget);
    expect(find.text('Mastered — moved up to Reading words'), findsOneWidget);
    expect(find.text('Next time: Reading words'), findsOneWidget);
    expect(find.text('Ready for reading words.'), findsOneWidget);
  });

  testWidgets('not mastered, and an older report has no focus line', (t) async {
    await _pumpReport(
      t,
      _report(
        outcome: {
          'focus_stage': 'word_read',
          'focus_items': 9,
          'focus_accuracy': 0.6,
          'mastered': false,
          'next_focus_stage': 'word_read',
        },
      ),
    );
    expect(find.text('Not mastered yet'), findsOneWidget);
    expect(find.text('Next time: Reading words'), findsOneWidget);

    await _pumpReport(t, _report());
    await t.pumpAndSettle();
    expect(find.textContaining('Focus:'), findsNothing);
    expect(find.textContaining('Next time'), findsNothing);
  });

  testWidgets('ladder renders with and without a focus stage', (t) async {
    for (final focus in [null, 'word_build']) {
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: VoiceLadder(stage: 'word_read', focus: focus),
          ),
        ),
      );
      expect(find.text('Making words'), findsOneWidget);
      expect(find.text('Reading words'), findsOneWidget);
    }
  });
}
