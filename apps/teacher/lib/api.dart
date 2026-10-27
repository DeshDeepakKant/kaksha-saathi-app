import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n.dart';

/// API base. Override at build time:
///   flutter build web --dart-define=API_BASE=https://host
/// Defaults: web → same origin; Android emulator → host machine.
class Api {
  Api._();
  static final Api i = Api._();
  static const _define = String.fromEnvironment('API_BASE');
  late final String base = _define.isNotEmpty
      ? _define
      : (kIsWeb ? Uri.base.origin : 'http://10.0.2.2:8000');

  String? _token;
  Map<String, dynamic>? me;
  final _cacheStore = <String, dynamic>{};

  bool get loggedIn => _token != null;

  Future<void> loadSession() async {
    final p = await SharedPreferences.getInstance();
    _token = p.getString('token');
    final cache = p.getString('cache');
    if (cache != null && cache.isNotEmpty) {
      _cacheStore.addAll(jsonDecode(cache) as Map<String, dynamic>);
    }
  }

  Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    if (_token != null) await p.setString('token', _token!);
    await p.setString('cache', jsonEncode(_cacheStore));
  }

  Map<String, String> get _headers => {
    'Authorization': 'Bearer ${_token ?? ''}',
  };

  /// GET with offline fallback: if the request fails, the last successful copy is returned
  /// with `offline: true` added (so screens can tell the teacher what is stale).
  Future<dynamic> get(String path) async {
    try {
      final r = await http
          .get(Uri.parse('$base$path'), headers: _headers)
          .timeout(const Duration(seconds: 30));
      if (r.statusCode >= 400) throw ApiError(_detail(r), r.statusCode);
      final data = jsonDecode(utf8.decode(r.bodyBytes));
      _cacheStore[path] = data;
      await _save();
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

  Future<dynamic> postJson(String path, Map<String, dynamic> body) async {
    try {
      final r = await http
          .post(
            Uri.parse('$base$path'),
            headers: {..._headers, 'content-type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 120));
      if (r.statusCode >= 400) throw ApiError(_detail(r), r.statusCode);
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiError {
      rethrow;
    } catch (_) {
      throw ApiError(
        tr(
          'No internet. Try again when the network is back.',
          'इंटरनेट नहीं है। नेटवर्क वापस आने पर दोबारा कोशिश करें।',
        ),
        0,
      );
    }
  }

  Future<dynamic> delete(String path) async {
    final r = await http
        .delete(Uri.parse('$base$path'), headers: _headers)
        .timeout(const Duration(seconds: 30));
    if (r.statusCode >= 400) throw ApiError(_detail(r), r.statusCode);
    return jsonDecode(utf8.decode(r.bodyBytes));
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
    final streamed = await req.send().timeout(const Duration(seconds: 180));
    final r = await http.Response.fromStream(streamed);
    if (r.statusCode >= 400) throw ApiError(_detail(r), r.statusCode);
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  static String _detail(http.Response r) {
    try {
      final j = jsonDecode(utf8.decode(r.bodyBytes));
      if (j is Map && j['detail'] != null) return j['detail'].toString();
    } catch (_) {}
    return 'HTTP ${r.statusCode}';
  }

  Future<Map<String, dynamic>> login(String code, String pin) async {
    final r = await postJson('/v1/auth/login', {
      'school_code': code,
      'pin': pin,
    }) as Map<String, dynamic>;
    _token = r['token'] as String;
    await _save();
    return r;
  }

  Future<Map<String, dynamic>> fetchMe() async {
    me = await get('/v1/me') as Map<String, dynamic>;
    return me!;
  }

  Future<void> logout() async {
    _token = null;
    _cacheStore.clear();
    final p = await SharedPreferences.getInstance();
    await p.remove('token');
    await p.remove('cache');
  }

  // ---- convenience wrappers
  Future<dynamic> classes() => get('/v1/classes');
  Future<dynamic> roster(int classId) => get('/v1/classes/$classId/roster');
  Future<dynamic> board(int classId, String subject) =>
      get('/v1/classes/$classId/board?subject=$subject');
  Future<dynamic> plan(int classId, String subject, {bool force = false}) =>
      postJson('/v1/classes/$classId/plans?subject=$subject&force=$force', {});
  Future<dynamic> latestPlan(int classId, String subject) =>
      get('/v1/classes/$classId/plans/latest?subject=$subject');
  Future<dynamic> profile(int childId, String subject) =>
      get('/v1/children/$childId/profile?subject=$subject');
  Future<dynamic> history(int childId) => get('/v1/children/$childId/history');
  Future<dynamic> tap(int classId, List<Map<String, dynamic>> items) =>
      postJson('/v1/classes/$classId/captures/tap', {'items': items});
  Future<dynamic> checkpointTargets(String cpId) =>
      get('/v1/checkpoints/$cpId/targets');
  Future<dynamic> probe(String cpId) => get('/v1/checkpoints/$cpId/probe');
  Future<dynamic> setAttendance(int classId, List<int> absentRolls) => postJson(
    '/v1/classes/$classId/attendance',
    {'absent_rolls': absentRolls},
  );
  Future<dynamic> markDone(int planId, String groupKey) =>
      postJson('/v1/plans/$planId/groups/$groupKey/done', {});
  Future<dynamic> aiActivity() => get('/v1/ai_activity');
  Future<dynamic> contentStatus() => get('/v1/content/status');
}

class ApiError implements Exception {
  ApiError(this.message, this.status);
  final String message;
  final int status;
  @override
  String toString() => message;
}
