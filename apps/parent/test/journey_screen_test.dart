import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kaksha_parent/api.dart';
import 'package:kaksha_parent/l10n.dart';
import 'package:kaksha_parent/screens/journey_screen.dart';
import 'package:kaksha_parent/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _ms(
  String id,
  int ch,
  String hi,
  String en,
  String state, [
  String? nipun,
]) => {
  'checkpoint_id': id,
  'chapter': ch,
  'title_hi': hi,
  'title_en': en,
  'nipun_ref': nipun,
  'state': state,
};

final _journey = {
  'subject': 'numeracy',
  'grade': 3,
  'milestones': [
    _ms('n1', 1, 'गिनती 1-20', 'Counting 1-20', 'learned', 'N2.1'),
    _ms('n2', 1, 'स्थानीय मान', 'Place value', 'learned'),
    _ms('n3', 2, 'हासिल वाला जोड़', 'Addition with carry', 'working'),
    _ms('n4', 2, 'उधार वाला घटाना', 'Subtraction with borrow', 'next'),
    _ms('n5', 3, 'गुणा', 'Multiplication', 'later'),
  ],
  'counts': {'learned': 2, 'working': 1, 'total': 5},
  'celebrations': [
    {
      'checkpoint_id': 'n2',
      'title_hi': 'स्थानीय मान',
      'title_en': 'Place value',
      'at': '2026-10-27',
      'line_hi': 'कविता ने स्थानीय मान सीख लिया!',
      'line_en': 'Kavita learned place value!',
    },
  ],
  'growth': [
    for (var i = 0; i < 6; i++)
      {'week_end': '2026-09-${(20 + i).toString()}', 'learned': i ~/ 2},
  ],
};

Future<void> _pump(
  WidgetTester tester,
  MockClient client, {
  double width = 1080,
}) async {
  tester.view.physicalSize = Size(width, 4000);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await http.runWithClient(
    () => tester.pumpWidget(
      MaterialApp(theme: Ks.theme(), home: const JourneyScreen()),
    ),
    () => client,
  );
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    Lang.code.value = 'en';
    Api.i.profile = {
      'child': {'first_name': 'Kavita'},
    };
  });

  testWidgets('shows progress as counts, states, NIPUN chip and celebrations', (
    tester,
  ) async {
    String? asked;
    await _pump(
      tester,
      MockClient((req) async {
        asked = req.url.toString();
        return http.Response(
          jsonEncode(_journey),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    expect(asked, contains('/v1/parent/journey?subject=numeracy'));
    expect(find.text('Kavita’s journey'), findsOneWidget);
    expect(find.text('Kavita has learned 2 of 5 steps.'), findsOneWidget);
    expect(find.text('Working on 1 step right now.'), findsOneWidget);
    expect(find.text('Kavita learned place value!'), findsOneWidget);
    expect(find.text('Learned steps by week'), findsOneWidget);
    expect(find.text('Chapter 2'), findsOneWidget);
    expect(find.text('NIPUN'), findsOneWidget);
    expect(find.text('Working on it now'), findsOneWidget);
    expect(find.text('Next step'), findsOneWidget);
    // never scores
    expect(find.textContaining('%'), findsNothing);
  });

  testWidgets('Hindi wording', (tester) async {
    Lang.code.value = 'hi';
    await _pump(
      tester,
      MockClient(
        (_) async => http.Response(
          jsonEncode(_journey),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      ),
    );
    expect(find.text('Kavita ने 5 में से 2 कदम सीख लिए हैं।'), findsOneWidget);
    expect(find.text('कविता ने स्थानीय मान सीख लिया!'), findsOneWidget);
    expect(find.text('अध्याय 2'), findsOneWidget);
    expect(find.text('अभी इस पर काम चल रहा है'), findsOneWidget);
  });

  testWidgets('route missing -> friendly error with retry', (tester) async {
    var calls = 0;
    await _pump(
      tester,
      MockClient((_) async {
        calls++;
        return http.Response('{"detail":"Not Found"}', 404);
      }),
    );
    expect(find.textContaining('not ready on the server yet'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(calls, 1);
  });

  testWidgets('brand-new child -> empty state', (tester) async {
    await _pump(
      tester,
      MockClient(
        (_) async => http.Response(
          jsonEncode({
            'subject': 'numeracy',
            'milestones': [],
            'counts': {'learned': 0, 'working': 0, 'total': 0},
            'celebrations': [],
            'growth': [],
          }),
          200,
        ),
      ),
    );
    expect(find.textContaining('journey will appear here'), findsOneWidget);
  });

  for (final hi in [false, true]) {
    testWidgets('English chip fetches the english journey on a narrow phone (${hi ? 'hi' : 'en'})', (
      tester,
    ) async {
      Lang.code.value = hi ? 'hi' : 'en';
      final asked = <String>[];
      final client = MockClient((req) async {
        asked.add(req.url.toString());
        final subject = req.url.queryParameters['subject'];
        return http.Response(
          jsonEncode({..._journey, 'subject': subject}),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      });
      await _pump(tester, client, width: 720); // 360 dp: the narrowest phones
      final label = hi ? 'अंग्रेज़ी' : 'English';
      expect(find.text(label), findsOneWidget);
      expect(find.byIcon(Icons.translate_rounded), findsOneWidget);
      await http.runWithClient(() async {
        await tester.tap(find.text(label));
        await tester.pumpAndSettle();
      }, () => client);
      expect(asked.last, contains('/v1/parent/journey?subject=english'));
      expect(
        find.text(hi ? 'Kavita ने 5 में से 2 कदम सीख लिए हैं।' : 'Kavita has learned 2 of 5 steps.'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull); // no overflow in the 3-way toggle
    });
  }
}
