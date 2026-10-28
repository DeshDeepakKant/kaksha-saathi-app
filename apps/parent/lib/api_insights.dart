import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

/// Parent insights routes (docs/parent_insights_contract.md). Own child only; every text field
/// comes as `*_hi` / `*_en`. Errors surface as [ApiError] like the rest of [Api].
extension InsightsApi on Api {
  /// `{class_topic, child_focus, line_hi, line_en, as_of}`.
  Future<Map<String, dynamic>> schoolWeek() async =>
      _map(await get('/v1/parent/school_week'));

  /// Up to 3 tips for mistakes the teacher saw.
  Future<List<Map<String, dynamic>>> tips() async =>
      _list((await get('/v1/parent/tips') as Map?)?['tips']);

  /// Celebrations (`kind: celebration`) and absent-day catch-ups (`kind: catch_up`).
  Future<List<Map<String, dynamic>>> moments() async =>
      _list((await get('/v1/parent/moments') as Map?)?['moments']);

  /// `{subject, grade, milestones, counts, celebrations, growth}` for `numeracy` / `literacy`.
  Future<Map<String, dynamic>> journey(String subject) async => _map(
    await get(
      '/v1/parent/journey?subject=${Uri.encodeQueryComponent(subject)}',
    ),
  );

  /// This school week's summary (Monday–Sunday, IST).
  Future<Map<String, dynamic>> weekly() async =>
      _map(await get('/v1/parent/weekly'));

  static Map<String, dynamic> _map(dynamic r) =>
      (r as Map).cast<String, dynamic>();

  static List<Map<String, dynamic>> _list(dynamic r) =>
      ((r as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();
}

/// Stable id of a moment; it includes the moment's date, so a new moment for the same lesson
/// shows again after an older one was dismissed.
String momentKey(Map m) => m['kind'] == 'catch_up'
    ? 'catch_up:${m['day']}'
    : 'celebration:${m['checkpoint_id']}:${m['at']}';

const _dismissedKey = 'moments_dismissed';

/// Moment ids the parent has hidden on Home.
Future<Set<String>> dismissedMoments() async {
  try {
    final p = await SharedPreferences.getInstance();
    return (p.getStringList(_dismissedKey) ?? const []).toSet();
  } catch (_) {
    return {};
  }
}

/// Remembers a hidden moment (the newest 40 are kept; moments are at most 14 days old).
Future<void> dismissMoment(String key) async {
  try {
    final p = await SharedPreferences.getInstance();
    final keys = (p.getStringList(_dismissedKey) ?? <String>[])
      ..remove(key)
      ..add(key);
    final start = keys.length > 40 ? keys.length - 40 : 0;
    await p.setStringList(_dismissedKey, keys.sublist(start));
  } catch (_) {}
}
