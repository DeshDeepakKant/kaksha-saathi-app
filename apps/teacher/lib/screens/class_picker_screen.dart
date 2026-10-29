import 'package:flutter/material.dart';

import '../api.dart';
import '../api_admin.dart';
import '../theme.dart';
import '../l10n.dart';
import 'class_setup_screen.dart';
import 'roster_screen.dart';
import 'syllabus_screen.dart';

/// Pops the tapped class map (board_screen relies on it). Each class also has "Students" and
/// "Syllabus" shortcuts, and "Add class" opens the setup screen.
class ClassPickerScreen extends StatefulWidget {
  const ClassPickerScreen({super.key});
  @override
  State<ClassPickerScreen> createState() => _ClassPickerScreenState();
}

class _ClassPickerScreenState extends State<ClassPickerScreen> {
  late Future<List<Map<String, dynamic>>> _future = _fetch();
  int? _anyClassId;

  Future<List<Map<String, dynamic>>> _fetch() async {
    final v = await Api.i.classes();
    final list = (v as List).cast<Map<String, dynamic>>();
    _anyClassId = list.isEmpty ? null : (list.first['id'] as num).toInt();
    return list;
  }

  Future<void> _reload() async {
    final f = _fetch();
    setState(() { _future = f; });
    try {
      await f;
    } catch (_) {}
  }

  Future<void> _add() async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ClassSetupScreen(anyClassId: _anyClassId),
      ),
    );
    if (mounted) _reload();
  }

  Future<void> _students(Map<String, dynamic> c) async {
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => RosterScreen(
          classId: (c['id'] as num).toInt(),
          className: '${c['label']}',
        ),
      ),
    );
    if (mounted) _reload(); // child and consent counts may have changed
  }

  void _syllabus(Map<String, dynamic> c) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => SyllabusScreen(
          classId: (c['id'] as num).toInt(),
          subject: 'numeracy',
          className: '${c['label']}',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Classes', 'कक्षाएँ'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _add,
        backgroundColor: Ks.accent,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_rounded),
        label: Text(tr('Add class', 'कक्षा जोड़ें')),
      ),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Loading();
          }
          if (snap.hasError) return _scrollable(_error(snap.error!));
          final list = snap.data ?? [];
          if (list.isEmpty) return _scrollable(_empty());
          return RefreshIndicator(
            onRefresh: _reload,
            child: ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              // Room at the bottom so the add button never covers the last class.
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              itemCount: list.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (_, i) => _tile(list[i]),
            ),
          );
        },
      ),
    );
  }

  /// Lets pull-to-refresh work on the error and empty views too.
  Widget _scrollable(Widget child) => RefreshIndicator(
    onRefresh: _reload,
    child: LayoutBuilder(
      builder: (context, box) => SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: box.maxHeight),
          child: Center(child: child),
        ),
      ),
    ),
  );

  Widget _error(Object e) => Padding(
    padding: const EdgeInsets.all(32),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.cloud_off_rounded, size: 48, color: Ks.muted),
        const SizedBox(height: 12),
        Text(
          friendlyError(e),
          textAlign: TextAlign.center,
          style: const TextStyle(color: Ks.muted, fontSize: 16),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(minimumSize: const Size(160, 48)),
          onPressed: _reload,
          icon: const Icon(Icons.refresh_rounded),
          label: Text(tr('Retry', 'दोबारा कोशिश करें')),
        ),
      ],
    ),
  );

  Widget _empty() => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      EmptyState(
        icon: Icons.groups_rounded,
        text: tr(
          'No class yet. Add your first class.',
          'अभी कोई कक्षा नहीं। अपनी पहली कक्षा जोड़ें।',
        ),
      ),
      FilledButton.icon(
        style: FilledButton.styleFrom(minimumSize: const Size(200, 52)),
        onPressed: _add,
        icon: const Icon(Icons.add_rounded),
        label: Text(tr('Add class', 'कक्षा जोड़ें')),
      ),
    ],
  );

  Widget _tile(Map<String, dynamic> c) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 18,
              vertical: 8,
            ),
            leading: const Icon(
              Icons.groups_rounded,
              color: Ks.accent,
              size: 30,
            ),
            title: Text(
              '${c['label']}',
              style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w600),
            ),
            subtitle: Text(
              tr(
                '${c['children']} children · consent ${c['consented']}',
                '${c['children']} बच्चे · सहमति ${c['consented']}',
              ),
            ),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).pop(c),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Wrap(
              spacing: 4,
              children: [
                TextButton.icon(
                  onPressed: () => _students(c),
                  icon: const Icon(Icons.people_alt_outlined, size: 20),
                  label: Text(tr('Students', 'बच्चे')),
                ),
                TextButton.icon(
                  onPressed: () => _syllabus(c),
                  icon: const Icon(Icons.menu_book_outlined, size: 20),
                  label: Text(tr('Syllabus', 'पाठ्यक्रम')),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
