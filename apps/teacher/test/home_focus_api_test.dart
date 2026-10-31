import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kaksha_teacher/api.dart';
import 'package:kaksha_teacher/l10n.dart';
import 'package:kaksha_teacher/screens/voice_report_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Home practice focus writes (docs/voice_focus_contract.md §3): PUT and DELETE need the network,
/// are never queued, and fail with an ApiError the card shows in a snackbar.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const path = '/v1/children/7/home_focus';
  final body = {
    'subject': 'english',
    'plan': {'focus_stage': 'letter', 'source': 'teacher_override'},
    'override': {'id': 1, 'stage': 'letter', 'until': '2026-11-07'},
    'history': <Object>[],
  };

  test('PUT sends the JSON body and returns the GET body', () async {
    late http.Request seen;
    final api = Api.forTest(
      MockClient((r) async {
        seen = r;
        return http.Response(jsonEncode(body), 200);
      }),
    );
    final r = await api.putJson(path, {
      'subject': 'english',
      'stage': 'letter',
      'note': 'Practise letter sounds',
      'days': 7,
    });
    expect(seen.method, 'PUT');
    expect(seen.url.path, path);
    expect(jsonDecode(seen.body), {
      'subject': 'english',
      'stage': 'letter',
      'note': 'Practise letter sounds',
      'days': 7,
    });
    expect((r as Map)['override']['stage'], 'letter');
    expect(api.pendingCount.value, 0); // not queued
  });

  test('PUT 422 and a lost connection become ApiErrors', () async {
    final bad = Api.forTest(
      MockClient(
        (_) async => http.Response(jsonEncode({'detail': 'unknown stage'}), 422),
      ),
    );
    await expectLater(
      bad.putJson(path, {'subject': 'english', 'stage': 'x'}),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 422)),
    );
    final offline = Api.forTest(
      MockClient((_) async => throw http.ClientException('no route')),
    );
    await expectLater(
      offline.putJson(path, {'subject': 'english', 'stage': 'letter'}),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 0)),
    );
    await expectLater(
      offline.delete('$path?subject=english'),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 0)),
    );
    expect(offline.pendingCount.value, 0);
  });

  test('DELETE carries the subject query', () async {
    late http.Request seen;
    final api = Api.forTest(
      MockClient((r) async {
        seen = r;
        return http.Response(jsonEncode({...body, 'override': null}), 200);
      }),
    );
    final r = await api.delete('$path?subject=literacy');
    expect(seen.method, 'DELETE');
    expect(seen.url.queryParameters['subject'], 'literacy');
    expect((r as Map)['override'], isNull);
  });

  test('focus labels and dates', () async {
    await Lang.set('en');
    expect(voiceDay('2026-11-07'), '7 Nov');
    expect(voiceDay(null), '');
    expect(voiceStages, hasLength(5));
    expect(voiceFocusSourceLabel('teacher_override'), 'Set by you');
    expect(voiceFocusSourceLabel('unknown'), '');
    await Lang.set('hi');
    expect(voiceDay('2026-11-07'), '7 नवंबर');
    await Lang.set('en');
  });
}
