import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

/// Stream-based recorder: identical code path on Android, iOS and web. Streamed bytes carry no
/// container, so it records raw 16-bit PCM (16 kHz mono) and [stop] wraps it in a WAV header that
/// the speech-to-text service can decode. The bytes stay in memory; the caller uploads them and
/// never persists audio locally.
class Recorder {
  final AudioRecorder _r = AudioRecorder();
  final _chunks = BytesBuilder(copy: false);
  StreamSubscription<Uint8List>? _sub;
  int _sampleRate = 16000;

  Future<bool> start() async {
    try {
      if (!await _r.hasPermission()) return false;
      return await _listen(16000);
    } catch (_) {
      try {
        // some devices refuse 16 kHz; record at the plugin's default rate and label the WAV to match
        return await _listen(const RecordConfig().sampleRate);
      } catch (_) {
        return false;
      }
    }
  }

  Future<bool> _listen(int sampleRate) async {
    final stream = await _r.startStream(
      RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: sampleRate,
        numChannels: 1,
      ),
    );
    _sampleRate = sampleRate;
    _chunks.clear();
    _sub = stream.listen(_chunks.add);
    return true;
  }

  Future<Uint8List?> stop() async {
    try {
      await _r.stop();
      await _sub?.cancel();
      final pcm = _chunks.takeBytes();
      return pcm.isEmpty ? null : wavFromPcm16(pcm, sampleRate: _sampleRate);
    } catch (_) {
      return null;
    }
  }

  void dispose() {
    _sub?.cancel();
    _r.dispose();
  }
}

/// Wraps little-endian 16-bit PCM samples in a standard 44-byte RIFF/WAVE header.
Uint8List wavFromPcm16(
  Uint8List pcm, {
  int sampleRate = 16000,
  int channels = 1,
}) {
  const bytesPerSample = 2;
  final blockAlign = channels * bytesPerSample;
  final out = Uint8List(44 + pcm.length);
  final h = ByteData.sublistView(out, 0, 44);
  void tag(int at, String s) => out.setRange(at, at + 4, s.codeUnits);
  tag(0, 'RIFF');
  h.setUint32(4, 36 + pcm.length, Endian.little);
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  h.setUint32(16, 16, Endian.little); // fmt chunk size
  h.setUint16(20, 1, Endian.little); // PCM
  h.setUint16(22, channels, Endian.little);
  h.setUint32(24, sampleRate, Endian.little);
  h.setUint32(28, sampleRate * blockAlign, Endian.little); // byte rate
  h.setUint16(32, blockAlign, Endian.little);
  h.setUint16(34, bytesPerSample * 8, Endian.little);
  tag(36, 'data');
  h.setUint32(40, pcm.length, Endian.little);
  out.setRange(44, out.length, pcm);
  return out;
}
