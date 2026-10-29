import 'package:flutter/material.dart';

import '../api.dart';
import '../session_guard.dart';
import '../l10n.dart';
import '../theme.dart';
import '../tts.dart';
import '../widgets/journey_celebrations.dart';
import '../widgets/journey_growth.dart';
import '../widgets/journey_path.dart';

/// The child's learning journey for one subject (contract `GET /parent/journey`): the class
/// roadmap as a trail of stars, recent celebrations and a small growth line. Progress is shown
/// as counts of steps, never as scores, grades or comparisons.
class JourneyScreen extends StatefulWidget {
  const JourneyScreen({super.key});
  @override
  State<JourneyScreen> createState() => _JourneyScreenState();
}

class _JourneyScreenState extends State<JourneyScreen> {
  String _subject = 'numeracy';
  final Map<String, Map<String, dynamic>> _data = {};
  String? _error;
  bool _loading = false;
  int _request = 0; // only the latest request may update the screen
  final _currentKey = GlobalKey();

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

  // ---- data ------------------------------------------------------------------------------

  Future<void> _load({bool refresh = false}) async {
    final subject = _subject;
    final req = ++_request;
    setState(() {
      _error = null;
      _loading = !refresh || !_data.containsKey(subject);
    });
    try {
      final r = await Api.i.get('/v1/parent/journey?subject=$subject');
      if (!mounted || req != _request) return;
      setState(() {
        _data[subject] = (r as Map).cast<String, dynamic>();
        _loading = false;
      });
      // Opens at the top (name, celebrations, growth). "Go to current step" jumps to the trail.
    } catch (e) {
      if (!mounted || req != _request) return;
      if (await handleExpiredSession(context, e)) return;
      if (!mounted) return;
      final msg = _errorText(e);
      if (refresh && _data.containsKey(subject)) {
        setState(() => _loading = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(msg)));
      } else {
        setState(() {
          _loading = false;
          _error = msg;
        });
      }
    }
  }

  void _switch(String subject) {
    if (subject == _subject) return;
    Speak.stop();
    setState(() {
      _subject = subject;
      _error = null;
    });
    if (!_data.containsKey(subject)) _load();
  }

  void _scrollToCurrent() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final c = _currentKey.currentContext;
      if (!mounted || c == null) return;
      Scrollable.ensureVisible(
        c,
        alignment: 0.35,
        duration: const Duration(milliseconds: 700),
        curve: Curves.easeOutCubic,
      );
    });
  }

  static String _errorText(Object e) {
    if (e is ApiError) {
      if (e.status == 404 || e.status == 405) {
        return tr(
          'The learning journey is not ready on the server yet. Please check again later.',
          'सीखने का सफ़र अभी सर्वर पर तैयार नहीं है। थोड़ी देर बाद फिर देखें।',
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
          'The server had a problem. Please try again.',
          'सर्वर पर दिक्कत आई। कृपया फिर से कोशिश करें।',
        );
      }
      return e.message;
    }
    return tr(
      'Could not connect. Check the internet and try again.',
      'जुड़ नहीं पाए। इंटरनेट देखकर फिर से कोशिश करें।',
    );
  }

  static List<Map<String, dynamic>> _maps(Object? v) =>
      ((v as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();

  static int _int(Object? v) => (v as num?)?.round() ?? 0;

  String get _name {
    final n = (Api.i.child?['first_name'] ?? '').toString().trim();
    return n.isNotEmpty ? n : tr('Your child', 'आपका बच्चा');
  }

  // ---- build -----------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Learning journey', 'सीखने का सफ़र')),
        actions: [
          TextButton(
            onPressed: () => Lang.set(Lang.isHi ? 'en' : 'hi'),
            style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
            child: Text(Lang.isHi ? 'EN' : 'हिं'),
          ),
        ],
      ),
      floatingActionButton:
          (_loading || _error != null || !_data.containsKey(_subject))
          ? null
          : FloatingActionButton.extended(
              onPressed: _scrollToCurrent,
              icon: const Icon(Icons.flag_rounded),
              label: Text(tr('Go to current step', 'अभी के कदम पर जाएँ')),
            ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 4, 18, 8),
              child: SizedBox(
                width: double.infinity,
                child: SegmentedButton<String>(
                  showSelectedIcon: false,
                  style: SegmentedButton.styleFrom(
                    minimumSize: const Size(0, 48),
                    textStyle: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  segments: [
                    ButtonSegment(
                      value: 'numeracy',
                      icon: const Icon(Icons.calculate_rounded),
                      label: Text(tr('Maths', 'गणित')),
                    ),
                    ButtonSegment(
                      value: 'literacy',
                      icon: const Icon(Icons.menu_book_rounded),
                      label: Text(tr('Hindi', 'हिंदी')),
                    ),
                    ButtonSegment(
                      value: 'english',
                      icon: const Icon(Icons.translate_rounded),
                      label: Text(tr('English', 'अंग्रेज़ी')),
                    ),
                  ],
                  selected: {_subject},
                  onSelectionChanged: (s) => _switch(s.first),
                ),
              ),
            ),
            Expanded(child: _body()),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    final d = _data[_subject];
    if (_loading && d == null) {
      return Loading(
        label: tr('Getting the journey…', 'सफ़र तैयार हो रहा है…'),
      );
    }
    if (d == null) {
      return _scrollable([
        const SizedBox(height: 40),
        EmptyState(
          icon: Icons.wifi_off_rounded,
          text: _error ?? tr('Nothing to show yet.', 'अभी दिखाने को कुछ नहीं।'),
        ),
        Center(
          child: FilledButton.icon(
            style: FilledButton.styleFrom(minimumSize: const Size(160, 56)),
            onPressed: _load,
            icon: const Icon(Icons.refresh_rounded),
            label: Text(tr('Try again', 'फिर से कोशिश करें')),
          ),
        ),
      ]);
    }

    final milestones = _maps(d['milestones']);
    final celebrations = _maps(d['celebrations']);
    final growth = _maps(d['growth']);
    if (milestones.isEmpty) {
      return _scrollable([
        _header(d, milestones),
        const SizedBox(height: 24),
        EmptyState(
          icon: Icons.route_rounded,
          text: trf(
            'The journey will appear here once the teacher starts this subject with the class. '
                'Every step {name} learns will light up as a star.',
            'जब टीचर कक्षा में यह विषय शुरू करेंगे, सफ़र यहाँ दिखेगा। '
                '{name} जो भी कदम सीखेंगे, वह तारे की तरह चमकेगा।', {'name': _name},
          ),
        ),
      ]);
    }

    var current = milestones.indexWhere((m) => m['state'] == 'working');
    if (current < 0) {
      current = milestones.indexWhere((m) => m['state'] == 'next');
    }
    final showGrowth =
        growth.length > 1 && growth.any((g) => _int(g['learned']) > 0);

    return _scrollable([
      _header(d, milestones),
      if (celebrations.isNotEmpty) ...[
        const SizedBox(height: 16),
        JourneyCelebrations(
          key: ValueKey('cel-$_subject'),
          items: celebrations,
        ),
      ],
      if (showGrowth) ...[
        const SizedBox(height: 12),
        JourneyGrowth(points: growth),
      ],
      const SizedBox(height: 18),
      SectionTitle(tr('Step by step', 'कदम-दर-कदम')),
      _legend(),
      const SizedBox(height: 4),
      JourneyPath(
        key: ValueKey('path-$_subject'),
        milestones: milestones,
        currentIndex: current < 0 ? null : current,
        currentKey: _currentKey,
      ),
      const SizedBox(height: 24),
    ]);
  }

  /// Pull-to-refresh needs a scrollable even for short content. A Column (not a lazy ListView)
  /// so the current milestone is always built and can be scrolled to.
  Widget _scrollable(List<Widget> children) => RefreshIndicator(
    color: Ks.accent,
    onRefresh: () => _load(refresh: true),
    child: SingleChildScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(18, 4, 18, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    ),
  );

  Widget _header(Map<String, dynamic> d, List<Map<String, dynamic>> ms) {
    final counts = (d['counts'] as Map?) ?? const {};
    final total = counts['total'] != null ? _int(counts['total']) : ms.length;
    final learned = counts['learned'] != null
        ? _int(counts['learned'])
        : ms.where((m) => m['state'] == 'learned').length;
    final working = counts['working'] != null
        ? _int(counts['working'])
        : ms.where((m) => m['state'] == 'working').length;
    final name = _name;
    final subject = switch (_subject) {
      'literacy' => tr('Hindi', 'हिंदी'),
      'english' => tr('English', 'अंग्रेज़ी'),
      _ => tr('Maths', 'गणित'),
    };
    final grade = (d['grade'] ?? '').toString();

    final String sentence;
    if (total == 0) {
      sentence = trf(
        '{name}’s {subject} journey is about to begin.',
        '{name} का {subject} का सफ़र बस शुरू होने वाला है।', {'name': name, 'subject': subject},
      );
    } else if (learned == 0) {
      sentence = trf(
        '{name} is just starting the {subject} path of {total} steps. '
            'Each step learned at school will turn into a star.',
        '{name} ने {subject} के {total} कदमों का सफ़र अभी शुरू किया है। '
            'स्कूल में सीखा हर कदम एक तारा बन जाएगा।', {'name': name, 'subject': subject, 'total': total},
      );
    } else {
      sentence = trf(
        '{name} has learned {learned} of {total} steps.',
        '{name} ने {total} में से {learned} कदम सीख लिए हैं।', {'name': name, 'learned': learned, 'total': total},
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: const BoxDecoration(
                color: Ks.green,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.star_rounded,
                color: journeyGold,
                size: 34,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    trf('{name}’s journey', '{name} का सफ़र', {'name': name}),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  if (grade.isNotEmpty)
                    Text(
                      trf('Class {grade} · {subject}', 'कक्षा {grade} · {subject}', {'grade': grade, 'subject': subject}),
                      style: const TextStyle(color: Ks.muted, fontSize: 14),
                    ),
                  const SizedBox(height: 6),
                  Text(
                    sentence,
                    style: const TextStyle(fontSize: 17, height: 1.45),
                  ),
                  if (working > 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        working == 1
                            ? tr(
                                'Working on 1 step right now.',
                                'अभी 1 कदम पर काम चल रहा है।',
                              )
                            : trf(
                                'Working on {working} steps right now.',
                                'अभी {working} कदमों पर काम चल रहा है।', {'working': working},
                              ),
                        style: const TextStyle(
                          fontSize: 15,
                          color: Ks.amber,
                          fontWeight: FontWeight.w600,
                        ),
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

  Widget _legend() {
    Widget item(IconData icon, Color fg, Color bg, String label) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: fg),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 13,
              color: fg,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        item(
          Icons.star_rounded,
          Ks.green,
          Ks.greenSoft,
          tr('Learned', 'सीख लिया'),
        ),
        item(
          Icons.star_half_rounded,
          Ks.amber,
          Ks.amberSoft,
          tr('Working on', 'काम चल रहा है'),
        ),
        item(
          Icons.star_outline_rounded,
          Ks.accent,
          Ks.accentSoft,
          tr('Next', 'अगला'),
        ),
        item(
          Icons.star_border_rounded,
          Ks.muted,
          const Color(0xFFF1EEE7),
          tr('Later', 'बाद में'),
        ),
      ],
    );
  }
}
