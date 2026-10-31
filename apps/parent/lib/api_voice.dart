import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'api.dart';
import 'l10n.dart';

/// The 30-minute voice session routes (docs/voice_session_contract.md). Session ids are used
/// as given by the server (int or string). Errors surface as [ApiError] like the rest of [Api].
extension VoiceApi on Api {
  Future<Map<String, dynamic>> startVoice(String lang) async =>
      _map(await post('/v1/parent/voice/sessions', {'lang': lang}));

  /// One answer. Reuse [clientTurnId] when retrying the same recording so the server can
  /// ignore a duplicate. Send [transcript] instead of [audio] when the parent typed the answer.
  Future<Map<String, dynamic>> voiceTurn(
    Object id, {
    required String itemId,
    required String clientTurnId,
    Uint8List? audio,
    double? durationS,
    String? transcript,
  }) async {
    final meta = {
      'item_id': itemId,
      'client_turn_id': clientTurnId,
      'duration_s': ?durationS,
      'transcript': ?transcript,
    };
    return _map(
      await postMultipart('/v1/parent/voice/sessions/$id/turn', {
        'meta': jsonEncode(meta),
      }, audio: transcript == null ? audio : null),
    );
  }

  Future<Map<String, dynamic>> voiceSkip(Object id, String itemId) async =>
      _map(
        await post('/v1/parent/voice/sessions/$id/skip', {
          'item_id': itemId,
          'client_turn_id': newTurnId(),
        }),
      );

  /// Ends the session and returns the Report. [reason]: `time_up` or `parent_stop`.
  Future<Map<String, dynamic>> voiceEnd(Object id, String reason) async =>
      _map(await post('/v1/parent/voice/sessions/$id/end', {'reason': reason}));

  Future<List<Map<String, dynamic>>> voiceSessions() async {
    final r = await get('/v1/parent/voice/sessions');
    return ((r as List?) ?? const [])
        .map((e) => (e as Map).cast<String, dynamic>())
        .toList();
  }

  /// `{session, report}`; `report` is null while the session is still active.
  Future<Map<String, dynamic>> voiceSession(Object id) async =>
      _map(await get('/v1/parent/voice/sessions/$id'));

  /// The next session's plan for the child in [lang] (docs/voice_focus_contract.md §1): focus
  /// stage, reason, placement, teacher override. Null when the server sent no focus stage.
  Future<Map<String, dynamic>?> voicePlan(String lang) async {
    final r = await get(
      '/v1/parent/voice/plan?lang=${Uri.encodeQueryComponent(lang)}',
    );
    if (r is! Map || r['focus_stage'] is! String) return null;
    return r.cast<String, dynamic>();
  }

  static Map<String, dynamic> _map(dynamic r) =>
      (r as Map).cast<String, dynamic>();
}

/// A random id for one upload (kept across retries of the same recording).
String newTurnId() {
  final r = Random.secure();
  return List.generate(
    16,
    (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();
}

/// Parent-facing message for a failed voice request.
String voiceErrorText(Object e) {
  if (e is ApiError) {
    if (e.status == 404 || e.status == 405) {
      return tr(
        'Voice sessions are not available on the server yet.',
        'सर्वर पर अभी आवाज़ वाला सत्र उपलब्ध नहीं है।',
      );
    }
    if (e.status == 401) {
      return tr(
        'Your sign-in has expired. Please sign in again.',
        'लॉग-इन का समय खत्म हो गया। कृपया फिर से लॉग-इन करें।',
      );
    }
    if (e.status >= 500) {
      return tr(
        'Saathi had a problem on the server. Please try again.',
        'सर्वर पर साथी को दिक्कत आई। कृपया फिर से कोशिश करें।',
      );
    }
    return e.message;
  }
  return tr(
    'Could not reach Saathi. Check the internet and try again.',
    'साथी तक नहीं पहुँच पाए। इंटरनेट देखकर फिर से कोशिश करें।',
  );
}

/// Ladder stage names, in order (backend voice_types.STAGES).
const voiceStages = [
  'letter',
  'word_build',
  'word_read',
  'sentence_build',
  'reading',
];

String voiceStageLabel(String? s) => switch (s) {
  'letter' => tr('Letters', 'अक्षर'),
  'word_build' => tr('Making words', 'शब्द बनाना'),
  'word_read' => tr('Reading words', 'शब्द पढ़ना'),
  'sentence_build' => tr('Sentences', 'वाक्य'),
  'reading' => tr('Reading', 'पढ़ना'),
  _ => s ?? '',
};

/// The session's phase (`placement` / `warmup` / `focus` / `stretch`) as a short label.
String voicePhaseLabel(String? p) => switch (p) {
  'placement' => tr('Finding the level', 'स्तर पता कर रहे हैं'),
  'warmup' => tr('Warm-up', 'शुरुआती अभ्यास'),
  'focus' => tr('Practice', 'अभ्यास'),
  'stretch' => tr('Challenge', 'चुनौती'),
  _ => '',
};
