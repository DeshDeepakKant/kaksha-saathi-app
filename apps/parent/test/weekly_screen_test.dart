import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:kaksha_parent/l10n.dart';
import 'package:kaksha_parent/widgets/weekly_card.dart';

Map<String, dynamic> _sample({Object? practiceDays}) => {
  'week_start': '2026-10-26',
  'week_end': '2026-11-01',
  'practice_days': practiceDays ?? ['2026-10-26', '2026-10-28', '2026-11-10'],
  'voice_sessions': 2,
  'voice_minutes': 14.6,
  'learned': [
    {'title_hi': 'दहाई और इकाई', 'title_en': 'Tens and ones'},
  ],
  'working_on': [
    {'title_hi': 'हासिल वाला घटाव', 'title_en': 'Subtraction with borrowing'},
  ],
  'next': [
    {'title_hi': 'गुणा की शुरुआत', 'title_en': 'Starting multiplication'},
  ],
  'tip': {
    'explain_hi': 'बच्चा बड़े अंक में से छोटा घटा देता है।',
    'explain_en': 'The child takes the smaller digit from the bigger one.',
    'game_hi': 'दस-दस तीलियों के बंडल से खेलें।',
    'game_en': 'Play with bundles of ten sticks.',
    'example': '52 − 17 → 45',
  },
  'line_hi': 'कविता ने इस हफ़्ते अच्छा अभ्यास किया।',
  'line_en': 'Kavita practised well this week.',
};

Future<void> _pump(WidgetTester t, WeeklyData w) => t.pumpWidget(
  MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(
        child: WeeklyCard(data: w, name: 'कविता'),
      ),
    ),
  ),
);

void main() {
  tearDown(() => Lang.code.value = 'en');

  test('practice_days as dates marks weekdays inside the week only', () {
    final w = WeeklyData.from(_sample());
    expect(w.days, {0, 2});
    expect(w.practiceDays, 2);
    expect(w.voiceMinutes, 15);
  });

  test('practice_days as a count has no weekday positions', () {
    final w = WeeklyData.from(_sample(practiceDays: 3));
    expect(w.days, isNull);
    expect(w.practiceDays, 3);
  });

  test('empty payload is a quiet week with an encouraging line', () {
    final w = WeeklyData.from({});
    expect(w.isQuiet, isTrue);
    expect(weeklyLine(w, ''), contains('fresh start'));
  });

  testWidgets('card renders name, dates and lists in English and Hindi', (
    t,
  ) async {
    final w = WeeklyData.from(_sample());
    await _pump(t, w);
    expect(find.text("कविता's week"), findsOneWidget);
    expect(find.text('26 Oct – 1 Nov'), findsOneWidget);
    expect(find.text('Tens and ones'), findsOneWidget);
    expect(find.text('Subtraction with borrowing'), findsOneWidget);
    expect(find.text('Starting multiplication'), findsOneWidget);
    expect(find.textContaining('%'), findsNothing);

    Lang.code.value = 'hi';
    await _pump(t, WeeklyData.from(_sample()));
    await t.pumpAndSettle();
    expect(find.text('कविता का हफ़्ता'), findsOneWidget);
    expect(find.text('26 अक्टूबर – 1 नवंबर'), findsOneWidget);
    expect(find.text('दहाई और इकाई'), findsOneWidget);
    expect(find.text('इस हफ़्ते सीखा'), findsOneWidget);
    expect(find.textContaining('1 मिनट का खेल'), findsOneWidget);
  });

  test('speech and share text include the lists', () {
    final w = WeeklyData.from(_sample());
    expect(weeklySpeech(w, 'Kavita'), contains('Learned this week: Tens'));
    final s = weeklyShareText(w, 'Kavita');
    expect(s, contains('• Starting multiplication'));
    expect(s, contains('1-minute game'));
  });
}
