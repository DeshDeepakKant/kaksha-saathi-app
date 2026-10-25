import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

/// Stream-based recorder: identical code path on Android (AAC/M4A) and web (Opus/WebM).
/// The bytes stay in memory; the caller uploads them and never persists audio locally.
class Recorder {
  final AudioRecorder _r = AudioRecorder();
  final _chunks = BytesBuilder(copy: false);
  StreamSubscription<Uint8List>? _sub;

  Future<bool> start() async {
    try {
      if (!await _r.hasPermission()) return false;
      final stream = await _r.startStream(
        const RecordConfig(
          encoder: AudioEncoder.aacLc,
          sampleRate: 16000,
          numChannels: 1,
        ),
      );
      _chunks.clear();
      _sub = stream.listen(_chunks.add);
      return true;
    } catch (_) {
      try {
        final stream = await _r.startStream(
          const RecordConfig(sampleRate: 16000, numChannels: 1),
        );
        _chunks.clear();
        _sub = stream.listen(_chunks.add);
        return true;
      } catch (_) {
        return false;
      }
    }
  }

  Future<Uint8List?> stop() async {
    try {
      await _r.stop();
      await _sub?.cancel();
      final bytes = _chunks.takeBytes();
      return bytes.isEmpty ? null : bytes;
    } catch (_) {
      return null;
    }
  }

  void dispose() {
    _sub?.cancel();
    _r.dispose();
  }
}
