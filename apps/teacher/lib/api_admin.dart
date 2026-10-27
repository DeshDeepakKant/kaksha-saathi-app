import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'l10n.dart';

/// Teacher-friendly text for an error from the API (or from the network layer).
/// 401 is handled globally (back to login), so it only gets a short line here.
String friendlyError(Object e) {
  final generic = tr(
    'Something went wrong, please try again',
    'कुछ गड़बड़ हो गई, कृपया दोबारा कोशिश करें',
  );
  if (e is! ApiError) return generic;
  final m = e.message.trim();
  if (e.status == 0) {
    // Api.postJson already words a lost connection for the teacher.
    return m.isEmpty ? generic : m;
  }
  if (e.status >= 500) return generic;
  if (e.status == 401) {
    return tr('Please log in again', 'कृपया दोबारा लॉगिन करें');
  }
  if (e.status == 422 || m.isEmpty || m.startsWith('HTTP ')) {
    return e.status == 422
        ? tr('Please check what you typed', 'कृपया लिखा हुआ जाँच लें')
        : generic;
  }
  // Pydantic-style detail lists are not for teachers.
  if (m.startsWith('[') || m.startsWith('{')) return generic;
  if (m.toLowerCase().contains('roll number already used')) {
    return tr(
      'This roll number is already used in the class',
      'यह रोल नंबर कक्षा में पहले से है',
    );
  }
  return m;
}

/// Wrappers for class / roster / subject setup and the child-data tools.
/// Static functions (not an extension) so they can never clash with another file's wrappers.
abstract final class AdminApi {
  static List<Map<String, dynamic>> _maps(dynamic v) => v is List
      ? v.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList()
      : <Map<String, dynamic>>[];

  /// `POST /v1/classes`. A duplicate grade + section comes back as ApiError(409).
  static Future<Map<String, dynamic>> createClass(
    int grade,
    String section, {
    String? label,
  }) async {
    final r = await Api.i.postJson('/v1/classes', {
      'grade': grade,
      'section': section,
      if (label != null && label.trim().isNotEmpty) 'label': label.trim(),
    });
    return (r as Map).cast<String, dynamic>();
  }

  /// `GET /v1/classes/{id}/subjects`: the school's subjects (built-ins first).
  static Future<List<Map<String, dynamic>>> subjects(int classId) async =>
      _maps(await Api.i.get('/v1/classes/$classId/subjects'));

  /// `POST /v1/subjects`.
  static Future<Map<String, dynamic>> createSubject(
    String name, {
    String? nameHi,
  }) async {
    final r = await Api.i.postJson('/v1/subjects', {
      'name': name.trim(),
      if (nameHi != null && nameHi.trim().isNotEmpty) 'name_hi': nameHi.trim(),
    });
    return (r as Map).cast<String, dynamic>();
  }

  static Future<List<Map<String, dynamic>>> roster(int classId) async =>
      _maps(await Api.i.get('/v1/classes/$classId/roster'));

  /// `POST /v1/classes/{id}/children`. Adds are not idempotent, so no outbox: errors are shown.
  /// The bulk route takes a bare JSON array, which `Api.postJson` (Map bodies) cannot send, so
  /// "paste many" calls this once per name.
  static Future<void> addChild(
    int classId,
    String firstName,
    int rollNo, {
    String? consentSource,
  }) => Api.i.postJson('/v1/classes/$classId/children', {
    'first_name': firstName.trim(),
    'roll_no': rollNo,
    'consent_source': ?consentSource,
  });

  /// Source recorded when the teacher confirms the parent's signed paper form.
  static const consentSource = 'parent_form_paper';

  /// `PATCH /v1/children/{id}/consent` (form field `source`). `Api` has no PATCH helper, so
  /// this reads the saved session token the same way `Api.loadSession` does.
  static Future<void> recordConsent(int childId, String source) async {
    await _send(
      'PATCH',
      '/v1/children/$childId/consent',
      form: {'source': source},
    );
  }

  /// `GET /v1/children/{id}/export`, always fresh (not stored in the offline cache).
  static Future<dynamic> exportChild(int childId) =>
      _send('GET', '/v1/children/$childId/export');

  static Future<void> deleteChildData(int childId) =>
      Api.i.delete('/v1/children/$childId/data');

  static Future<void> deleteClassData(int classId) =>
      Api.i.delete('/v1/classes/$classId/data');

  static Future<dynamic> _send(
    String method,
    String path, {
    Map<String, String>? form,
  }) async {
    final http.Response r;
    try {
      final p = await SharedPreferences.getInstance();
      final req = http.Request(method, Uri.parse('${Api.i.base}$path'))
        ..headers['Authorization'] = 'Bearer ${p.getString('token') ?? ''}';
      if (form != null) req.bodyFields = form;
      r = await http.Response.fromStream(
        await req.send().timeout(const Duration(seconds: 30)),
      );
    } catch (_) {
      throw ApiError(
        tr(
          'No internet. Try again when the network is back.',
          'इंटरनेट नहीं है। नेटवर्क वापस आने पर दोबारा कोशिश करें।',
        ),
        0,
      );
    }
    if (r.statusCode >= 400) {
      var detail = 'HTTP ${r.statusCode}';
      try {
        final j = jsonDecode(utf8.decode(r.bodyBytes));
        if (j is Map && j['detail'] != null) detail = j['detail'].toString();
      } catch (_) {}
      if (r.statusCode == 401 && Api.i.loggedIn) {
        Api.i.logout();
        Api.i.onSessionExpired?.call();
      }
      throw ApiError(detail, r.statusCode);
    }
    return jsonDecode(utf8.decode(r.bodyBytes));
  }
}
