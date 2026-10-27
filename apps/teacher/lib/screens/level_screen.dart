import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../tts.dart';
import '../l10n.dart';

/// One child's learning map: status per checkpoint, evidence timeline, misconception hints,
/// probe suggestion, and a one-tap 3-item probe.
class LevelScreen extends StatefulWidget {
  const LevelScreen({
    super.key,
    required this.childId,
    required this.childName,
    required this.classId,
    required this.subject,
  });
  final int childId;
  final String childName;
  final int classId;
  final String subject;
  @override
  State<LevelScreen> createState() => _LevelScreenState();
}

class _LevelScreenState extends State<LevelScreen> {
  Map<String, dynamic>? _profile;
  List<dynamic> _history = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final p = await Api.i.profile(
        widget.childId,
        widget.subject,
      ) as Map<String, dynamic>;
      List<dynamic> h = const [];
      try {
        h = await Api.i.history(
          widget.childId,
          subject: widget.subject,
        ) as List;
      } catch (_) {}
      setState(() {
        _profile = p;
        _history = h;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _probe(Map<String, dynamic> item) async {
    final cp = item['checkpoint_id'] as String;
    dynamic probe;
    try {
      probe = await Api.i.probe(cp);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr('Could not load questions: $e', 'प्रश्न नहीं मिले: $e'),
          ),
        ),
      );
      return;
    }
    final p = probe['probe'] as Map<String, dynamic>?;
    final items = (p?['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    if (!mounted) return;
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Ks.paper,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSt) {
          var passed = 0;
          return Padding(
            padding: EdgeInsets.fromLTRB(
              20,
              16,
              20,
              20 + MediaQuery.of(ctx).viewInsets.bottom,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  p?['title_hi'] ?? tr('Check', 'जाँच'),
                  style: Theme.of(ctx).textTheme.titleLarge,
                ),
                const SizedBox(height: 6),
                Text(
                  tr(
                    'Ask ${widget.childName}:',
                    '${widget.childName} से पूछें:',
                  ),
                  style: const TextStyle(color: Ks.muted),
                ),
                const SizedBox(height: 12),
                for (final it in items)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            it['ask_hi'],
                            style: const TextStyle(fontSize: 17),
                          ),
                        ),
                        IconButton(
                          tooltip: tr('Listen', 'सुनें'),
                          icon: const Icon(
                            Icons.volume_up_rounded,
                            color: Ks.accent,
                          ),
                          onPressed: () => Speak.say(it['ask_hi']),
                        ),
                      ],
                    ),
                  ),
                if (items.isEmpty)
                  Text(
                    tr(
                      'No ready-made question for this lesson — check directly with taps.',
                      'इस सबक का तैयार प्रश्न नहीं — सीधे टैप में जाँचें।',
                    ),
                  ),
                if ((p?['tell_hi'] as String?)?.isNotEmpty == true)
                  Padding(
                    padding: const EdgeInsets.only(top: 4, bottom: 10),
                    child: Text(
                      p!['tell_hi'],
                      style: const TextStyle(color: Ks.muted),
                    ),
                  ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => setSt(() => passed = 0),
                        child: Text(tr('Not correct', 'सही नहीं')),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: FilledButton(
                        onPressed: () => setSt(() => passed = items.length),
                        child: Text(tr('All correct', 'सब सही')),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                FilledButton.icon(
                  onPressed: items.isEmpty
                      ? null
                      : () async {
                          await Api.i.postJson(
                            '/v1/classes/${widget.classId}/captures/probe?child_id=${widget.childId}&checkpoint_id=$cp&passed=$passed&total=${items.length}',
                            {},
                          );
                          if (ctx.mounted) Navigator.of(ctx).pop();
                          _load();
                        },
                  icon: const Icon(Icons.save_rounded),
                  label: Text(
                    tr(
                      'Save check ($passed/${items.length})',
                      'जाँच दर्ज करें ($passed/${items.length})',
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.childName),
        actions: [
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: _load),
        ],
      ),
      body: _loading
          ? const Loading()
          : _error != null
          ? EmptyState(icon: Icons.error_outline, text: _error!)
          : _body(),
    );
  }

  Widget _body() {
    final p = _profile!;
    final items = (p['items'] as List).cast<Map<String, dynamic>>();
    final needs =
        items
            .where(
              (i) =>
                  i['status'] == 'needs_intervention' ||
                  i['status'] == 'needs_practice',
            )
            .toList()
          ..sort(
            (a, b) => (a['status'] == 'needs_intervention' ? 0 : 1).compareTo(
              b['status'] == 'needs_intervention' ? 0 : 1,
            ),
          );
    final assessed = items.where((i) => i['status'] != 'not_started').length;
    final chapters = <String, List<Map<String, dynamic>>>{};
    for (final i in items) {
      (chapters[i['chapter'] as String? ?? tr('Other', 'अन्य')] ??= []).add(i);
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        Row(
          children: [
            CircleAvatar(
              radius: 26,
              backgroundColor: Ks.accentSoft,
              child: Text(
                '${p['child']['roll_no']}',
                style: const TextStyle(
                  color: Ks.accent,
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tr(
                      '$assessed / ${items.length} lessons assessed',
                      '$assessed / ${items.length} सबक जाँचे गए',
                    ),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    widget.subject == 'numeracy'
                        ? tr('Maths', 'गणित')
                        : tr('Hindi', 'हिंदी'),
                    style: const TextStyle(color: Ks.muted),
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        if (needs.isNotEmpty) ...[
          SectionTitle(tr('Needs attention now', 'अभी ध्यान दें')),
          ...needs.take(4).map((i) => _focusCard(i)),
        ] else
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                tr(
                  'No major gap visible yet. Start from the board with children whose checks are pending.',
                  'अभी कोई बड़ी चूक नहीं दिख रही। ऊपर बोर्ड से जाँच बाकी बच्चों से शुरू करें।',
                ),
              ),
            ),
          ),
        SectionTitle(tr('Full map', 'पूरा नक्शा')),
        for (final ch in chapters.entries) ...[
          Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 6),
            child: Text(
              ch.key,
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 15,
                color: Ks.muted,
              ),
            ),
          ),
          for (final i in ch.value) _row(i),
        ],
        if (_history.isNotEmpty) ...[
          SectionTitle(tr('Recent evidence', 'हाल के सबूत')),
          for (final h in _history.take(12))
            _historyRow(h as Map<String, dynamic>),
        ],
      ],
    );
  }

  Widget _focusCard(Map<String, dynamic> i) {
    final misc = i['misconception_top'] as String?;
    final improving = i['improving'] == true;
    final lowConf = (i['confidence'] as num? ?? 0) < 0.5;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    cpTitle(i),
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (improving)
                  Padding(
                    padding: EdgeInsets.only(right: 6),
                    child: Tooltip(
                      message: tr('Improving', 'सुधर रहा है'),
                      child: Icon(
                        Icons.trending_up_rounded,
                        color: Ks.green,
                        size: 20,
                      ),
                    ),
                  ),
                StatusChip(i['status'], compact: true),
              ],
            ),
            if (misc != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  tr(
                    'Likely gap: ${_miscHi(misc)}',
                    'संभावित चूक: ${_miscHi(misc)}',
                  ),
                  style: const TextStyle(color: Ks.rose, fontSize: 14),
                ),
              ),
            if (lowConf)
              Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text(
                  tr(
                    'Little evidence — check with taps',
                    'सबूत कम — टैप से जाँचें',
                  ),
                  style: TextStyle(color: Ks.muted, fontSize: 13),
                ),
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => _probe(i),
              icon: const Icon(Icons.quiz_rounded, size: 18),
              label: Text(
                tr(
                  'Check in 2 minutes (with questions)',
                  '2 मिनट में जाँचें (प्रश्न सहित)',
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _row(Map<String, dynamic> i) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      children: [
        Expanded(child: Text(cpTitle(i), style: const TextStyle(fontSize: 15))),
        const SizedBox(width: 8),
        StatusChip(i['status'], compact: true),
      ],
    ),
  );

  Widget _historyRow(Map<String, dynamic> h) {
    final result = h['result'] as String? ?? '';
    final icon = result == 'correct'
        ? Icons.check_rounded
        : (result == 'partial' ? Icons.remove_rounded : Icons.close_rounded);
    final color = result == 'correct'
        ? Ks.green
        : (result == 'partial' ? Ks.amber : Ks.rose);
    final at = DateTime.tryParse(h['at'] as String? ?? '')?.toLocal();
    final when = at == null ? '' : '${at.day}/${at.month}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              _shortCp(h['checkpoint_id'] as String? ?? ''),
              style: const TextStyle(fontSize: 14),
            ),
          ),
          Text(
            '${_srcHi(h['source'] as String? ?? '')} · $when',
            style: const TextStyle(color: Ks.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  String _shortCp(String id) => id.split('.').last.replaceAll('_', ' ');
  String _srcHi(String s) =>
      {
        'teacher_tap': tr('Tap', 'टैप'),
        'photo_work': tr('Photo', 'फ़ोटो'),
        'class_voice': tr('Voice', 'आवाज़'),
        'teacher_note': tr('Spoken', 'बोलकर'),
        'guided_probe': tr('Check', 'जाँच'),
        'home_voice': tr('Home', 'घर'),
        'home_tap': tr('Home', 'घर'),
      }[s] ??
      s;
  String _miscHi(String m) =>
      {
        'smaller_minus_larger': tr(
          'Subtracts the smaller from the larger',
          'छोटे में से बड़ा घटा रहा है',
        ),
        'borrow_from_wrong_column': tr(
          'Borrows from the wrong place',
          'उधार गलत जगह से',
        ),
        'ignores_zero_borrow': tr(
          'Doesn\'t understand borrowing across zero',
          'शून्य वाला उधार नहीं समझा',
        ),
        'forgets_carry': tr('Forgets to carry', 'हासिल भूल रहा है'),
        'confuses_sa_sha': tr('Confuses स and श', 'स और श में फर्क नहीं'),
        'confuses_i_ii_matra': tr(
          'Confuses the इ and ई matras',
          'इ और ई की मात्रा में फर्क नहीं',
        ),
        'ignores_matra': tr('Drops the matra', 'मात्रा छोड़ देता है'),
        'reads_letters_separately': tr(
          'Reads letters one by one',
          'अक्षर अलग-अलग पढ़ता है',
        ),
        'treats_digits_as_separate': tr(
          'Treats digits separately',
          'अंकों को अलग-अलग समझता है',
        ),
      }[m] ??
      m;
}
