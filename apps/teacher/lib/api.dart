import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n.dart';
import 'outbox.dart';

/// API base. Override at build time:
///   flutter build web --dart-define=API_BASE=https://host
class Api {
  Api._([http.Client? client, Outbox? outbox])
    : _client = client ?? http.Client(),
      _outbox = outbox ?? Outbox();
  static final Api i = Api._();

  /// For unit tests: inject a fake HTTP client (and optionally a small-cap outbox).
  @visibleForTesting
  factory Api.forTest(http.Client client, {Outbox? outbox}) =>
      Api._(client, outbox);

  final http.Client _client;
  final Outbox _outbox;

  /// Pauses before the one automatic GET retry, and the first-attempt timeout for queued writes.
  /// Fields (not consts) so tests can shrink them.
  @visibleForTesting
  Duration retryDelay = const Duration(seconds: 3);
  @visibleForTesting
  Duration queuedTimeout = const Duration(seconds: 30);
  static const _define = String.fromEnvironment('API_BASE');

  /// The live server (Render). Every build talks to it unless a developer deliberately overrides
  /// it with `--dart-define=API_BASE=...`; nothing falls back to a server on a laptop.
  static const productionBase = 'https://kaksha-saathi-558g.onrender.com';
  late final String base = _define.isNotEmpty ? _define : productionBase;

  String? _token;
  String? _teacherId; // owner stamp for outbox entries
  Map<String, dynamic>? me;
  final _cacheStore = <String, dynamic>{};

  bool get loggedIn => _token != null;

  Future<void> loadSession() async {
    final p = await SharedPreferences.getInstance();
    _token = p.getString('token');
    _teacherId = p.getString('teacher_id');
    await _outbox.load(); // updates pendingCount
    final cache = p.getString('cache');
    if (cache != null && cache.isNotEmpty) {
      _cacheStore.addAll(jsonDecode(cache) as Map<String, dynamic>);
    }
    await _startPrefs();
  }

  Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    if (_token != null) await p.setString('token', _token!);
    if (_teacherId != null) await p.setString('teacher_id', _teacherId!);
    await p.setString('cache', jsonEncode(_cacheStore));
  }

  Map<String, String> get _headers => {
    'Authorization': 'Bearer ${_token ?? ''}',
  };

  /// GET with offline fallback: if the request fails, the last successful copy is returned
  /// with `offline: true` added (so screens can tell the teacher what is stale).
  /// Render's free server sleeps and takes up to ~40 s to wake, so the timeout is 45 s and a
  /// timeout or 502/503/504 is retried once after a short pause.
  Future<dynamic> get(String path) async {
    try {
      final r = await _getRaw(path);
      if (r.statusCode >= 400) throw _fail(r);
      final data = jsonDecode(utf8.decode(r.bodyBytes));
      _cacheStore[path] = data;
      await _save();
      _kickOutbox();
      return data;
    } catch (e) {
      // An expired session is not "offline": let the caller send the teacher back to login.
      if (e is ApiError && e.status == 401) rethrow;
      if (_cacheStore.containsKey(path)) {
        final c = _cacheStore[path];
        if (c is Map<String, dynamic>) return {...c, 'offline': true};
        return c;
      }
      rethrow;
    }
  }

  static bool _isGateway(int status) =>
      status == 502 || status == 503 || status == 504;

  Future<http.Response> _getRaw(String path) async {
    for (var attempt = 0; ; attempt++) {
      try {
        final r = await _client
            .get(Uri.parse('$base$path'), headers: _headers)
            .timeout(const Duration(seconds: 45));
        if (attempt == 0 && _isGateway(r.statusCode)) {
          await Future<void>.delayed(retryDelay);
          continue;
        }
        return r;
      } on TimeoutException {
        if (attempt > 0) rethrow;
        await Future<void>.delayed(retryDelay);
      }
    }
  }

  Future<http.Response> _postRaw(
    String path,
    Map<String, dynamic> body,
    Duration timeout,
  ) => _client
      .post(
        Uri.parse('$base$path'),
        headers: {..._headers, 'content-type': 'application/json'},
        body: jsonEncode(body),
      )
      .timeout(timeout);

  Future<dynamic> postJson(String path, Map<String, dynamic> body) async {
    try {
      final r = await _postRaw(path, body, const Duration(seconds: 120));
      if (r.statusCode >= 400) throw _fail(r);
      _kickOutbox();
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiError {
      rethrow;
    } catch (_) {
      throw ApiError.network();
    }
  }

  // ---- offline outbox

  /// Writes that should survive a lost connection (taps, probes, confirms, attendance).
  /// Tries the request now; on a network failure/timeout, 401, 408/429 or 5xx it is parked in
  /// the outbox (persisted) and `{'queued': true}` is returned. Other 4xx still throw.
  /// If older writes are already waiting, they go first so the order is kept.
  ///
  /// Replay safety (the server may have processed a request whose reply was lost):
  ///  - `/captures/tap`: a `client_uuid` is added to the body; the backend de-duplicates on it.
  ///  - `/captures/probe`: a `client_uuid` query param is appended to the path; the backend
  ///    de-duplicates on it. The extended path is what gets parked, so replays reuse the id.
  ///  - `/captures/{id}/confirm`: safe, a second send gets 409 "already handled", which is dropped.
  ///  - `/attendance`: safe (sets a value); `setAttendance` pins `day` so a late replay hits the right date.
  ///  - `/plans/{id}/groups/{key}/done`: safe, idempotent on the server.
  Future<dynamic> postQueued(String path, Map<String, dynamic> body) async {
    final b = Map<String, dynamic>.of(body);
    final uri = Uri.parse(path);
    if (uri.path.endsWith('/captures/tap') && b['client_uuid'] == null) {
      b['client_uuid'] = newClientUuid();
    }
    if (uri.path.endsWith('/captures/probe') &&
        !uri.queryParameters.containsKey('client_uuid')) {
      path = '$path${uri.hasQuery ? '&' : '?'}client_uuid=${newClientUuid()}';
    }
    final entry = OutboxEntry(
      id: newClientUuid(),
      path: path,
      body: b,
      createdAt: DateTime.now().millisecondsSinceEpoch,
      owner: _teacherId ?? '',
    );
    if (!_outbox.isEmpty) {
      await flushOutbox();
      if (!_outbox.isEmpty) {
        await _outbox.add(entry);
        return {'queued': true};
      }
    }
    http.Response r;
    try {
      r = await _postRaw(path, b, queuedTimeout);
    } catch (_) {
      await _outbox.add(entry);
      return {'queued': true};
    }
    if (r.statusCode < 400) {
      _kickOutbox();
      return jsonDecode(utf8.decode(r.bodyBytes));
    }
    final err = _fail(r); // 401 also sends the teacher back to login
    if (_classify(r.statusCode) == OutboxResult.retry) {
      await _outbox.add(entry);
      return {'queued': true};
    }
    throw err;
  }

  /// Number of writes waiting in the outbox (drives the "N waiting to send" chip).
  ValueNotifier<int> get pendingCount => _outbox.pending;

  static OutboxResult _classify(int status) {
    if (status < 400) return OutboxResult.sent;
    // 401: the session expired; keep the write for after the teacher signs in again.
    if (status == 401 || status == 408 || status == 429 || status >= 500) {
      return OutboxResult.retry;
    }
    return OutboxResult.drop;
  }

  Future<OutboxResult> _replay(OutboxEntry e) async {
    if (_token == null) return OutboxResult.retry;
    // Never send one teacher's parked writes under another teacher's login.
    if (e.owner != (_teacherId ?? '')) return OutboxResult.drop;
    http.Response r;
    try {
      r = await _postRaw(e.path, e.body, queuedTimeout);
    } catch (_) {
      return OutboxResult.retry;
    }
    final res = _classify(r.statusCode);
    if (r.statusCode == 401) _fail(r);
    // A 500 that never clears is a server bug, not a cold start: give up after a few tries so
    // it cannot block the queue forever. (Gateway errors and network failures never count.)
    final poison =
        r.statusCode >= 500 && !_isGateway(r.statusCode) && e.attempts + 1 >= 8;
    return res == OutboxResult.retry && poison ? OutboxResult.drop : res;
  }

  /// Replays the outbox in order. Stops at the first network failure or retryable error; drops an
  /// entry the server refuses (4xx). Safe to call any time; only one run at a time.
  Future<void> flushOutbox() async {
    if (!loggedIn || _outbox.isEmpty) return;
    try {
      await _outbox.flush(_replay);
    } catch (_) {}
  }

  Timer? _kick;
  Timer? _ticker;

  /// After a successful request the network is clearly up: flush soon (debounced).
  void _kickOutbox() {
    if (_outbox.isEmpty || _outbox.flushing || _kick != null) return;
    _kick = Timer(const Duration(seconds: 2), () {
      _kick = null;
      unawaited(flushOutbox());
    });
  }

  /// Retry parked writes every [every] while the app runs (main.dart starts this).
  void startOutboxTimer({Duration every = const Duration(seconds: 60)}) {
    _ticker?.cancel();
    _ticker = Timer.periodic(every, (_) => unawaited(flushOutbox()));
  }

  Future<dynamic> delete(String path) async {
    try {
      final r = await _client
          .delete(Uri.parse('$base$path'), headers: _headers)
          .timeout(const Duration(seconds: 30));
      if (r.statusCode >= 400) throw _fail(r);
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiError {
      rethrow;
    } catch (_) {
      throw ApiError.network();
    }
  }

  /// PUT that needs the network (not queued in the outbox): a lost connection is
  /// `ApiError.network()`, a failed response is `ApiError(status)`.
  Future<dynamic> putJson(String path, Map<String, dynamic> body) async {
    try {
      final r = await _client
          .put(
            Uri.parse('$base$path'),
            headers: {..._headers, 'content-type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 45));
      if (r.statusCode >= 400) throw _fail(r);
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiError {
      rethrow;
    } catch (_) {
      throw ApiError.network();
    }
  }

  Future<dynamic> postMultipart(
    String path, {
    Map<String, String> fields = const {},
    Uint8List? file,
    String filename = 'file',
    String fieldName = 'image',
  }) async {
    final req = http.MultipartRequest('POST', Uri.parse('$base$path'));
    req.headers.addAll(_headers);
    req.fields.addAll(fields);
    if (file != null) {
      req.files.add(
        http.MultipartFile.fromBytes(fieldName, file, filename: filename),
      );
    }
    final streamed = await _client
        .send(req)
        .timeout(const Duration(seconds: 180));
    final r = await http.Response.fromStream(streamed);
    if (r.statusCode >= 400) throw _fail(r);
    _kickOutbox();
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  /// Multipart POST with several files, each `(field, bytes, filename)`; a field name may repeat
  /// (a book's cover and index pages all go as `images`). Reading a book with AI can take a
  /// couple of minutes, hence the long timeout. A request that never reached the server
  /// throws [ApiError.network].
  Future<dynamic> postMultipartFiles(
    String path, {
    Map<String, String> fields = const {},
    List<(String, Uint8List, String)> files = const [],
    Duration timeout = const Duration(seconds: 240),
  }) async {
    try {
      final req = http.MultipartRequest('POST', Uri.parse('$base$path'));
      req.headers.addAll(_headers);
      req.fields.addAll(fields);
      for (final (field, bytes, filename) in files) {
        req.files.add(
          http.MultipartFile.fromBytes(field, bytes, filename: filename),
        );
      }
      final streamed = await _client.send(req).timeout(timeout);
      final r = await http.Response.fromStream(streamed).timeout(timeout);
      if (r.statusCode >= 400) throw _fail(r);
      _kickOutbox();
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiError {
      rethrow;
    } catch (_) {
      throw ApiError.network();
    }
  }

  /// Called once when the server rejects the session (401); main.dart opens the login screen.
  VoidCallback? onSessionExpired;

  ApiError _fail(http.Response r) {
    if (r.statusCode == 401 && _token != null) {
      logout(); // clears the token first, so parallel 401s don't fire this twice
      onSessionExpired?.call();
    }
    return ApiError(_detail(r), r.statusCode);
  }

  static String _detail(http.Response r) {
    Object? detail;
    try {
      final j = jsonDecode(utf8.decode(r.bodyBytes));
      if (j is Map) detail = j['detail'];
    } catch (_) {}
    return ApiError.friendly(r.statusCode, detail);
  }

  Future<Map<String, dynamic>> login(String code, String pin) async {
    final r = await postJson('/v1/auth/login', {
      'school_code': code,
      'pin': pin,
    }) as Map<String, dynamic>;
    _token = r['token'] as String;
    final t = r['teacher'];
    _teacherId = (t is Map && t['id'] != null) ? '${t['id']}' : '';
    // Writes parked by a different teacher never go out under this login.
    await _outbox.removeWhere((e) => e.owner != _teacherId);
    await _save();
    await _prefsAfterLogin();
    return r;
  }

  Future<Map<String, dynamic>> fetchMe() async {
    me = await get('/v1/me') as Map<String, dynamic>;
    if (_teacherId == null && me!['id'] != null) {
      _teacherId = '${me!['id']}';
      await _save();
    }
    return me!;
  }

  /// Clears the session and cached reads. The outbox is deliberately KEPT: a 401 (expired token)
  /// also lands here and must not eat the teacher's unsent taps. Each entry is stamped with its
  /// teacher id, and [login] drops entries from a different teacher, so nothing is ever sent
  /// under someone else's login.
  Future<void> logout() async {
    _token = null;
    _cacheStore.clear();
    prefs = null; // the phone copy (per teacher) stays for their next sign-in
    final p = await SharedPreferences.getInstance();
    await p.remove('token');
    await p.remove('cache');
  }

  // ---- language and voice (docs/lang_provider_contract.md §3, §5)

  static const _prefsPath = '/v1/me/prefs';
  static const _prefFields = ['voice_provider', 'app_lang', 'content_lang'];

  /// This teacher's `{voice_provider, app_lang, content_lang, stored}`; null when signed out.
  Map<String, dynamic>? prefs;
  bool _prefsDirty = false; // changed while offline; sent before the next read
  String? _titlesLang;
  Map<String, String> _titles = const {};
  bool _langHooked = false;

  String get _prefsKey => 'prefs.${_teacherId ?? ''}';

  static Map<String, dynamic> _pickPrefs(Object? m) {
    final src = m is Map ? m : const {};
    return {
      'voice_provider': src['voice_provider'] ?? 'sarvam',
      'app_lang': src['app_lang'] ?? 'en',
      'content_lang': src['content_lang'] ?? 'hi',
      'stored': src['stored'] == true,
    };
  }

  /// App start: apply the phone's copy at once (works offline), then refresh from the server.
  Future<void> _startPrefs() async {
    _hookLang();
    if (!loggedIn) return;
    await _loadLocalPrefs();
    unawaited(refreshPrefs().catchError((_) {}));
  }

  /// After sign-in: this teacher's phone copy, then the server's (briefly awaited so the first
  /// screen already shows the right languages).
  Future<void> _prefsAfterLogin() async {
    _hookLang();
    prefs = null;
    _prefsDirty = false;
    _titlesLang = null;
    _titles = const {};
    await _loadLocalPrefs();
    try {
      await refreshPrefs().timeout(const Duration(seconds: 10));
    } catch (_) {}
  }

  /// A language switched elsewhere (the English | हिंदी toggle) is saved for this teacher too.
  void _hookLang() {
    if (_langHooked) return;
    _langHooked = true;
    Lang.code.addListener(() {
      final p = prefs;
      if (!loggedIn || p == null || p['app_lang'] == Lang.code.value) return;
      unawaited(setPref('app_lang', Lang.code.value).catchError((_) => false));
    });
  }

  Future<void> _loadLocalPrefs() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = p.getString(_prefsKey);
      if (raw == null || raw.isEmpty) return;
      final m = jsonDecode(raw) as Map;
      prefs = _pickPrefs(m);
      _prefsDirty = m['dirty'] == true;
      _titlesLang = m['titles_lang'] as String?;
      _titles = ((m['titles'] as Map?) ?? const {}).map(
        (k, v) => MapEntry('$k', '$v'),
      );
      await _applyPrefs(fetchTitles: false);
    } catch (_) {}
  }

  Future<void> _saveLocalPrefs() async {
    final cur = prefs;
    if (cur == null) return;
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString(
        _prefsKey,
        jsonEncode({
          ...cur,
          'dirty': _prefsDirty,
          'titles_lang': _titlesLang,
          'titles': _titles,
        }),
      );
    } catch (_) {}
  }

  Future<Map<String, dynamic>> _sendPrefs(Map<String, dynamic> p) async {
    http.Response r;
    try {
      r = await _postRaw(_prefsPath, {
        for (final f in _prefFields) f: p[f],
      }, const Duration(seconds: 20));
    } catch (_) {
      throw ApiError.network();
    }
    if (r.statusCode >= 400) throw _fail(r);
    return _pickPrefs(jsonDecode(utf8.decode(r.bodyBytes)));
  }

  /// Reads this teacher's prefs from the server (first sending a change made offline) and
  /// applies them. Throws when the server can't be reached.
  Future<void> refreshPrefs() async {
    if (!loggedIn) return;
    Map<String, dynamic> server;
    if (_prefsDirty && prefs != null) {
      server = await _sendPrefs(prefs!);
    } else {
      final r = await _getRaw(_prefsPath);
      if (r.statusCode >= 400) throw _fail(r);
      server = _pickPrefs(jsonDecode(utf8.decode(r.bodyBytes)));
      // Never saved yet: keep the app language the teacher picked before signing in.
      if (server['stored'] != true && server['app_lang'] != Lang.code.value) {
        try {
          server = await _sendPrefs({...server, 'app_lang': Lang.code.value});
        } catch (_) {}
      }
    }
    prefs = server;
    _prefsDirty = false;
    await _applyPrefs();
  }

  /// Saves one setting (`voice_provider` / `app_lang` / `content_lang`) right away: applied on
  /// the phone first, then sent. Returns false when only the phone has it (no network, or a
  /// server without prefs); it is sent on the next start. Throws [ApiError] when the server
  /// refuses the value (the change is undone).
  Future<bool> setPref(String field, String value) async {
    final before = Map<String, dynamic>.of(prefs ?? _pickPrefs(null));
    prefs = {...before, field: value};
    await _applyPrefs(fetchTitles: false);
    try {
      prefs = await _sendPrefs(prefs!);
      _prefsDirty = false;
      await _applyPrefs();
      return true;
    } on ApiError catch (e) {
      if (e.status == 0 || e.status == 404 || e.status >= 500) {
        _prefsDirty = e.status != 404;
        await _applyPrefs();
        return false;
      }
      if (e.status != 401) {
        prefs = before;
        await _applyPrefs(fetchTitles: false);
      }
      rethrow;
    }
  }

  /// Lang + ContentLang from [prefs]; checkpoint titles for languages other than hi/en come from
  /// `/v1/content/titles` (the last copy is kept for offline starts).
  Future<void> _applyPrefs({bool fetchTitles = true}) async {
    final p = prefs;
    if (p == null) return;
    final app = '${p['app_lang']}';
    final content = '${p['content_lang']}';
    if (Lang.code.value != app) await Lang.set(app);
    var titles = const <String, String>{};
    if (content != 'hi' && content != 'en') {
      if (fetchTitles && loggedIn) {
        try {
          final r = await _getRaw('/v1/content/titles?lang=$content');
          if (r.statusCode < 400) {
            final j = jsonDecode(utf8.decode(r.bodyBytes));
            final t = j is Map ? j['titles'] : null;
            if (t is Map) {
              _titles = t.map((k, v) => MapEntry('$k', '$v'));
              _titlesLang = content;
            }
          }
        } catch (_) {}
      }
      if (_titlesLang == content) titles = _titles;
    }
    ContentLang.apply(content, titles);
    await _saveLocalPrefs();
  }

  /// `GET /v1/languages`: app languages, content languages and voice services (last copy offline).
  Future<Map<String, dynamic>> languages() async =>
      ((await get('/v1/languages')) as Map).cast<String, dynamic>();

  /// Server voice for [text] (`POST /v1/speech/tts`). Status 200 carries the audio; 204 = no
  /// service speaks [lang]; 0 = no network / not signed in. Never throws.
  Future<({int status, Uint8List? audio, String? mime})> speechTts(
    String text,
    String lang, {
    Duration timeout = const Duration(seconds: 12),
  }) async {
    if (!loggedIn) return (status: 0, audio: null, mime: null);
    try {
      final r = await _postRaw('/v1/speech/tts', {
        'text': text,
        'lang': lang,
      }, timeout);
      if (r.statusCode != 200 || r.bodyBytes.isEmpty) {
        return (status: r.statusCode, audio: null, mime: null);
      }
      return (status: 200, audio: r.bodyBytes, mime: r.headers['content-type']);
    } catch (_) {
      return (status: 0, audio: null, mime: null);
    }
  }

  // ---- convenience wrappers
  Future<dynamic> classes() => get('/v1/classes');
  Future<dynamic> roster(int classId) => get('/v1/classes/$classId/roster');
  Future<dynamic> board(int classId, String subject) =>
      get('/v1/classes/$classId/board?subject=$subject');

  /// [forDate] (yyyy-mm-dd) plans for another day; omitted means today.
  Future<dynamic> plan(
    int classId,
    String subject, {
    bool force = false,
    String? forDate,
  }) => postJson(
    '/v1/classes/$classId/plans?subject=$subject&force=$force'
    '${forDate == null ? '' : '&for_date=$forDate'}',
    {},
  );
  Future<dynamic> latestPlan(int classId, String subject, {String? forDate}) =>
      get(
        '/v1/classes/$classId/plans/latest?subject=$subject'
        '${forDate == null ? '' : '&for_date=$forDate'}',
      );
  Future<dynamic> profile(int childId, String subject) =>
      get('/v1/children/$childId/profile?subject=$subject');
  Future<dynamic> history(int childId, {String? subject}) => get(
    '/v1/children/$childId/history${subject == null ? '' : '?subject=$subject'}',
  );
  Future<dynamic> tap(int classId, List<Map<String, dynamic>> items) =>
      postJson('/v1/classes/$classId/captures/tap', {'items': items});
  Future<dynamic> checkpointTargets(String cpId) =>
      get('/v1/checkpoints/$cpId/targets');
  Future<dynamic> probe(String cpId) => get('/v1/checkpoints/$cpId/probe');

  /// Replaces the day's register; with [merge] only marks [absentRolls] absent, leaving others as-is.
  Future<dynamic> setAttendance(
    int classId,
    List<int> absentRolls, {
    bool merge = false,
  }) {
    // Pin the day: a parked write replayed after midnight must still mark the day it was taken.
    final n = DateTime.now();
    final day =
        '${n.year}-${n.month.toString().padLeft(2, '0')}-${n.day.toString().padLeft(2, '0')}';
    return postQueued(
      '/v1/classes/$classId/attendance?day=$day${merge ? '&merge=true' : ''}',
      {'absent_rolls': absentRolls},
    );
  }

  Future<dynamic> markDone(int planId, String groupKey) =>
      postJson('/v1/plans/$planId/groups/$groupKey/done', {});
  Future<dynamic> aiActivity() => get('/v1/ai_activity');
  Future<dynamic> contentStatus() => get('/v1/content/status');
}

class ApiError implements Exception {
  ApiError(this.message, this.status);

  /// The request never reached the server (no internet, timeout).
  factory ApiError.network() => ApiError(
    tr(
      'No internet. Try again when the network is back.',
      'इंटरनेट नहीं है। नेटवर्क वापस आने पर दोबारा कोशिश करें।',
    ),
    0,
  );

  final String message;
  final int status;

  /// Short, teacher-readable text for a failed response. [detail] is FastAPI's `detail`: a string,
  /// or a list of validation objects `{loc, msg, type}` on 422.
  static String friendly(int status, Object? detail) {
    if (status == 502 || status == 503 || status == 504) {
      return tr(
        'Server is waking up, try again in a minute',
        'सर्वर चालू हो रहा है, एक मिनट बाद दोबारा कोशिश करें',
      );
    }
    if (status >= 500) {
      return tr(
        'Server problem, please try again',
        'सर्वर में समस्या है, कृपया दोबारा कोशिश करें',
      );
    }
    if (detail is String && detail.isNotEmpty) return detail;
    if (detail is List && detail.isNotEmpty) {
      final parts = <String>[];
      for (final d in detail.take(3)) {
        if (d is Map) {
          final loc = d['loc'];
          final field = loc is List
              ? loc.whereType<String>().where(
                  (x) => x != 'body' && x != 'query',
                )
              : const <String>[];
          final msg = '${d['msg'] ?? ''}'.trim();
          parts.add(field.isEmpty ? msg : '${field.last}: $msg');
        } else {
          parts.add('$d');
        }
      }
      return '${tr('Please check the details', 'कृपया जानकारी जाँचें')}: '
          '${parts.where((x) => x.isNotEmpty).join('; ')}';
    }
    if (detail != null) return detail.toString();
    return trf('Request failed ({status})', 'अनुरोध सफल नहीं हुआ ({status})', {
      'status': '$status',
    });
  }

  @override
  String toString() => status >= 500 ? friendly(status, null) : message;
}
