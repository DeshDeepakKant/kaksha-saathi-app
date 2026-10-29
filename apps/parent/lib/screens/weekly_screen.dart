import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../api.dart';
import '../session_guard.dart';
import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';
import '../widgets/weekly_card.dart';

/// Weekly summary (`GET /v1/parent/weekly`): one card for the week that can be read aloud or
/// shared as an image. Progress words only, no scores, ranks or comparisons.
class WeeklyScreen extends StatefulWidget {
  const WeeklyScreen({super.key});
  @override
  State<WeeklyScreen> createState() => _WeeklyScreenState();
}

class _WeeklyScreenState extends State<WeeklyScreen> {
  final _cardKey = GlobalKey();
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  bool _speaking = false;
  bool _sharing = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    Speak.stop();
    super.dispose();
  }

  String get _name => (Api.i.child?['first_name'] ?? '').toString();

  Future<void> _load({bool quiet = false}) async {
    if (!quiet) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final r = await Api.i.get('/v1/parent/weekly');
      if (!mounted) return;
      setState(() {
        _data = (r as Map).cast<String, dynamic>();
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      if (await handleExpiredSession(context, e)) return;
      if (quiet && _data != null) {
        _snack(_errorText(e));
      } else {
        setState(() => _error = _errorText(e));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  static String _errorText(Object e) {
    if (e is ApiError) {
      if (e.status == 404 || e.status == 405) {
        return tr(
          'The weekly summary is not ready on the server yet. Please check again later.',
          'हफ़्ते का सार अभी सर्वर पर तैयार नहीं है। थोड़ी देर बाद फिर देखें।',
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
          'Something went wrong on the server. Please try again.',
          'सर्वर पर कुछ गड़बड़ हुई। कृपया फिर से कोशिश करें।',
        );
      }
      return e.message;
    }
    return tr(
      'Could not load this week. Check the internet and try again.',
      'इस हफ़्ते का सार नहीं आ पाया। इंटरनेट देखकर फिर से कोशिश करें।',
    );
  }

  void _snack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _toggleRead(WeeklyData w) async {
    if (_speaking) {
      await Speak.stop();
      if (mounted) setState(() => _speaking = false);
      return;
    }
    setState(() => _speaking = true);
    await Speak.say(weeklySpeech(w, _name), Lang.isHi ? 'hi' : 'en');
    if (mounted) setState(() => _speaking = false);
  }

  /// The card as PNG bytes, or null when it is not on screen.
  Future<Uint8List?> _capture() async {
    await WidgetsBinding.instance.endOfFrame;
    final ro = _cardKey.currentContext?.findRenderObject();
    if (ro is! RenderRepaintBoundary) return null;
    final image = await ro.toImage(pixelRatio: 3);
    try {
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      return data?.buffer.asUint8List();
    } finally {
      image.dispose();
    }
  }

  /// Shares the card image (the share sheet offers WhatsApp); on the web or on any failure the
  /// text summary goes to the clipboard instead.
  Future<void> _share(WeeklyData w) async {
    if (_sharing) return;
    setState(() => _sharing = true);
    var shared = false;
    if (!kIsWeb) {
      try {
        final png = await _capture();
        if (png != null) {
          final r = await SharePlus.instance.share(
            ShareParams(
              files: [XFile.fromData(png, mimeType: 'image/png')],
              fileNameOverrides: const ['kaksha_week.png'],
              text: weeklyLine(w, _name),
            ),
          );
          shared = r.status != ShareResultStatus.unavailable;
        }
      } catch (_) {}
    }
    if (!shared) {
      try {
        await Clipboard.setData(ClipboardData(text: weeklyShareText(w, _name)));
        _snack(
          tr(
            'Copied: paste it in WhatsApp',
            'कॉपी हो गया: WhatsApp में चिपकाएँ',
          ),
        );
      } catch (_) {
        _snack(
          tr(
            'Could not share right now. Please try again.',
            'अभी भेज नहीं पाए। कृपया फिर से कोशिश करें।',
          ),
        );
      }
    }
    if (mounted) setState(() => _sharing = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('This week', 'इस हफ़्ते'))),
      body: SafeArea(child: _body()),
    );
  }

  Widget _body() {
    final d = _data;
    if (_loading && d == null) {
      return Loading(
        label: tr('Getting this week’s summary…', 'इस हफ़्ते का सार आ रहा है…'),
      );
    }
    if (d == null) {
      return RefreshIndicator(
        color: Ks.accent,
        onRefresh: () => _load(quiet: true),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 40),
            EmptyState(
              icon: Icons.wifi_off_rounded,
              text:
                  _error ??
                  tr('Nothing to show yet.', 'अभी दिखाने के लिए कुछ नहीं है।'),
            ),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Try again', 'फिर से कोशिश करें')),
            ),
          ],
        ),
      );
    }
    final w = WeeklyData.from(d);
    return RefreshIndicator(
      color: Ks.accent,
      onRefresh: () => _load(quiet: true),
      // Not a lazy ListView: the card must stay built so it can be captured for sharing.
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(6, 6, 6, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            WeeklyCard(data: w, name: _name, boundaryKey: _cardKey),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: 6),
                  FilledButton.icon(
                    onPressed: _sharing ? null : () => _share(w),
                    icon: _sharing
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2.5),
                          )
                        : const Icon(Icons.share_rounded),
                    label: Text(tr('Share on WhatsApp', 'WhatsApp पर भेजें')),
                  ),
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    onPressed: () => _toggleRead(w),
                    icon: Icon(
                      _speaking ? Icons.stop_rounded : Icons.volume_up_rounded,
                      color: Ks.accent,
                    ),
                    label: Text(
                      _speaking
                          ? tr('Stop', 'रोकें')
                          : tr('Read aloud', 'सुनाएँ'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
