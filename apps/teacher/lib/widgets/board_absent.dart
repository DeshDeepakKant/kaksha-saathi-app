import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';

/// Compact "Absent today (n)" strip with the absent children's names and an edit button.
class BoardAbsentStrip extends StatelessWidget {
  const BoardAbsentStrip({
    super.key,
    required this.count,
    required this.names,
    required this.onEdit,
  });
  final int count;
  final List<String> names;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    const maxNames = 4;
    final shown = names.take(maxNames).join(', ');
    final extra = count - names.take(maxNames).length;
    final text = count == 0
        ? tr('Everyone is marked present', 'सब उपस्थित दर्ज हैं')
        : (extra > 0 ? '$shown +$extra' : shown);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 4, 6, 4),
        child: Row(
          children: [
            const Icon(Icons.event_busy_rounded, color: Ks.muted),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    tr('Absent today ($count)', 'आज अनुपस्थित ($count)'),
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 15,
                      color: Ks.ink,
                    ),
                  ),
                  if (text.isNotEmpty)
                    Text(
                      text,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Ks.muted, fontSize: 14),
                    ),
                ],
              ),
            ),
            TextButton(
              style: TextButton.styleFrom(
                minimumSize: const Size(48, 48),
                foregroundColor: Ks.accent,
              ),
              onPressed: onEdit,
              child: Text(tr('Edit', 'बदलें')),
            ),
          ],
        ),
      ),
    );
  }
}

/// What the register sheet saved: the absent child ids, and whether the write was parked offline.
class BoardAbsentResult {
  const BoardAbsentResult(this.ids, this.queued);
  final List<int> ids;
  final bool queued;
}

/// Opens the register editor. Returns null if the teacher closed it without saving.
Future<BoardAbsentResult?> showBoardAbsentSheet(
  BuildContext context, {
  required int classId,
  required List<int> absentIds,
}) => showModalBottomSheet<BoardAbsentResult>(
  context: context,
  isScrollControlled: true,
  backgroundColor: Ks.paper,
  shape: const RoundedRectangleBorder(
    borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
  ),
  builder: (_) => _AbsentSheet(classId: classId, absentIds: absentIds),
);

class _AbsentSheet extends StatefulWidget {
  const _AbsentSheet({required this.classId, required this.absentIds});
  final int classId;
  final List<int> absentIds;
  @override
  State<_AbsentSheet> createState() => _AbsentSheetState();
}

class _AbsentSheetState extends State<_AbsentSheet> {
  late final Future<List<Map<String, dynamic>>> _roster;
  late final Set<int> _absent = {...widget.absentIds};
  List<Map<String, dynamic>> _rows = const [];
  bool _ready =
      false; // saving before the roster loads would wipe the day's register
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _roster = _loadRoster().then((rows) {
      if (mounted) setState(() => _ready = rows.isNotEmpty);
      return rows;
    });
  }

  Future<List<Map<String, dynamic>>> _loadRoster() async {
    final r = await Api.i.roster(widget.classId);
    final rows = r is List
        ? r.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList()
        : <Map<String, dynamic>>[];
    _rows = rows;
    return rows;
  }

  int? _id(Map<String, dynamic> c) => int.tryParse('${c['id']}');
  int? _roll(Map<String, dynamic> c) => int.tryParse('${c['roll_no']}');

  Future<void> _save() async {
    // The server replaces the whole day's register, so send every absent roll, not just changes.
    final ids = <int>[];
    final rolls = <int>[];
    for (final c in _rows) {
      final id = _id(c);
      final roll = _roll(c);
      if (id != null && roll != null && _absent.contains(id)) {
        ids.add(id);
        rolls.add(roll);
      }
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final r = await Api.i.postQueued(
        '/v1/classes/${widget.classId}/attendance',
        {'absent_rolls': rolls},
      );
      if (!mounted) return;
      final queued = r is Map && r['queued'] == true;
      Navigator.of(context).pop(BoardAbsentResult(ids, queued));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.of(context).size.height * 0.85;
    return SizedBox(
      height: height,
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom,
        ),
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 8, 4),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      tr("Today's register", 'आज की हाज़िरी'),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: tr('Close', 'बंद करें'),
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  tr(
                    'Switch on the children who are absent.',
                    'जो बच्चे अनुपस्थित हैं उन्हें चालू करें।',
                  ),
                  style: const TextStyle(color: Ks.muted, fontSize: 15),
                ),
              ),
            ),
            const SizedBox(height: 6),
            Expanded(
              child: FutureBuilder<List<Map<String, dynamic>>>(
                future: _roster,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const Loading();
                  }
                  if (snap.hasError) {
                    return EmptyState(
                      icon: Icons.cloud_off_rounded,
                      text: tr(
                        "Couldn't load the class list. Close and try again.",
                        'कक्षा की सूची नहीं आई। बंद करके दोबारा कोशिश करें।',
                      ),
                    );
                  }
                  final rows = snap.data!;
                  if (rows.isEmpty) {
                    return EmptyState(
                      icon: Icons.group_off_rounded,
                      text: tr(
                        'No children in this class.',
                        'इस कक्षा में कोई बच्चा नहीं।',
                      ),
                    );
                  }
                  return ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    itemCount: rows.length,
                    itemBuilder: (_, i) {
                      final c = rows[i];
                      final id = _id(c);
                      final roll = c['roll_no'];
                      return SwitchListTile(
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 8,
                        ),
                        activeThumbColor: Colors.white,
                        activeTrackColor: Ks.rose,
                        title: Text(
                          '${roll ?? ''}  ${c['first_name'] ?? ''}'.trim(),
                          style: const TextStyle(fontSize: 17),
                        ),
                        subtitle: Text(
                          id != null && _absent.contains(id)
                              ? tr('Absent', 'अनुपस्थित')
                              : tr('Present', 'उपस्थित'),
                          style: const TextStyle(color: Ks.muted),
                        ),
                        value: id != null && _absent.contains(id),
                        onChanged: id == null || _saving
                            ? null
                            : (v) => setState(() {
                                v ? _absent.add(id) : _absent.remove(id);
                              }),
                      );
                    },
                  );
                },
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
                child: Text(_error!, style: const TextStyle(color: Ks.rose)),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
              child: FilledButton(
                onPressed: (_saving || !_ready) ? null : _save,
                child: _saving
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : Text(tr('Save register', 'हाज़िरी सहेजें')),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
