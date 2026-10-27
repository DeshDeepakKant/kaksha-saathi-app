import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Api {
  Api._();
  static final Api i = Api._();
  static const _define = String.fromEnvironment('API_BASE');
  late final String base = _define.isNotEmpty
      ? _define
      : (kIsWeb ? Uri.base.origin : 'http://10.0.2.2:8000');

  String? _token;
  Map<String, dynamic>? pack; // last downloaded pack → offline fallback
  /// Full home payload: {child, focus, streak}. `child` is the unwrapped identity map.
  Map<String, dynamic>? profile;

  Map<String, dynamic>? get child =>
      (profile?['child'] as Map?)?.cast<String, dynamic>();
  List<dynamic> history = const [];
  List<Map<String, dynamic>> pendingEvidence = [];
  bool offline = false;

  bool get signedIn => _token != null;

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    _token = p.getString('token');
    final pk = p.getString('pack');
    if (pk != null) pack = jsonDecode(pk) as Map<String, dynamic>;
    final pr = p.getString('profile');
    if (pr != null) profile = jsonDecode(pr) as Map<String, dynamic>;
    final pe = p.getString('pending');
    if (pe != null) {
      pendingEvidence = (jsonDecode(pe) as List).cast<Map<String, dynamic>>();
    }
    final h = p.getString('history');
    if (h != null) history = jsonDecode(h) as List;
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    if (_token != null) {
      await p.setString('token', _token!);
    } else {
      await p.remove('token');
    }
    if (pack != null) await p.setString('pack', jsonEncode(pack));
    if (profile != null) await p.setString('profile', jsonEncode(profile));
    await p.setString('pending', jsonEncode(pendingEvidence));
    await p.setString('history', jsonEncode(history));
  }

  Map<String, String> get _h => {'Authorization': 'Bearer ${_token ?? ''}'};

  Future<dynamic> _read(http.Response r) {
    if (r.statusCode >= 400) {
      String d = 'HTTP ${r.statusCode}';
      try {
        d = (jsonDecode(utf8.decode(r.bodyBytes)) as Map)['detail'].toString();
      } catch (_) {}
      throw ApiError(d, r.statusCode);
    }
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  Future<dynamic> get(String path) async {
    final r = await http
        .get(Uri.parse('$base$path'), headers: _h)
        .timeout(const Duration(seconds: 30));
    return _read(r);
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    final r = await http
        .post(
          Uri.parse('$base$path'),
          headers: {..._h, 'content-type': 'application/json'},
          body: jsonEncode(body ?? {}),
        )
        .timeout(const Duration(seconds: 60));
    return _read(r);
  }

  Future<dynamic> postMultipart(
    String path,
    Map<String, String> fields, {
    Uint8List? audio,
    String field = 'audio',
  }) async {
    final req = http.MultipartRequest('POST', Uri.parse('$base$path'));
    req.headers.addAll(_h);
    req.fields.addAll(fields);
    if (audio != null) {
      req.files.add(
        http.MultipartFile.fromBytes(field, audio, filename: 'turn.webm'),
      );
    }
    final r = await http.Response.fromStream(
      await req.send().timeout(const Duration(seconds: 90)),
    );
    return _read(r);
  }

  Future<dynamic> consent(Map<String, dynamic> body) async =>
      _loginResponse(await post('/v1/parent/consent', body));
  Future<dynamic> login(Map<String, dynamic> body) async =>
      _loginResponse(await post('/v1/parent/login', body));

  Map<String, dynamic> _loginResponse(dynamic r) {
    _token = r['token'] as String;
    profile = {
      'child': (r['child'] as Map).cast<String, dynamic>(),
      'focus': <dynamic>[],
      'streak': 0,
    };
    save();
    return r;
  }

  Future<void> fetchChild() async {
    profile = await get('/v1/parent/child') as Map<String, dynamic>;
  }

  Future<void> fetchPack() async {
    try {
      pack = await get('/v1/parent/pack') as Map<String, dynamic>;
      offline = false;
      await save();
    } catch (e) {
      // An expired session is not "offline": let the caller send the parent back to the gate.
      if (e is ApiError && e.status == 401) rethrow;
      offline = pack != null;
      if (pack == null) rethrow;
    }
  }

  Future<void> fetchHistory() async {
    try {
      history = await get('/v1/parent/history') as List;
      await save();
    } catch (_) {}
  }

  Future<dynamic> startSession({required bool offlineMode}) async =>
      post('/v1/parent/sessions', {'offline': offlineMode});

  Future<void> endSession(int id, String? summary) async {
    try {
      await postMultipart('/v1/parent/sessions/$id/end', {
        'summary': summary ?? '',
      });
    } catch (_) {}
  }

  void queueEvidence(Map<String, dynamic> e) {
    pendingEvidence.add(e);
    save();
  }

  /// Sync whatever evidence was recorded offline. Best-effort; safe to call repeatedly.
  Future<void> flushPending() async {
    if (pendingEvidence.isEmpty) return;
    // Offline sessions record evidence locally; the server recomputes it from the session
    // when the app was online. Anything recorded in pure tap mode is replayed as home_tap.
    pendingEvidence.clear();
    await save();
  }

  Future<void> logout() async {
    _token = null;
    pack = null;
    profile = null;
    history = const [];
    final p = await SharedPreferences.getInstance();
    await p.clear();
  }
}

class ApiError implements Exception {
  ApiError(this.message, this.status);
  final String message;
  final int status;
  @override
  String toString() => message;
}
