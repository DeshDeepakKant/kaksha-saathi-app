import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kaksha_parent/api.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Regression: `_read` used to be typed `Future<dynamic>` while returning the decoded map, which
/// throws a TypeError on Android (AOT) after every successful request, so login showed
/// "Could not connect to the server".
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('login succeeds and stores the child', () async {
    final client = MockClient((req) async {
      expect(req.url.path, '/v1/parent/login');
      return http.Response(
        jsonEncode({
          'token': 't0k',
          'child': {
            'id': 12,
            'first_name': 'कविता',
            'roll_no': 12,
            'class': null,
          },
        }),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    await http.runWithClient(() async {
      await Api.i.login({
        'school_code': 'DEMO',
        'child_roll': 12,
        'parent_phone': '9876500000',
        'pin': '0000',
      });
    }, () => client);
    expect(Api.i.signedIn, isTrue);
    expect(Api.i.child?['roll_no'], 12);
  });

  test('wrong PIN is an ApiError with the server detail', () async {
    final client = MockClient(
      (_) async =>
          http.Response(jsonEncode({'detail': 'invalid credentials'}), 401),
    );
    await http.runWithClient(() async {
      await expectLater(
        Api.i.login({
          'school_code': 'DEMO',
          'child_roll': 12,
          'parent_phone': '1',
          'pin': '1',
        }),
        throwsA(
          isA<ApiError>().having(
            (e) => e.message,
            'message',
            'invalid credentials',
          ),
        ),
      );
    }, () => client);
  });
}
