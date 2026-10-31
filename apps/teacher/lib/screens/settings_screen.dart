import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api.dart';
import '../api_admin.dart';
import '../theme.dart';
import 'login_screen.dart';
import '../l10n.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  Map<String, dynamic>? _ai;
  Map<String, dynamic>? _content;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    Api.i
        .aiActivity()
        .then((v) {
          if (mounted) setState(() => _ai = (v as Map).cast<String, dynamic>());
        })
        .catchError((_) {});
    Api.i
        .contentStatus()
        .then((v) {
          if (mounted) {
            setState(() => _content = (v as Map).cast<String, dynamic>());
          }
        })
        .catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final me = Api.i.me;
    final caps = (me?['capabilities'] as Map?) ?? {};
    return Scaffold(
      appBar: AppBar(title: Text(tr('Settings', 'सेटिंग्स'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    me?['name'] ?? '',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    me?['school'] ?? '',
                    style: const TextStyle(color: Ks.muted),
                  ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    children: [
                      _cap('AI', caps['ai'] == true),
                      _cap(
                        tr('Voice recognition', 'आवाज़ पहचान'),
                        caps['asr'] == true,
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          const LanguageVoiceCard(),
          const SizedBox(height: 12),
          if (_ai != null) ...[_aiCard(_ai!), const SizedBox(height: 12)],
          if (_ai != null &&
              (_ai!['checks_7d'] != null || _ai!['plans_7d'] != null)) ...[
            _weekCard(_ai!),
            const SizedBox(height: 12),
          ],
          if (_content != null) ...[
            _contentCard(_content!),
            const SizedBox(height: 12),
          ],
          _dataCard(),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            onPressed: () async {
              await Api.i.logout();
              if (!context.mounted) return;
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(builder: (_) => const LoginScreen()),
                (_) => false,
              );
            },
            icon: const Icon(Icons.logout_rounded),
            label: Text(tr('Log out', 'लॉगआउट')),
          ),
        ],
      ),
    );
  }

  Widget _cap(String label, bool on) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: on ? Ks.greenSoft : Ks.roseSoft,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      '$label: ${on ? tr('On', 'चालू') : tr('Off (offline mode)', 'बंद (ऑफ़लाइन मोड)')}',
      style: TextStyle(fontSize: 13, color: on ? Ks.green : Ks.rose),
    ),
  );

  String _money(Object? v) => v is num ? v.toStringAsFixed(2) : '-';

  Widget _stat(String label, Object? v) => Container(
    constraints: const BoxConstraints(minWidth: 96),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
    decoration: BoxDecoration(
      color: Ks.accentSoft,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      children: [
        Text(
          '${v ?? '-'}',
          style: const TextStyle(
            fontSize: 22,
            fontWeight: FontWeight.w700,
            color: Ks.accent,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 13, color: Ks.muted),
        ),
      ],
    ),
  );

  Widget _aiCard(Map<String, dynamic> ai) {
    final today = ai['cost_inr_today'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              tr('AI suggestion ledger', 'AI सुझावों का हिसाब'),
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
            ),
            const SizedBox(height: 6),
            Text(
              tr(
                'The AI only proposes. Nothing reaches a child\'s record until you confirm it.',
                'AI सिर्फ़ सुझाव देता है। आपकी पुष्टि के बिना कुछ भी बच्चे के रिकॉर्ड में नहीं जाता।',
              ),
              style: const TextStyle(color: Ks.muted),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _stat(tr('Shown', 'दिखाए गए'), ai['proposals']),
                _stat(tr('Confirmed', 'पुष्टि की'), ai['confirmed']),
                _stat(tr('Rejected', 'रद्द किए'), ai['rejected']),
                _stat(tr('Edited', 'बदले गए'), ai['edited']),
                _stat(tr('Skipped', 'छोड़े गए'), ai['skipped']),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              tr(
                'Rejected includes the suggestions you skipped.',
                'रद्द में छोड़े गए सुझाव भी गिने जाते हैं।',
              ),
              style: const TextStyle(color: Ks.muted, fontSize: 13),
            ),
            const SizedBox(height: 10),
            _kv(
              tr('Offline / rule-based', 'ऑफ़लाइन/नियम से बने'),
              ai['degraded'],
            ),
            _kv(tr('AI calls', 'AI कॉल'), ai['ai_calls']),
            // Older servers only send the all-time figure: show it as the total, never as "today".
            if (today != null)
              _kv(tr('Spent today (₹)', 'आज खर्च (₹)'), _money(today)),
            _kv(tr('Total spent (₹)', 'कुल खर्च (₹)'), _money(ai['cost_inr'])),
            _kv(
              tr('Budget left (₹)', 'बचा बजट (₹)'),
              Api.i.me?['budget_left_inr'],
            ),
          ],
        ),
      ),
    );
  }

  Widget _weekCard(Map<String, dynamic> ai) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('This week', 'इस हफ़्ते'),
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
          ),
          const SizedBox(height: 4),
          Text(
            tr('Last 7 days', 'पिछले 7 दिन'),
            style: const TextStyle(color: Ks.muted),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _stat(tr('Checks recorded', 'जाँच दर्ज हुईं'), ai['checks_7d']),
              _stat(tr('Plans made', 'योजनाएँ बनीं'), ai['plans_7d']),
            ],
          ),
        ],
      ),
    ),
  );

  // ---- children's data tools

  void _snack(String m) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _info(String title, String body) => showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      icon: const Icon(Icons.check_circle_rounded, color: Ks.green, size: 36),
      title: Text(title),
      content: Text(body),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: Text(tr('OK', 'ठीक है')),
        ),
      ],
    ),
  );

  Widget _dataCard() => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.privacy_tip_outlined, color: Ks.muted),
              const SizedBox(width: 10),
              Text(
                tr('Children\'s data', 'बच्चों का डेटा'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            tr(
              'First name and roll number only. Photos are deleted after 7 days. Voice is not saved.',
              'सिर्फ़ पहला नाम और रोल नंबर। फ़ोटो 7 दिन में हटती हैं। आवाज़ सहेजी नहीं जाती।',
            ),
            style: const TextStyle(color: Ks.muted),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: _busy ? null : _exportChild,
            icon: const Icon(Icons.download_outlined),
            label: Text(
              tr('Download a child\'s data', 'बच्चे का डेटा डाउनलोड करें'),
            ),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: Ks.rose),
            onPressed: _busy ? null : _deleteChild,
            icon: const Icon(Icons.person_remove_outlined),
            label: Text(tr('Delete a child\'s data', 'बच्चे का डेटा हटाएँ')),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: Ks.rose),
            onPressed: _busy ? null : _deleteClass,
            icon: const Icon(Icons.delete_forever_outlined),
            label: Text(
              tr('Delete all class data', 'कक्षा का पूरा डेटा हटाएँ'),
            ),
          ),
        ],
      ),
    ),
  );

  /// The teacher's classes; with exactly one it is returned without asking.
  Future<Map<String, dynamic>?> _chooseClass() async {
    final List<Map<String, dynamic>> list;
    try {
      list = ((await Api.i.classes()) as List).cast<Map<String, dynamic>>();
    } catch (e) {
      _snack(friendlyError(e));
      return null;
    }
    if (list.isEmpty) {
      _snack(tr('No class yet', 'अभी कोई कक्षा नहीं'));
      return null;
    }
    if (list.length == 1 || !mounted) return list.first;
    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                tr('Choose a class', 'कक्षा चुनें'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            for (final c in list)
              ListTile(
                leading: const Icon(Icons.groups_rounded, color: Ks.accent),
                title: Text('${c['label']}'),
                onTap: () => Navigator.pop(ctx, c),
              ),
          ],
        ),
      ),
    );
  }

  /// Class, then child. Returns the roster entry.
  Future<Map<String, dynamic>?> _chooseChild() async {
    final cls = await _chooseClass();
    if (cls == null || !mounted) return null;
    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _ChildSheet(
        classId: (cls['id'] as num).toInt(),
        className: '${cls['label']}',
      ),
    );
  }

  Future<void> _exportChild() async {
    final child = await _chooseChild();
    if (child == null || !mounted) return;
    setState(() => _busy = true);
    try {
      final data = await AdminApi.exportChild((child['id'] as num).toInt());
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _ExportDialog(
          name: '${child['first_name']}',
          json: const JsonEncoder.withIndent('  ').convert(data),
        ),
      );
    } catch (e) {
      _snack(friendlyError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _deleteChild() async {
    final child = await _chooseChild();
    if (child == null || !mounted) return;
    final name = '${child['first_name']}';
    final yes = await showDialog<bool>(
      context: context,
      builder: (_) => _TypedConfirm(
        title: trf("Delete {name}'s data?", '{name} का डेटा हटाएँ?', {'name': name}),
        message: tr(
          'This permanently deletes all learning records and attendance of $name. $name stays on the class list. This cannot be undone.',
          '$name के सभी सीखने के रिकॉर्ड और उपस्थिति हमेशा के लिए हट जाएँगे। $name कक्षा की सूची में रहेगा/रहेगी। इसे वापस नहीं किया जा सकता।',
        ),
        expected: name,
        actionLabel: tr('Delete data', 'डेटा हटाएँ'),
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await AdminApi.deleteChildData((child['id'] as num).toInt());
      if (!mounted) return;
      await _info(
        tr('Data deleted', 'डेटा हट गया'),
        tr(
          'The learning records and attendance of $name have been deleted.',
          '$name के सीखने के रिकॉर्ड और उपस्थिति हटा दिए गए हैं।',
        ),
      );
    } catch (e) {
      _snack(friendlyError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _deleteClass() async {
    final cls = await _chooseClass();
    if (cls == null || !mounted) return;
    final label = '${cls['label']}';
    final yes = await showDialog<bool>(
      context: context,
      builder: (_) => _TypedConfirm(
        title: trf('Delete all data of {label}?', '{label} का पूरा डेटा हटाएँ?', {'label': label}),
        message: tr(
          'This permanently deletes every child\'s learning records, the attendance, saved checks and plans of this class. The class and its student list stay. This cannot be undone.',
          'इस कक्षा के हर बच्चे के सीखने के रिकॉर्ड, उपस्थिति, सहेजी गई जाँचें और योजनाएँ हमेशा के लिए हट जाएँगी। कक्षा और बच्चों की सूची रहेगी। इसे वापस नहीं किया जा सकता।',
        ),
        expected: label,
        actionLabel: tr('Delete all data', 'पूरा डेटा हटाएँ'),
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await AdminApi.deleteClassData((cls['id'] as num).toInt());
      if (!mounted) return;
      await _info(
        tr('Data deleted', 'डेटा हट गया'),
        tr(
          'All learning records, attendance, saved checks and plans of $label have been deleted.',
          '$label के सभी सीखने के रिकॉर्ड, उपस्थिति, सहेजी गई जाँचें और योजनाएँ हटा दी गई हैं।',
        ),
      );
    } catch (e) {
      _snack(friendlyError(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _contentCard(Map<String, dynamic> c) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('Content', 'सामग्री'),
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
          ),
          const SizedBox(height: 8),
          _kv(tr('Checkpoints', 'जाँच बिंदु (checkpoints)'), c['checkpoints']),
          _kv(
            tr('Activities (reviewed)', 'गतिविधियाँ (जाँची गईं)'),
            '${c['activities_reviewed']} / ${c['activities']}',
          ),
          _kv(
            tr('Home practice questions', 'घर के अभ्यास प्रश्न'),
            c['practice_items'],
          ),
          _kv(tr('Ready check questions', 'तैयार जाँच प्रश्न'), c['probes']),
        ],
      ),
    ),
  );

  Widget _kv(String k, Object? v) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      children: [
        Expanded(
          child: Text(k, style: const TextStyle(color: Ks.muted)),
        ),
        Text(
          '${v ?? '-'}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ],
    ),
  );
}

/// Picks a child of one class (search box when the class is large).
class _ChildSheet extends StatefulWidget {
  const _ChildSheet({required this.classId, required this.className});
  final int classId;
  final String className;
  @override
  State<_ChildSheet> createState() => _ChildSheetState();
}

class _ChildSheetState extends State<_ChildSheet> {
  late Future<List<Map<String, dynamic>>> _future = AdminApi.roster(
    widget.classId,
  );
  String _q = '';

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: MediaQuery.of(context).size.height * 0.7,
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                tr(
                  'Choose a child · ${widget.className}',
                  'बच्चा चुनें · ${widget.className}',
                ),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: TextField(
                onChanged: (v) => setState(() => _q = v.trim().toLowerCase()),
                decoration: InputDecoration(
                  prefixIcon: const Icon(Icons.search_rounded),
                  hintText: tr(
                    'Search name or roll no.',
                    'नाम या रोल नंबर खोजें',
                  ),
                ),
              ),
            ),
            Expanded(
              child: FutureBuilder<List<Map<String, dynamic>>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const Loading();
                  }
                  if (snap.hasError) {
                    return Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(friendlyError(snap.error!)),
                          TextButton(
                            onPressed: () => setState(
                              () => _future = AdminApi.roster(widget.classId),
                            ),
                            child: Text(tr('Retry', 'दोबारा कोशिश करें')),
                          ),
                        ],
                      ),
                    );
                  }
                  final all = snap.data ?? [];
                  final list = _q.isEmpty
                      ? all
                      : all
                            .where(
                              (c) =>
                                  '${c['first_name']}'.toLowerCase().contains(
                                    _q,
                                  ) ||
                                  '${c['roll_no']}' == _q,
                            )
                            .toList();
                  if (list.isEmpty) {
                    return EmptyState(
                      icon: Icons.person_outline_rounded,
                      text: all.isEmpty
                          ? tr(
                              'No students in this class yet.',
                              'इस कक्षा में अभी कोई बच्चा नहीं।',
                            )
                          : tr('No student matches.', 'कोई बच्चा नहीं मिला।'),
                    );
                  }
                  return ListView(
                    children: [
                      for (final c in list)
                        ListTile(
                          leading: CircleAvatar(
                            backgroundColor: Ks.accentSoft,
                            foregroundColor: Ks.accent,
                            child: Text('${c['roll_no']}'),
                          ),
                          title: Text('${c['first_name']}'),
                          onTap: () => Navigator.pop(context, c),
                        ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The child's export as readable JSON, with a Copy button (no file-saving package in the app).
class _ExportDialog extends StatefulWidget {
  const _ExportDialog({required this.name, required this.json});
  final String name;
  final String json;
  @override
  State<_ExportDialog> createState() => _ExportDialogState();
}

class _ExportDialogState extends State<_ExportDialog> {
  bool _copied = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(trf('Data of {name}', '{name} का डेटा', {'name': widget.name})),
      content: SizedBox(
        width: double.maxFinite,
        height: MediaQuery.of(context).size.height * 0.5,
        child: SingleChildScrollView(
          child: SelectableText(
            widget.json,
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 12.5,
              height: 1.4,
            ),
          ),
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: widget.json));
            if (mounted) setState(() => _copied = true);
          },
          icon: Icon(_copied ? Icons.check_rounded : Icons.copy_rounded),
          label: Text(
            _copied ? tr('Copied', 'कॉपी हो गया') : tr('Copy', 'कॉपी करें'),
          ),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(tr('Close', 'बंद करें')),
        ),
      ],
    );
  }
}

/// Destructive confirmation: the action unlocks only when [expected] is typed.
class _TypedConfirm extends StatefulWidget {
  const _TypedConfirm({
    required this.title,
    required this.message,
    required this.expected,
    required this.actionLabel,
  });
  final String title;
  final String message;
  final String expected;
  final String actionLabel;
  @override
  State<_TypedConfirm> createState() => _TypedConfirmState();
}

class _TypedConfirmState extends State<_TypedConfirm> {
  final _c = TextEditingController();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  bool get _match =>
      _c.text.trim().toLowerCase() == widget.expected.trim().toLowerCase();

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.message),
            const SizedBox(height: 14),
            Text(
              tr(
                'Type "${widget.expected}" to confirm',
                'पुष्टि के लिए "${widget.expected}" लिखें',
              ),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _c,
              autofocus: true,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(hintText: widget.expected),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: Text(tr('Cancel', 'रद्द करें')),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            minimumSize: const Size(0, 44),
            backgroundColor: Ks.rose,
          ),
          onPressed: _match ? () => Navigator.pop(context, true) : null,
          child: Text(widget.actionLabel),
        ),
      ],
    );
  }
}

/// "Language and voice": voice service, app language and learning language. Each change is
/// applied at once and saved for this user (on the server and on the phone).
class LanguageVoiceCard extends StatefulWidget {
  const LanguageVoiceCard({super.key});
  @override
  State<LanguageVoiceCard> createState() => _LanguageVoiceCardState();
}

typedef _Choice = ({
  String code,
  String title,
  String? subtitle,
  bool beta,
  bool enabled,
});

class _LanguageVoiceCardState extends State<LanguageVoiceCard> {
  Map<String, dynamic>? _langs; // GET /v1/languages
  String? _saving; // the field being saved

  @override
  void initState() {
    super.initState();
    Api.i
        .languages()
        .then((v) {
          if (mounted) setState(() => _langs = v);
        })
        .catchError((_) {});
  }

  List<Map<String, dynamic>> _list(String key) =>
      ((_langs?[key] as List?) ?? const [])
          .whereType<Map>()
          .map((m) => m.cast<String, dynamic>())
          .toList();

  /// Voice services from the server; before it answers, both are listed and the server decides.
  List<Map<String, dynamic>> get _providers {
    final l = _list('providers');
    if (l.isNotEmpty) return l;
    return const [
      {'key': 'sarvam', 'name': 'Sarvam', 'default': true},
      {'key': 'gnani', 'name': 'Gnani', 'default': false},
    ];
  }

  /// Learning languages the server can teach in; Hindi and English when it can't be reached.
  List<Map<String, dynamic>> get _contentLangs {
    final l = _list('content_languages');
    if (l.isNotEmpty) return l;
    return const [
      {'code': 'hi'},
      {'code': 'en'},
    ];
  }

  static AppLanguage? _app(String code) {
    for (final l in appLanguages()) {
      if (l.code == code) return l;
    }
    return null;
  }

  /// `मराठी · Marathi` for a language code (native name first).
  String _langName(String code, [Map<String, dynamic>? m]) {
    final a = _app(code);
    final native = (m?['name_native'] ?? a?.nativeName ?? code).toString();
    final en = (m?['name_en'] ?? a?.englishName ?? '').toString();
    return en.isEmpty || en == native ? native : '$native · $en';
  }

  String _providerName(Map<String, dynamic> p) {
    final name = (p['name'] ?? p['key']).toString();
    return p['default'] == true
        ? '$name${tr(': recommended', ': सुझाया गया')}'
        : name;
  }

  Future<void> _save(String field, String value) async {
    setState(() => _saving = field);
    try {
      final onServer = await Api.i.setPref(field, value);
      if (!onServer) {
        _snack(
          tr(
            'Saved on this phone. It will be saved to your account when the internet is back.',
            'इस फ़ोन पर सहेजा गया। इंटरनेट आने पर आपके खाते में भी सहेजा जाएगा।',
          ),
        );
      }
    } on ApiError catch (e) {
      _snack(e.message);
    } catch (e) {
      _snack(e.toString());
    } finally {
      if (mounted) setState(() => _saving = null);
    }
  }

  void _snack(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _pickProvider() async {
    final cur = '${Api.i.prefs?['voice_provider'] ?? 'sarvam'}';
    final picked = await _pick(
      title: tr('Voice service', 'आवाज़ सेवा'),
      selected: cur,
      searchable: false,
      items: [
        for (final p in _providers)
          (
            code: '${p['key']}',
            title: _providerName(p),
            subtitle: p['configured'] == false
                ? tr('Not set up yet', 'अभी सेट नहीं है')
                : null,
            beta: false,
            enabled: p['configured'] != false,
          ),
      ],
    );
    if (picked != null && picked != cur) await _save('voice_provider', picked);
  }

  Future<void> _pickAppLang() async {
    final cur = Lang.code.value;
    final picked = await _pick(
      title: tr('App language', 'ऐप की भाषा'),
      selected: cur,
      searchable: true,
      items: [
        for (final l in appLanguages())
          (
            code: l.code,
            title: l.nativeName,
            subtitle: l.englishName == l.nativeName ? null : l.englishName,
            beta: l.beta,
            enabled: true,
          ),
      ],
    );
    if (picked != null && picked != cur) await _save('app_lang', picked);
  }

  Future<void> _pickContentLang() async {
    final cur = ContentLang.code.value;
    final picked = await _pick(
      title: tr('Learning language', 'सीखने की भाषा'),
      selected: cur,
      searchable: _contentLangs.length > 6,
      items: [
        for (final m in _contentLangs)
          (
            code: '${m['code']}',
            title:
                (m['name_native'] ??
                        _app('${m['code']}')?.nativeName ??
                        m['code'])
                    .toString(),
            subtitle: (m['name_en'] ?? _app('${m['code']}')?.englishName)
                ?.toString(),
            beta: false,
            enabled: true,
          ),
      ],
    );
    if (picked != null && picked != cur) await _save('content_lang', picked);
  }

  /// A bottom sheet list (with a search box for long lists); returns the chosen code.
  Future<String?> _pick({
    required String title,
    required String selected,
    required bool searchable,
    required List<_Choice> items,
  }) {
    var query = '';
    return showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) {
          final q = query.trim().toLowerCase();
          final shown = q.isEmpty
              ? items
              : items
                    .where(
                      (c) =>
                          c.code.toLowerCase().contains(q) ||
                          c.title.toLowerCase().contains(q) ||
                          (c.subtitle ?? '').toLowerCase().contains(q),
                    )
                    .toList();
          return SafeArea(
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.of(ctx).size.height * 0.8,
              ),
              child: Padding(
                padding: EdgeInsets.only(
                  bottom: MediaQuery.of(ctx).viewInsets.bottom,
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                      child: Text(
                        title,
                        style: Theme.of(ctx).textTheme.titleMedium,
                      ),
                    ),
                    if (searchable)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                        child: TextField(
                          decoration: InputDecoration(
                            prefixIcon: const Icon(Icons.search_rounded),
                            hintText: tr('Search languages', 'भाषा खोजें'),
                          ),
                          onChanged: (v) => setSheet(() => query = v),
                        ),
                      ),
                    Flexible(
                      child: ListView(
                        shrinkWrap: true,
                        children: [
                          for (final c in shown)
                            ListTile(
                              enabled: c.enabled,
                              title: Row(
                                children: [
                                  Flexible(child: Text(c.title)),
                                  if (c.beta) ...[
                                    const SizedBox(width: 8),
                                    _betaTag(),
                                  ],
                                ],
                              ),
                              subtitle: c.subtitle == null
                                  ? null
                                  : Text(c.subtitle!),
                              trailing: c.code == selected
                                  ? const Icon(
                                      Icons.check_rounded,
                                      color: Ks.accent,
                                    )
                                  : null,
                              onTap: () => Navigator.of(ctx).pop(c.code),
                            ),
                          if (shown.isEmpty)
                            Padding(
                              padding: const EdgeInsets.all(20),
                              child: Text(
                                tr('No language matches', 'कोई भाषा नहीं मिली'),
                                style: const TextStyle(color: Ks.muted),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _betaTag() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      color: Ks.amberSoft,
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      tr('beta', 'बीटा'),
      style: const TextStyle(fontSize: 12, color: Ks.amber),
    ),
  );

  Widget _row({
    required IconData icon,
    required String label,
    required String value,
    required String field,
    required VoidCallback onTap,
  }) => ListTile(
    contentPadding: EdgeInsets.zero,
    leading: Icon(icon, color: Ks.accent),
    title: Text(label),
    subtitle: Text(value),
    trailing: _saving == field
        ? const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          )
        : const Icon(Icons.chevron_right_rounded),
    onTap: _saving == null ? onTap : null,
  );

  @override
  Widget build(BuildContext context) {
    final providerKey = '${Api.i.prefs?['voice_provider'] ?? 'sarvam'}';
    final provider = _providers.firstWhere(
      (p) => p['key'] == providerKey,
      orElse: () => {'key': providerKey, 'name': providerKey},
    );
    final appLang = _app(Lang.code.value);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: ValueListenableBuilder<String>(
          valueListenable: ContentLang.code,
          builder: (_, content, _) {
            Map<String, dynamic>? contentMeta;
            for (final m in _contentLangs) {
              if (m['code'] == content) contentMeta = m;
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tr('Language and voice', 'भाषा और आवाज़'),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  tr(
                    'App language = buttons and menus. Learning language = what children read, hear and speak.',
                    'ऐप की भाषा = बटन और मेनू। सीखने की भाषा = बच्चे जो पढ़ते, सुनते और बोलते हैं।',
                  ),
                  style: const TextStyle(color: Ks.muted),
                ),
                const SizedBox(height: 4),
                _row(
                  icon: Icons.record_voice_over_rounded,
                  label: tr('Voice service', 'आवाज़ सेवा'),
                  value: _providerName(provider),
                  field: 'voice_provider',
                  onTap: _pickProvider,
                ),
                _row(
                  icon: Icons.translate_rounded,
                  label: tr('App language', 'ऐप की भाषा'),
                  value: appLang == null
                      ? Lang.code.value
                      : _langName(appLang.code),
                  field: 'app_lang',
                  onTap: _pickAppLang,
                ),
                _row(
                  icon: Icons.menu_book_rounded,
                  label: tr('Learning language', 'सीखने की भाषा'),
                  value: _langName(content, contentMeta),
                  field: 'content_lang',
                  onTap: _pickContentLang,
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
