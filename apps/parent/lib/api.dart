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

  /// Full home payload: {child, focus, streak}. `child` is the unwrapped identity map.
  Map<String, dynamic>? profile;

  Map<String, dynamic>? get child =>
      (profile?['child'] as Map?)?.cast<String, dynamic>();

  bool get signedIn => _token != null;

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    _token = p.getString('token');
    final pr = p.getString('profile');
    if (pr != null) profile = jsonDecode(pr) as Map<String, dynamic>;
    // left over from the removed short practice (offline pack, upload queue, practice history)
    for (final k in const ['pack', 'pending', 'history']) {
      await p.remove(k);
    }
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    if (_token != null) {
      await p.setString('token', _token!);
    } else {
      await p.remove('token');
    }
    if (profile != null) await p.setString('profile', jsonEncode(profile));
  }

  Map<String, String> get _h => {'Authorization': 'Bearer ${_token ?? ''}'};

  dynamic _read(http.Response r) {
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
        http.MultipartFile.fromBytes(field, audio, filename: 'turn.wav'),
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

  Future<void> logout() async {
    _token = null;
    profile = null;
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
