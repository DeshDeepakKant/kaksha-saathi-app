import 'package:flutter/material.dart';

import '../api.dart';
import '../api_admin.dart';
import '../theme.dart';
import '../l10n.dart';
import 'level_check_screen.dart';

/// Students of one class: roll number, first name and consent state; add one, paste many,
/// record parent consent, edit / move / remove a student and restore a removed one.
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
  // Removed (inactive) students; empty when there are none or the server is older.
  List<Map<String, dynamic>> _inactive = const [];

  @override
  void initState() {
    super.initState();
    _future = AdminApi.roster(widget.classId);
    _loadInactive();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    final f = AdminApi.roster(widget.classId);
    setState(() {
      _future = f;
    });
    _loadInactive();
    try {
      await f;
    } catch (_) {}
  }

  /// Separate from the roster so an older server (404) or a failure never breaks the list.
  Future<void> _loadInactive() async {
    var list = <Map<String, dynamic>>[];
    try {
      final r = await Api.i.get(
        '/v1/classes/${widget.classId}/children/inactive',
      );
      if (r is List) {
        list = r
            .whereType<Map>()
            .map((m) => m.cast<String, dynamic>())
            .toList();
      }
    } catch (_) {}
    if (mounted) setState(() => _inactive = list);
  }

  void _toast(String text, {SnackBarAction? action}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(text), action: action));
  }

  Future<void> _levelCheck() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            LevelCheckScreen(classId: widget.classId, subject: 'numeracy'),
      ),
    );
    if (mounted) _reload();
  }

  Future<void> _edit(Map<String, dynamic> c) async {
    final name = '${c['first_name']}';
    final r = await showModalBottomSheet<_EditResult>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _EditStudentSheet(
        child: c,
        classId: widget.classId,
        className: widget.className,
      ),
    );
    if (r == null || !mounted) return;
    _reload();
    if (r.removed) {
      final id = (c['id'] as num).toInt();
      _toast(
        trf('Removed {name} from the class', '{name} को कक्षा से हटाया', {'name': name}),
        action: SnackBarAction(
          label: tr('Restore', 'वापस लाएँ'),
          onPressed: () => _restore({...c, 'id': id}),
        ),
      );
    } else if (r.movedTo != null) {
      _toast(
        trf(
          'Moved {name} to {movedTo}',
          '{name} को {movedTo} में भेजा', {'name': r.name, 'movedTo': r.movedTo},
        ),
      );
    } else {
      _toast(tr('Saved', 'सहेज लिया'));
    }
  }

  /// Brings a removed student back. A roll clash (409) asks for a new roll number once.
  Future<void> _restore(Map<String, dynamic> c) async {
    final id = (c['id'] as num).toInt();
    final name = '${c['first_name']}';
    if (_busy.contains(id)) return;
    setState(() => _busy.add(id));
    try {
      final body = <String, dynamic>{'active': true};
      while (true) {
        try {
          await Api.i.postJson('/v1/children/$id/edit', body);
          break;
        } on ApiError catch (e) {
          if (e.status != 409 || !mounted) rethrow;
          final roll = await _askRoll(
            name,
            (body['roll_no'] as int?) ?? (c['roll_no'] as num?)?.toInt(),
          );
          if (roll == null) return;
          body['roll_no'] = roll;
        }
      }
      if (!mounted) return;
      _toast(trf('Restored {name}', '{name} वापस आ गया', {'name': name}));
      _reload();
    } catch (e) {
      if (mounted) _toast(_errText(e));
    } finally {
      if (mounted) setState(() => _busy.remove(id));
    }
  }

  Future<int?> _askRoll(String name, int? taken) async {
    final list = await _future.catchError((_) => <Map<String, dynamic>>[]);
    if (!mounted) return null;
    final ctrl = TextEditingController(text: '${_nextRoll(list)}');
    String? err;
    final roll = await showDialog<int>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSt) => AlertDialog(
          title: Text(tr('Roll number taken', 'रोल नंबर पहले से है')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                taken == null
                    ? trf(
                        'That roll number is now used by another student. Restore {name} with a new roll number:',
                        'वह रोल नंबर अब किसी और बच्चे का है। {name} को नए रोल नंबर के साथ वापस लाएँ:', {'name': name},
                      )
                    : trf(
                        'Roll {taken} is now used by another student. Restore {name} with a new roll number:',
                        'रोल {taken} अब किसी और बच्चे का है। {name} को नए रोल नंबर के साथ वापस लाएँ:', {'taken': taken, 'name': name},
                      ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: ctrl,
                autofocus: true,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: tr('Roll number', 'रोल नंबर'),
                  errorText: err,
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: Text(tr('Cancel', 'रद्द करें')),
            ),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: () {
                final n = int.tryParse(ctrl.text.trim());
                if (n == null || n < 1) {
                  setSt(
                    () => err = tr(
                      'Roll number must be a number',
                      'रोल नंबर एक संख्या होनी चाहिए',
                    ),
                  );
                  return;
                }
                Navigator.pop(ctx, n);
              },
              child: Text(tr('Restore', 'वापस लाएँ')),
            ),
          ],
        ),
      ),
    );
    ctrl.dispose();
    return roll;
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
          trf(
            'Only record this if you have the parent\'s signed consent form for {name}.',
            '{name} के लिए माता-पिता का हस्ताक्षर वाला सहमति पत्र हो, तभी इसे दर्ज करें।', {'name': name},
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
            trf('Consent recorded for {name}', '{name} की सहमति दर्ज हुई', {'name': name}),
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
          trf('Students · {className}', 'बच्चे · {className}', {'className': widget.className}),
        ),
        actions: [
          TextButton.icon(
            style: TextButton.styleFrom(minimumSize: const Size(0, 48)),
            onPressed: _levelCheck,
            icon: const Icon(Icons.stairs_rounded),
            label: Text(tr('Level check', 'स्तर जाँच')),
          ),
          const SizedBox(width: 4),
        ],
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
                    trf(
                      '{listCount} students · consent recorded for {consented}',
                      '{listCount} बच्चे · {consented} की सहमति दर्ज', {'listCount': list.length, 'consented': consented},
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
                  const SizedBox(height: 4),
                  Text(
                    tr(
                      'Tap a student to edit, move or remove.',
                      'बदलने, दूसरी कक्षा में भेजने या हटाने के लिए बच्चे पर टैप करें।',
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
                if (_inactive.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _removedCard(),
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
        minVerticalPadding: 10,
        onTap: () => _edit(c),
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
            ? const Icon(Icons.edit_rounded, color: Ks.muted)
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

  /// "Removed students (N)", collapsed; each row can be restored.
  Widget _removedCard() => Card(
    clipBehavior: Clip.antiAlias,
    child: ExpansionTile(
      leading: const Icon(Icons.person_off_rounded, color: Ks.muted),
      title: Text(
        trf(
          'Removed students ({inactiveCount})',
          'हटाए गए बच्चे ({inactiveCount})', {'inactiveCount': _inactive.length},
        ),
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
      subtitle: Text(
        tr('Their records are kept.', 'इनका रिकॉर्ड रखा हुआ है।'),
        style: const TextStyle(color: Ks.muted, fontSize: 13),
      ),
      children: [
        for (final c in _inactive) _removedRow(c),
        const SizedBox(height: 6),
      ],
    ),
  );

  Widget _removedRow(Map<String, dynamic> c) {
    final id = (c['id'] as num).toInt();
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: Ks.line,
        foregroundColor: Ks.muted,
        child: Text(
          '${c['roll_no'] ?? ''}',
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),
      title: Text('${c['first_name']}', style: const TextStyle(fontSize: 16)),
      trailing: _busy.contains(id)
          ? const SizedBox(
              width: 22,
              height: 22,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 44)),
              onPressed: () => _restore(c),
              icon: const Icon(Icons.restore_rounded, size: 18),
              label: Text(tr('Restore', 'वापस लाएँ')),
            ),
    );
  }
}

/// Teacher-readable text for a failed manage call: the server's message, or a short
/// "update the server" note when the route itself is missing (older backend).
String _errText(Object e) {
  if (e is! ApiError) {
    return tr(
      'Something went wrong, please try again',
      'कुछ गड़बड़ हो गई, कृपया दोबारा कोशिश करें',
    );
  }
  if (e.status == 404 && e.message == 'Not Found') {
    return tr(
      'This needs the latest server. Ask to update the server.',
      'इसके लिए नया सर्वर चाहिए। सर्वर अपडेट करवाएँ।',
    );
  }
  return e.toString();
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
      _err = trf(
        'Saved {ok} of {namesCount}. {problem} The remaining names are still in the box.',
        '{namesCount} में से {ok} सहेजे गए। {problem} बाकी नाम बॉक्स में हैं।', {'ok': ok, 'namesCount': names.length, 'problem': problem},
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
                trf(
                  'One first name per line. Roll numbers continue from {start}.',
                  'हर लाइन में एक पहला नाम। रोल नंबर {start} से आगे चलेंगे।', {'start': _start},
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
                    trf(
                      '{namesCount} students will be added, roll {start}–{start2}: {names}{v}',
                      '{namesCount} बच्चे जुड़ेंगे, रोल {start}–{start2}: {names}{v}', {'namesCount': names.length, 'start': _start, 'start2': _start + names.length - 1, 'names': names.take(3).join(', '), 'v': names.length > 3 ? '…' : ''},
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
                      ? trf(
                          'Saving {done} of {total}…',
                          '{done} / {total} सहेजे…', {'done': _done, 'total': _total},
                        )
                      : names.isEmpty
                      ? tr('Add students', 'बच्चे जोड़ें')
                      : trf(
                          'Add {namesCount} students',
                          '{namesCount} बच्चे जोड़ें', {'namesCount': names.length},
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

/// What the edit sheet did, so the roster can say it in a SnackBar.
class _EditResult {
  const _EditResult({required this.name, this.movedTo, this.removed = false});
  final String name;
  final String? movedTo;
  final bool removed;
}

/// Edit one student: first name, roll number, move to another class, or remove from the class.
class _EditStudentSheet extends StatefulWidget {
  const _EditStudentSheet({
    required this.child,
    required this.classId,
    required this.className,
  });
  final Map<String, dynamic> child;
  final int classId;
  final String className;
  @override
  State<_EditStudentSheet> createState() => _EditStudentSheetState();
}

class _EditStudentSheetState extends State<_EditStudentSheet> {
  late final _name = TextEditingController(
    text: '${widget.child['first_name']}',
  );
  late final _roll = TextEditingController(text: '${widget.child['roll_no']}');
  // The teacher's classes for "move"; empty (dropdown hidden) until loaded or on failure.
  List<Map<String, dynamic>> _classes = const [];
  late int _target = widget.classId;
  bool _saving = false;
  String? _err;

  int get _id => (widget.child['id'] as num).toInt();

  @override
  void initState() {
    super.initState();
    _loadClasses();
  }

  @override
  void dispose() {
    _name.dispose();
    _roll.dispose();
    super.dispose();
  }

  Future<void> _loadClasses() async {
    try {
      final r = await Api.i.classes();
      final list = r is List
          ? r.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList()
          : <Map<String, dynamic>>[];
      // Only worth showing when there is somewhere to move to and this class is in the list.
      if (mounted &&
          list.length > 1 &&
          list.any((c) => (c['id'] as num?)?.toInt() == widget.classId)) {
        setState(() => _classes = list);
      }
    } catch (_) {}
  }

  String _classLabel(int id) {
    for (final c in _classes) {
      if ((c['id'] as num?)?.toInt() == id) return '${c['label']}';
    }
    return widget.className;
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
    final clipped = name.length > 60 ? name.substring(0, 60) : name;
    // Send only what changed.
    final body = <String, dynamic>{
      if (clipped != '${widget.child['first_name']}') 'first_name': clipped,
      if (roll != (widget.child['roll_no'] as num?)?.toInt()) 'roll_no': roll,
      if (_target != widget.classId) 'class_id': _target,
    };
    if (body.isEmpty) {
      Navigator.pop(context);
      return;
    }
    setState(() {
      _saving = true;
      _err = null;
    });
    try {
      await Api.i.postJson('/v1/children/$_id/edit', body);
      if (!mounted) return;
      Navigator.pop(
        context,
        _EditResult(
          name: clipped,
          movedTo: _target != widget.classId ? _classLabel(_target) : null,
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _err = e is ApiError && e.status == 409
            ? trf(
                'Roll {roll} is already used in {classLabel}. Pick another number.',
                '{classLabel} में रोल {roll} पहले से है। दूसरा नंबर चुनें।', {'roll': roll, 'classLabel': _classLabel(_target)},
              )
            : _errText(e);
      });
    }
  }

  Future<void> _remove() async {
    final name = '${widget.child['first_name']}';
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(trf('Remove {name}?', '{name} को हटाएँ?', {'name': name})),
        content: Text(
          trf(
            '{name} leaves this class list. Their records are kept, and you can bring them back from "Removed students".',
            '{name} इस कक्षा की सूची से हट जाएगा। रिकॉर्ड रखा रहेगा, और "हटाए गए बच्चे" से वापस ला सकते हैं।', {'name': name},
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(tr('Cancel', 'रद्द करें')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Ks.rose,
              minimumSize: const Size(0, 44),
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(tr('Remove', 'हटाएँ')),
          ),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() {
      _saving = true;
      _err = null;
    });
    try {
      await Api.i.postJson('/v1/children/$_id/edit', {'active': false});
      if (mounted) {
        Navigator.pop(context, _EditResult(name: name, removed: true));
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _err = _errText(e);
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
              tr('Edit student', 'बच्चे की जानकारी बदलें'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _name,
              enabled: !_saving,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: tr('First name', 'पहला नाम'),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _roll,
              enabled: !_saving,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: tr('Roll number', 'रोल नंबर'),
              ),
            ),
            if (_classes.isNotEmpty) ...[
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: _target,
                isExpanded: true,
                decoration: InputDecoration(labelText: tr('Class', 'कक्षा')),
                items: [
                  for (final c in _classes)
                    DropdownMenuItem(
                      value: (c['id'] as num).toInt(),
                      child: Text('${c['label']}'),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (v) => setState(() => _target = v ?? widget.classId),
              ),
              if (_target != widget.classId)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    trf(
                      'The student and their records move to {classLabel}.',
                      'बच्चा और उसका रिकॉर्ड {classLabel} में चला जाएगा।', {'classLabel': _classLabel(_target)},
                    ),
                    style: const TextStyle(color: Ks.muted, fontSize: 13),
                  ),
                ),
            ],
            const SizedBox(height: 14),
            if (_err != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(_err!, style: const TextStyle(color: Ks.rose)),
              ),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: Text(
                _saving ? tr('Saving…', 'सहेज रहे हैं…') : tr('Save', 'सहेजें'),
              ),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: Ks.rose,
                minimumSize: const Size(0, 48),
              ),
              onPressed: _saving ? null : _remove,
              icon: const Icon(Icons.person_remove_rounded),
              label: Text(tr('Remove from class', 'कक्षा से हटाएँ')),
            ),
          ],
        ),
      ),
    );
  }
}
