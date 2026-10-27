import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kaksha_teacher/api.dart';
import 'package:kaksha_teacher/outbox.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Records every POST body per path and answers with whatever [handler] returns
/// (throw to simulate a network failure).
class Fake {
  final sent = <({String path, Map<String, dynamic> body})>[];
  late http.Response Function(http.Request r) handler;

  MockClient get client => MockClient((r) async {
    if (r.method == 'POST') {
      sent.add((
        path: r.url.path + (r.url.hasQuery ? '?${r.url.query}' : ''),
        body: jsonDecode(r.body) as Map<String, dynamic>,
      ));
    }
    return handler(r);
  });
}

http.Response ok([Object body = const {'ok': true}]) => http.Response(
  jsonEncode(body),
  200,
  headers: {'content-type': 'application/json'},
);

http.Response status(int code, [Object body = const {'detail': 'x'}]) =>
    http.Response(
      jsonEncode(body),
      code,
      headers: {'content-type': 'application/json'},
    );

Future<Api> makeApi(Fake f, {int cap = 200}) async {
  SharedPreferences.setMockInitialValues({'token': 't', 'teacher_id': '7'});
  final api = Api.forTest(f.client, outbox: Outbox(cap: cap));
  api.retryDelay = Duration.zero;
  await api.loadSession();
  return api;
}

void main() {
  const tap = '/v1/classes/1/captures/tap';

  test('network failure parks the write and returns queued', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    final r = await api.postQueued('/v1/classes/1/attendance', {
      'absent_rolls': [3],
    });
    expect(r, {'queued': true});
    expect(api.pendingCount.value, 1);
  });

  test('success sends directly and queues nothing', () async {
    final f = Fake()..handler = (_) => ok({'committed': 1});
    final api = await makeApi(f);
    final r = await api.postQueued(tap, {'items': []});
    expect(r, {'committed': 1});
    expect(api.pendingCount.value, 0);
  });

  test('server 4xx throws and is not queued; 5xx is queued', () async {
    final f = Fake()
      ..handler = (_) => status(422, {'detail': 'child not in class'});
    final api = await makeApi(f);
    await expectLater(
      api.postQueued(tap, {'items': []}),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 422)),
    );
    expect(api.pendingCount.value, 0);
    f.handler = (_) => status(503);
    expect(await api.postQueued(tap, {'items': []}), {'queued': true});
    expect(api.pendingCount.value, 1);
  });

  test('tap gets a client_uuid that stays the same on replay', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    await api.postQueued(tap, {'items': []});
    final firstTry = f.sent.single.body['client_uuid'] as String;
    expect(firstTry, isNotEmpty);
    // Still offline: a flush retries with the same id.
    await api.flushOutbox();
    expect(f.sent.last.body['client_uuid'], firstTry);
    // Back online: the replay carries the same id, then the queue is empty.
    f.handler = (_) => ok();
    await api.flushOutbox();
    expect(f.sent.last.body['client_uuid'], firstTry);
    expect(api.pendingCount.value, 0);
    // A caller-supplied client_uuid is kept as is.
    f.handler = (_) => throw TimeoutException('offline');
    await api.postQueued(tap, {'items': [], 'client_uuid': 'mine'});
    expect(f.sent.last.body['client_uuid'], 'mine');
  });

  test('probe gets a client_uuid query param that stays the same on replay', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    const probe =
        '/v1/classes/1/captures/probe?child_id=2&checkpoint_id=N1&passed=3&total=4';
    await api.postQueued(probe, {});
    final first = f.sent.single.path;
    final id = Uri.parse(first).queryParameters['client_uuid'];
    expect(id, isNotEmpty);
    expect(first, startsWith('$probe&client_uuid='));
    f.handler = (_) => ok();
    await api.flushOutbox();
    expect(f.sent.last.path, first);
    expect(api.pendingCount.value, 0);
  });

  test('replays in order and stops at the first network failure', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    for (final n in [1, 2, 3]) {
      await api.postQueued('/v1/classes/1/attendance', {'n': n});
    }
    expect(api.pendingCount.value, 3);
    f.sent.clear();
    await api.flushOutbox(); // still offline: only the head is tried
    expect(f.sent.map((s) => s.body['n']), [1]);
    f.sent.clear();
    var calls = 0;
    f.handler = (_) => ++calls == 2 ? throw TimeoutException('x') : ok();
    await api.flushOutbox();
    expect(f.sent.map((s) => s.body['n']), [
      1,
      2,
    ]); // 1 sent, 2 failed, 3 untouched
    expect(api.pendingCount.value, 2);
    f.sent.clear();
    f.handler = (_) => ok();
    await api.flushOutbox();
    expect(f.sent.map((s) => s.body['n']), [2, 3]);
    expect(api.pendingCount.value, 0);
  });

  test('a new write waits behind older ones', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    await api.postQueued('/v1/classes/1/attendance', {'n': 1});
    f.sent.clear();
    f.handler = (_) => ok();
    await api.postQueued('/v1/classes/1/attendance', {'n': 2});
    expect(f.sent.map((s) => s.body['n']), [1, 2]);
    expect(api.pendingCount.value, 0);
  });

  test('a 4xx on replay drops that entry and continues', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    for (final n in [1, 2, 3]) {
      await api.postQueued('/v1/classes/1/attendance', {'n': n});
    }
    f.sent.clear();
    f.handler = (r) => (jsonDecode(r.body) as Map)['n'] == 2
        ? status(409, {'detail': 'dup'})
        : ok();
    await api.flushOutbox();
    expect(f.sent.map((s) => s.body['n']), [1, 2, 3]);
    expect(api.pendingCount.value, 0);
  });

  test('cap drops the oldest and keeps the newest', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f, cap: 3);
    for (final n in [1, 2, 3, 4, 5]) {
      await api.postQueued('/v1/classes/1/attendance', {'n': n});
    }
    expect(api.pendingCount.value, 3);
    f.sent.clear();
    f.handler = (_) => ok();
    await api.flushOutbox();
    expect(f.sent.map((s) => s.body['n']), [3, 4, 5]);
  });

  test('queue persists across a restart', () async {
    final f = Fake()..handler = (_) => throw TimeoutException('offline');
    final api = await makeApi(f);
    await api.postQueued('/v1/classes/1/attendance', {'n': 1});
    // "Restart": a new Api over the same stored prefs.
    final api2 = Api.forTest(f.client)..retryDelay = Duration.zero;
    await api2.loadSession();
    expect(api2.pendingCount.value, 1);
    f.sent.clear();
    f.handler = (_) => ok();
    await api2.flushOutbox();
    expect(f.sent.map((s) => s.body['n']), [1]);
    expect(api2.pendingCount.value, 0);
  });

  test('friendly errors', () {
    expect(ApiError.friendly(500, null), contains('Server problem'));
    expect(ApiError.friendly(503, null), contains('waking up'));
    expect(
      ApiError.friendly(422, [
        {
          'loc': ['body', 'items', 0, 'child_id'],
          'msg': 'field required',
          'type': 'x',
        },
      ]),
      'Please check the details: child_id: field required',
    );
    expect(ApiError.friendly(404, 'capture not found'), 'capture not found');
    expect(ApiError('HTTP 500', 500).toString(), contains('Server problem'));
  });

  test('GET retries once on 503 then succeeds', () async {
    var n = 0;
    final f = Fake()..handler = (_) => ++n == 1 ? status(503) : ok({'a': 1});
    final api = await makeApi(f);
    expect(await api.get('/v1/classes'), {'a': 1});
    expect(n, 2);
  });
}
