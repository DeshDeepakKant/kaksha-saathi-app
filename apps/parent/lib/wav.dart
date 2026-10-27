import 'dart:typed_data';

/// Wraps raw little-endian PCM16 (what `record` streams on every platform) in a 44-byte
/// WAV header so the speech-to-text service can decode it.
Uint8List wavFromPcm16(
  Uint8List pcm, {
  int sampleRate = 16000,
  int channels = 1,
}) {
  final h = ByteData(44);
  void tag(int at, String s) {
    for (var i = 0; i < 4; i++) {
      h.setUint8(at + i, s.codeUnitAt(i));
    }
  }

  tag(0, 'RIFF');
  h.setUint32(4, 36 + pcm.length, Endian.little);
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  h.setUint32(16, 16, Endian.little); // fmt chunk size
  h.setUint16(20, 1, Endian.little); // PCM
  h.setUint16(22, channels, Endian.little);
  h.setUint32(24, sampleRate, Endian.little);
  h.setUint32(28, sampleRate * channels * 2, Endian.little); // byte rate
  h.setUint16(32, channels * 2, Endian.little); // block align
  h.setUint16(34, 16, Endian.little); // bits per sample
  tag(36, 'data');
  h.setUint32(40, pcm.length, Endian.little);
  return (BytesBuilder(copy: false)
        ..add(h.buffer.asUint8List())
        ..add(pcm))
      .takeBytes();
}
