import 'package:flutter/material.dart';

import '../api_admin.dart';
import '../theme.dart';
import '../l10n.dart';

/// Students of one class: roll number, first name and consent state; add one, paste many,
/// record parent consent.
class RosterScreen extends StatefulWidget {
  const RosterScreen({
    super.key,
    required this.classId,
    required this.className,
  });
  final int classId;
  final String className;
  @override
  State<RosterScreen> createState() => _RosterScreenState();
}

class _RosterScreenState extends State<RosterScreen> {
  late Future<List<Map<String, dynamic>>> _future;
  final _search = TextEditingController();
  String _q = '';
  final _busy = <int>{};

  @override
  void initState() {
    super.initState();
    _future = AdminApi.roster(widget.classId);
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    final f = AdminApi.roster(widget.classId);
    setState(() => _future = f);
    try {
      await f;
    } catch (_) {}
  }

  int _nextRoll(List<Map<String, dynamic>> list) {
    var m = 0;
    for (final c in list) {
      final r = (c['roll_no'] as num?)?.toInt() ?? 0;
      if (r > m) m = r;
    }
    return m + 1;
  }

  Future<void> _addOne(List<Map<String, dynamic>> list) async {
    await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) =>
          _AddStudentSheet(classId: widget.classId, nextRoll: _nextRoll(list)),
    );
    _reload(); // also after a dismissed paste that saved some names
  }

  Future<void> _addMany(List<Map<String, dynamic>> list) async {
    await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) =>
          _PasteManySheet(classId: widget.classId, nextRoll: _nextRoll(list)),
    );
    _reload(); // also after a dismissed paste that saved some names
  }

  Future<void> _recordConsent(Map<String, dynamic> c) async {
    final id = (c['id'] as num).toInt();
    final name = '${c['first_name']}';
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Record consent?', 'सहमति दर्ज करें?')),
        content: Text(
          tr(
            'Only record this if you have the parent\'s signed consent form for $name.',
            '$name के लिए माता-पिता का हस्ताक्षर वाला सहमति पत्र हो, तभी इसे दर्ज करें।',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(tr('Cancel', 'रद्द करें')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(tr('Yes, I have it', 'हाँ, मेरे पास है')),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy.add(id));
    try {
      await AdminApi.recordConsent(id, AdminApi.consentSource);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            tr('Consent recorded for $name', '$name की सहमति दर्ज हुई'),
          ),
        ),
      );
      await _reload();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyError(e))));
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          tr('Students · ${widget.className}', 'बच्चे · ${widget.className}'),
        ),
      ),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Loading();
          }
          if (snap.hasError) {
            return _ErrorView(error: snap.error!, onRetry: _reload);
          }
          final list = snap.data ?? [];
          final showSearch = list.length > 15;
          final q = _q.trim().toLowerCase();
          final shown = (!showSearch || q.isEmpty)
              ? list
              : list
                    .where(
                      (c) =>
                          '${c['first_name']}'.toLowerCase().contains(q) ||
                          '${c['roll_no']}' == q,
                    )
                    .toList();
          final consented = list.where((c) => c['consented'] == true).length;
          return RefreshIndicator(
            onRefresh: _reload,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () => _addOne(list),
                        icon: const Icon(Icons.person_add_alt_1_rounded),
                        label: Text(tr('Add student', 'बच्चा जोड़ें')),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () => _addMany(list),
                        icon: const Icon(Icons.playlist_add_rounded),
                        label: Text(tr('Paste many', 'कई जोड़ें')),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                if (list.isEmpty)
                  EmptyState(
                    icon: Icons.person_outline_rounded,
                    text: tr(
                      'No students yet. Add one, or paste the whole list.',
                      'अभी कोई बच्चा नहीं। एक जोड़ें, या पूरी सूची पेस्ट करें।',
                    ),
                  )
                else ...[
                  Text(
                    tr(
                      '${list.length} students · consent recorded for $consented',
                      '${list.length} बच्चे · $consented की सहमति दर्ज',
                    ),
                    style: const TextStyle(color: Ks.muted),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    tr(
                      'Consent can only be recorded here, not withdrawn. To remove a child\'s records, use Settings.',
                      'सहमति यहाँ सिर्फ़ दर्ज हो सकती है, वापस नहीं ली जा सकती। बच्चे का डेटा हटाने के लिए सेटिंग्स देखें।',
                    ),
                    style: const TextStyle(color: Ks.muted, fontSize: 13),
                  ),
                  const SizedBox(height: 12),
                  if (showSearch) ...[
                    TextField(
                      controller: _search,
                      onChanged: (v) => setState(() => _q = v),
                      decoration: InputDecoration(
                        prefixIcon: const Icon(Icons.search_rounded),
                        hintText: tr(
                          'Search name or roll no.',
                          'नाम या रोल नंबर खोजें',
                        ),
                        suffixIcon: _q.isEmpty
                            ? null
                            : IconButton(
                                icon: const Icon(Icons.close_rounded),
                                onPressed: () {
                                  _search.clear();
                                  setState(() => _q = '');
                                },
                              ),
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (shown.isEmpty)
                    Padding(
                      padding: const EdgeInsets.all(24),
                      child: Center(
                        child: Text(
                          tr('No student matches.', 'कोई बच्चा नहीं मिला।'),
                          style: const TextStyle(color: Ks.muted),
                        ),
                      ),
                    ),
                  for (final c in shown) ...[
                    _tile(c),
                    const SizedBox(height: 8),
                  ],
                ],
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _tile(Map<String, dynamic> c) {
    final id = (c['id'] as num).toInt();
    final ok = c['consented'] == true;
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: Ks.accentSoft,
          foregroundColor: Ks.accent,
          child: Text(
            '${c['roll_no']}',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        title: Text(
          '${c['first_name']}',
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(
            children: [
              Icon(
                ok ? Icons.check_circle_rounded : Icons.hourglass_empty_rounded,
                size: 16,
                color: ok ? Ks.green : Ks.amber,
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  ok
                      ? tr('Consent recorded', 'सहमति दर्ज')
                      : tr('Consent pending', 'सहमति बाकी'),
                  style: TextStyle(color: ok ? Ks.green : Ks.amber),
                ),
              ),
            ],
          ),
        ),
        trailing: ok
            ? null
            : _busy.contains(id)
            ? const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : TextButton(
                onPressed: () => _recordConsent(c),
                child: Text(tr('Record consent', 'सहमति दर्ज करें')),
              ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off_rounded, size: 48, color: Ks.muted),
          const SizedBox(height: 12),
          Text(
            friendlyError(error),
            textAlign: TextAlign.center,
            style: const TextStyle(color: Ks.muted, fontSize: 16),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(minimumSize: const Size(160, 48)),
            onPressed: onRetry,
            icon: const Icon(Icons.refresh_rounded),
            label: Text(tr('Retry', 'दोबारा कोशिश करें')),
          ),
        ],
      ),
    ),
  );
}

class _AddStudentSheet extends StatefulWidget {
  const _AddStudentSheet({required this.classId, required this.nextRoll});
  final int classId;
  final int nextRoll;
  @override
  State<_AddStudentSheet> createState() => _AddStudentSheetState();
}

class _AddStudentSheetState extends State<_AddStudentSheet> {
  final _name = TextEditingController();
  late final _roll = TextEditingController(text: '${widget.nextRoll}');
  bool _consent = false;
  bool _saving = false;
  String? _err;

  @override
  void dispose() {
    _name.dispose();
    _roll.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    final roll = int.tryParse(_roll.text.trim());
    if (name.isEmpty) {
      setState(
        () => _err = tr(
          'Type the child\'s first name',
          'बच्चे का पहला नाम लिखें',
        ),
      );
      return;
    }
    if (roll == null || roll < 1) {
      setState(
        () => _err = tr(
          'Roll number must be a number',
          'रोल नंबर एक संख्या होनी चाहिए',
        ),
      );
      return;
    }
    setState(() {
      _saving = true;
      _err = null;
    });
    try {
      await AdminApi.addChild(
        widget.classId,
        name.length > 60 ? name.substring(0, 60) : name,
        roll,
        consentSource: _consent ? AdminApi.consentSource : null,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _err = friendlyError(e);
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        20,
        0,
        20,
        20 + MediaQuery.of(context).viewInsets.bottom,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              tr('Add a student', 'बच्चा जोड़ें'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _name,
              autofocus: true,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: tr('First name', 'पहला नाम'),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _roll,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: tr('Roll number', 'रोल नंबर'),
              ),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _consent,
              onChanged: (v) => setState(() => _consent = v ?? false),
              title: Text(
                tr(
                  'Parent has signed the consent form',
                  'माता-पिता ने सहमति पत्र पर हस्ताक्षर किए हैं',
                ),
              ),
            ),
            if (_err != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_err!, style: const TextStyle(color: Ks.rose)),
              ),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: Text(
                _saving ? tr('Saving…', 'सहेज रहे हैं…') : tr('Add', 'जोड़ें'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PasteManySheet extends StatefulWidget {
  const _PasteManySheet({required this.classId, required this.nextRoll});
  final int classId;
  final int nextRoll;
  @override
  State<_PasteManySheet> createState() => _PasteManySheetState();
}

class _PasteManySheetState extends State<_PasteManySheet> {
  final _text = TextEditingController();
  late int _start = widget.nextRoll;
  bool _consent = false;
  bool _saving = false;
  int _done = 0;
  int _total = 0;
  bool _addedSome = false;
  String? _err;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  List<String> get _names => _text.text
      .split('\n')
      .map((l) => l.trim())
      .where((l) => l.isNotEmpty)
      .map((l) => l.length > 60 ? l.substring(0, 60) : l)
      .toList();

  Future<void> _save() async {
    final names = _names;
    if (names.isEmpty) return;
    setState(() {
      _saving = true;
      _done = 0;
      _total = names.length;
      _err = null;
    });
    var ok = 0;
    Object? failure;
    for (var i = 0; i < names.length; i++) {
      try {
        await AdminApi.addChild(
          widget.classId,
          names[i],
          _start + i,
          consentSource: _consent ? AdminApi.consentSource : null,
        );
        ok++;
        if (mounted) setState(() => _done = ok);
      } catch (e) {
        failure = e;
        break;
      }
    }
    if (!mounted) return;
    if (failure == null) {
      Navigator.pop(context, true);
      return;
    }
    final problem = friendlyError(failure);
    // Keep the lines that were not saved so a retry does not add anyone twice.
    final rest = names.sublist(ok);
    setState(() {
      _saving = false;
      _addedSome = _addedSome || ok > 0;
      _start += ok;
      _text.text = rest.join('\n');
      _err = tr(
        'Saved $ok of ${names.length}. $problem The remaining names are still in the box.',
        '${names.length} में से $ok सहेजे गए। $problem बाकी नाम बॉक्स में हैं।',
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final names = _names;
    return PopScope(
      canPop: !_saving,
      onPopInvokedWithResult: (didPop, _) {},
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          0,
          20,
          20 + MediaQuery.of(context).viewInsets.bottom,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                tr('Paste many students', 'कई बच्चे जोड़ें'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text(
                tr(
                  'One first name per line. Roll numbers continue from $_start.',
                  'हर लाइन में एक पहला नाम। रोल नंबर $_start से आगे चलेंगे।',
                ),
                style: const TextStyle(color: Ks.muted),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _text,
                enabled: !_saving,
                autofocus: true,
                minLines: 5,
                maxLines: 10,
                keyboardType: TextInputType.multiline,
                textCapitalization: TextCapitalization.words,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  hintText: tr('Asha\nRavi\nSita', 'आशा\nरवि\nसीता'),
                ),
              ),
              const SizedBox(height: 8),
              if (names.isNotEmpty)
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Ks.accentSoft,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    tr(
                      '${names.length} students will be added, roll $_start–${_start + names.length - 1}: ${names.take(3).join(', ')}${names.length > 3 ? '…' : ''}',
                      '${names.length} बच्चे जुड़ेंगे, रोल $_start–${_start + names.length - 1}: ${names.take(3).join(', ')}${names.length > 3 ? '…' : ''}',
                    ),
                    style: const TextStyle(
                      color: Ks.accent,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _consent,
                onChanged: _saving
                    ? null
                    : (v) => setState(() => _consent = v ?? false),
                title: Text(
                  tr(
                    'Parents of all of them have signed the consent form',
                    'इन सभी के माता-पिता ने सहमति पत्र पर हस्ताक्षर किए हैं',
                  ),
                ),
              ),
              if (_err != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_err!, style: const TextStyle(color: Ks.rose)),
                ),
              FilledButton(
                onPressed: (_saving || names.isEmpty) ? null : _save,
                child: Text(
                  _saving
                      ? tr(
                          'Saving $_done of $_total…',
                          '$_done / $_total सहेजे…',
                        )
                      : names.isEmpty
                      ? tr('Add students', 'बच्चे जोड़ें')
                      : tr(
                          'Add ${names.length} students',
                          '${names.length} बच्चे जोड़ें',
                        ),
                ),
              ),
              if (_addedSome && !_saving)
                TextButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: Text(tr('Close', 'बंद करें')),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
