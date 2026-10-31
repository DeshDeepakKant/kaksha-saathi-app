import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'l10n.dart';

class Api {
  Api._();
  static final Api i = Api._();
  static const _define = String.fromEnvironment('API_BASE');

  /// The live server (Render). Every build talks to it unless a developer deliberately overrides
  /// it with `--dart-define=API_BASE=...`; nothing falls back to a server on a laptop.
  static const productionBase = 'https://kaksha-saathi-558g.onrender.com';
  late final String base = _define.isNotEmpty ? _define : productionBase;

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
    await _startPrefs();
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
        final detail = (jsonDecode(utf8.decode(r.bodyBytes)) as Map)['detail'];
        if (detail is String && detail.isNotEmpty) {
          d = detail;
        } else if (detail is List && detail.isNotEmpty) {
          // FastAPI validation errors: [{loc: [...], msg: "..."}]
          final first = detail.first;
          d = first is Map && first['msg'] != null
              ? first['msg'].toString()
              : 'HTTP ${r.statusCode}';
        }
      } catch (_) {}
      throw ApiError(d, r.statusCode);
    }
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  /// Deletes this child's practice data (home sessions, voice sessions and their transcripts).
  /// The school's own records are not touched.
  Future<void> deleteMyData() async {
    final r = await http
        .delete(Uri.parse('$base/v1/parent/child/data'), headers: _h)
        .timeout(const Duration(seconds: 30));
    _read(r);
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

  Future<dynamic> consent(Map<String, dynamic> body) async {
    final r = _loginResponse(await post('/v1/parent/consent', body));
    await _prefsAfterLogin();
    return r;
  }

  Future<dynamic> login(Map<String, dynamic> body) async {
    final r = _loginResponse(await post('/v1/parent/login', body));
    await _prefsAfterLogin();
    return r;
  }

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

  /// Clears the session and the child's data from the phone. Kept: the app language, the
  /// language list and each parent's language/voice settings (no child data in them).
  Future<void> logout() async {
    _token = null;
    profile = null;
    prefs = null;
    final p = await SharedPreferences.getInstance();
    for (final k in p.getKeys().toList()) {
      if (k == 'lang' || k == 'languages' || k.startsWith('prefs.')) continue;
      await p.remove(k);
    }
  }

  // ---- language and voice (docs/lang_provider_contract.md §3, §5)

  static const _prefsPath = '/v1/parent/prefs';
  static const _prefFields = ['voice_provider', 'app_lang', 'content_lang'];

  /// This parent's `{voice_provider, app_lang, content_lang, stored}`; null when signed out.
  Map<String, dynamic>? prefs;
  bool _prefsDirty = false; // changed while offline; sent before the next read
  String? _titlesLang;
  Map<String, String> _titles = const {};
  bool _langHooked = false;

  /// Last `GET /v1/languages` (also kept on the phone for offline starts).
  Map<String, dynamic>? languagesData;

  /// The parent id from the token (`sub`), so settings are kept per parent on a shared phone.
  String get _uid {
    try {
      final part = _token!.split('.')[1];
      final m = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(part))),
      );
      return '${(m as Map)['sub'] ?? ''}';
    } catch (_) {
      return '';
    }
  }

  String get _prefsKey => 'prefs.$_uid';

  static Map<String, dynamic> _pickPrefs(Object? m) {
    final src = m is Map ? m : const {};
    return {
      'voice_provider': src['voice_provider'] ?? 'gnani',
      'app_lang': src['app_lang'] ?? 'en',
      'content_lang': src['content_lang'] ?? 'hi',
      'stored': src['stored'] == true,
    };
  }

  /// App start: apply the phone's copy at once (works offline), then refresh from the server.
  Future<void> _startPrefs() async {
    _hookLang();
    await _loadLanguagesLocal();
    if (!signedIn) return;
    await _loadLocalPrefs();
    unawaited(refreshPrefs().catchError((_) {}));
  }

  /// After sign-in: this parent's phone copy, then the server's (briefly awaited so Home already
  /// shows the right languages).
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

  /// A language switched elsewhere (the EN / हिं buttons) is saved for this parent too.
  void _hookLang() {
    if (_langHooked) return;
    _langHooked = true;
    Lang.code.addListener(() {
      final p = prefs;
      if (!signedIn || p == null || p['app_lang'] == Lang.code.value) return;
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
      r = await http
          .post(
            Uri.parse('$base$_prefsPath'),
            headers: {..._h, 'content-type': 'application/json'},
            body: jsonEncode({for (final f in _prefFields) f: p[f]}),
          )
          .timeout(const Duration(seconds: 20));
    } catch (_) {
      throw ApiError('network', 0);
    }
    return _pickPrefs(_read(r));
  }

  /// Reads this parent's prefs from the server (first sending a change made offline) and
  /// applies them. Throws when the server can't be reached.
  Future<void> refreshPrefs() async {
    if (!signedIn) return;
    Map<String, dynamic> server;
    if (_prefsDirty && prefs != null) {
      server = await _sendPrefs(prefs!);
    } else {
      server = _pickPrefs(await get(_prefsPath));
      // Never saved yet: keep the app language picked on the sign-in screen.
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
      if (fetchTitles && signedIn) {
        try {
          final j = await get('/v1/content/titles?lang=$content');
          final t = j is Map ? j['titles'] : null;
          if (t is Map) {
            _titles = t.map((k, v) => MapEntry('$k', '$v'));
            _titlesLang = content;
          }
        } catch (_) {}
      }
      if (_titlesLang == content) titles = _titles;
    }
    ContentLang.apply(content, titles);
    await _saveLocalPrefs();
  }

  Future<void> _loadLanguagesLocal() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = p.getString('languages');
      if (raw != null && raw.isNotEmpty) {
        languagesData = (jsonDecode(raw) as Map).cast<String, dynamic>();
      }
    } catch (_) {}
  }

  /// `GET /v1/languages`: app languages, content languages and voice services. Falls back to
  /// the last copy when offline.
  Future<Map<String, dynamic>> languages() async {
    try {
      final d = ((await get('/v1/languages')) as Map).cast<String, dynamic>();
      languagesData = d;
      try {
        final p = await SharedPreferences.getInstance();
        await p.setString('languages', jsonEncode(d));
      } catch (_) {}
      return d;
    } catch (_) {
      if (languagesData != null) return {...languagesData!, 'offline': true};
      rethrow;
    }
  }

  /// Server voice for [text] (`POST /v1/speech/tts`). Status 200 carries the audio; 204 = no
  /// service speaks [lang]; 0 = no network / not signed in. Never throws.
  Future<({int status, Uint8List? audio, String? mime})> speechTts(
    String text,
    String lang, {
    Duration timeout = const Duration(seconds: 12),
  }) async {
    if (!signedIn) return (status: 0, audio: null, mime: null);
    try {
      final r = await http
          .post(
            Uri.parse('$base/v1/speech/tts'),
            headers: {..._h, 'content-type': 'application/json'},
            body: jsonEncode({'text': text, 'lang': lang}),
          )
          .timeout(timeout);
      if (r.statusCode != 200 || r.bodyBytes.isEmpty) {
        return (status: r.statusCode, audio: null, mime: null);
      }
      return (status: 200, audio: r.bodyBytes, mime: r.headers['content-type']);
    } catch (_) {
      return (status: 0, audio: null, mime: null);
    }
  }
}

class ApiError implements Exception {
  ApiError(this.message, this.status);
  final String message;
  final int status;
  @override
  String toString() => message;
}
