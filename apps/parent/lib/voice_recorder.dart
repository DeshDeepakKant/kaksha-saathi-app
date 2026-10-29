import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import 'wav.dart';

/// One recorded answer, in memory only (never written to disk).
class VoiceTake {
  VoiceTake(this.wav, this.durationS, {required this.heardSpeech});
  final Uint8List wav;
  final double durationS;

  /// Whether the level detector heard anything like speech (the audio is uploaded either way,
  /// so a quiet child is still judged by the server).
  final bool heardSpeech;
}

/// The microphone could not be used ([denied]: the permission was refused).
class MicError implements Exception {
  const MicError({this.denied = false});
  final bool denied;
}

/// 16 kHz mono PCM16 recorder with end-of-speech detection.
///
/// The level is measured from the PCM stream itself (RMS in dBFS), which behaves the same on
/// Android and the web. The noise floor is learned from the first moments of each take, so a
/// noisy room raises the speech threshold. A turn ends when, after speech, the level stays
/// below the threshold for [silence]; or [maxRecordS] after speech began; or when the child
/// never starts, [maxRecordS] + [waitForSpeech] after the mic opened; or on [finish].
class VoiceRecorder {
  /// Replaced in tests, which cannot use the platform plugin.
  @visibleForTesting
  static AudioRecorder Function() recorderFactory = AudioRecorder.new;

  final _rec = recorderFactory();
  StreamSubscription<Uint8List>? _sub;
  Completer<bool>? _end; // true = keep the take, false = discard
  Timer? _cap;
  bool _disposed = false;
  // Bumped by cancel(): a listen() still waiting for the permission dialog gives up quietly.
  int _epoch = 0;

  /// 0..1 input level for a meter.
  final level = ValueNotifier<double>(0);

  /// True while the child is speaking (above the threshold).
  final speaking = ValueNotifier<bool>(false);

  static const _rate = 16000;
  static const _bytesPerMs = _rate * 2 / 1000; // PCM16 mono

  /// Safety net for a permission request that never returns.
  static const permissionTimeout = Duration(seconds: 60);

  /// Whether the permission is granted now, without showing the dialog (used when the app
  /// comes back from Settings). Never throws.
  Future<bool> permissionGranted() async {
    try {
      return await _rec
          .hasPermission(request: false)
          .timeout(const Duration(seconds: 5), onTimeout: () => false);
    } catch (_) {
      return false;
    }
  }

  bool get active => _end != null && !_end!.isCompleted;

  /// Records one answer. Returns null when [cancel]led; throws [MicError] when the mic is
  /// unavailable or permission is refused.
  Future<VoiceTake?> listen({
    required int maxRecordS,
    Duration silence = const Duration(milliseconds: 1500),
    Duration waitForSpeech = const Duration(seconds: 6),
  }) async {
    await cancel();
    final epoch = _epoch;
    bool ok;
    try {
      // The first call shows the system permission dialog and resolves only when the parent
      // answers, however long that takes, so a slow dialog is never mistaken for a refusal.
      // The long timeout is only a safety net for a call that never returns (not a denial).
      ok = await _rec.hasPermission().timeout(
        permissionTimeout,
        onTimeout: () => throw const MicError(),
      );
    } on MicError {
      rethrow;
    } catch (_) {
      throw const MicError();
    }
    // Cancelled (pause, skip, leave) while the dialog was up.
    if (_disposed || epoch != _epoch) return null;
    if (!ok) throw const MicError(denied: true);

    final end = Completer<bool>();
    _end = end;
    final buf = BytesBuilder(copy: false);
    Stream<Uint8List> stream;
    try {
      stream = await _rec
          .startStream(
            const RecordConfig(
              encoder: AudioEncoder.pcm16bits,
              sampleRate: _rate,
              numChannels: 1,
            ),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {
      _end = null;
      try {
        await _rec.stop();
      } catch (_) {}
      throw const MicError();
    }
    if (end.isCompleted) {
      // Cancelled while the mic was opening.
      try {
        await _rec.stop();
      } catch (_) {}
      return null;
    }

    final maxMs = math.max(2, maxRecordS) * 1000;
    var totalMs = 0.0;
    var speechMs = 0.0; // continuous loud time (debounces clicks)
    var quietMs = 0.0;
    double? onsetMs;
    var heard = false;
    // Noise floor: average of the first ~300 ms, then follows quiet stretches slowly.
    var floorSum = 0.0;
    var floorN = 0;
    double? floor;

    void done(bool keep) {
      if (!end.isCompleted) end.complete(keep);
    }

    _sub = stream.listen(
      (chunk) {
        buf.add(chunk);
        final ms = chunk.length / _bytesPerMs;
        totalMs += ms;
        final db = _dbfs(chunk);
        if (_disposed) return;
        level.value = ((db + 60) / 50).clamp(0.0, 1.0);
        if (floor == null) {
          floorSum += db;
          floorN++;
          if (totalMs >= 300) floor = floorSum / floorN;
        }
        final f = floor ?? -55.0;
        final threshold = (f + 12).clamp(-50.0, -28.0);
        final loud = db > threshold || (floor == null && db > -30);
        if (loud) {
          speechMs += ms;
          quietMs = 0;
          if (!heard && speechMs >= 180) {
            heard = true;
            onsetMs = totalMs - speechMs;
          }
        } else {
          speechMs = 0;
          quietMs += ms;
          if (floor != null && db < f + 6) floor = f * 0.97 + db * 0.03;
        }
        speaking.value = loud && heard;
        if (heard && quietMs >= silence.inMilliseconds) done(true);
        if (onsetMs != null && totalMs - onsetMs! >= maxMs) done(true);
      },
      onError: (_) => done(true),
      onDone: () => done(true),
    );
    _cap = Timer(
      Duration(milliseconds: maxMs) + waitForSpeech,
      () => done(true),
    );

    final keep = await end.future;
    _cap?.cancel();
    try {
      await _rec.stop();
    } catch (_) {}
    await _sub?.cancel();
    _sub = null;
    if (_disposed) return null;
    level.value = 0;
    speaking.value = false;
    if (identical(_end, end)) _end = null;
    final pcm = buf.takeBytes();
    if (!keep) return null;
    if (pcm.isEmpty) return VoiceTake(Uint8List(0), 0, heardSpeech: false);
    return VoiceTake(
      wavFromPcm16(pcm, sampleRate: _rate),
      pcm.length / (_bytesPerMs * 1000),
      heardSpeech: heard,
    );
  }

  /// Ends the current take now and keeps it (the "Done" button).
  void finish() {
    final e = _end;
    if (e != null && !e.isCompleted) e.complete(true);
  }

  /// Stops and discards the current take (pause, skip, leaving the screen).
  Future<void> cancel() async {
    _epoch++;
    final e = _end;
    if (e != null && !e.isCompleted) e.complete(false);
    _cap?.cancel();
  }

  void dispose() {
    _disposed = true;
    cancel();
    _sub?.cancel();
    _rec.dispose();
    level.dispose();
    speaking.dispose();
  }

  /// RMS level of little-endian PCM16 in dBFS (-90 for silence).
  static double _dbfs(Uint8List b) {
    final n = b.length ~/ 2;
    if (n == 0) return -90;
    final d = ByteData.sublistView(b);
    var sum = 0.0;
    for (var i = 0; i < n; i++) {
      final s = d.getInt16(i * 2, Endian.little);
      sum += s * s;
    }
    final rms = math.sqrt(sum / n) / 32768.0;
    return rms <= 0.00003 ? -90 : 20 * math.log(rms) / math.ln10;
  }
}
