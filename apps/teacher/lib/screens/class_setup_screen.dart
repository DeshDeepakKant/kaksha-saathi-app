import 'package:flutter/material.dart';

import '../api.dart';
import '../api_admin.dart';
import '../theme.dart';
import '../l10n.dart';
import 'roster_screen.dart';

/// Add a class (grade + section) and add subjects for the school.
/// [anyClassId] is any existing class; it is only used to list the school's subjects.
class ClassSetupScreen extends StatefulWidget {
  const ClassSetupScreen({super.key, this.anyClassId});
  final int? anyClassId;
  @override
  State<ClassSetupScreen> createState() => _ClassSetupScreenState();
}

class _ClassSetupScreenState extends State<ClassSetupScreen> {
  int? _grade;
  final _section = TextEditingController(text: 'A');
  final _label = TextEditingController();
  bool _creating = false;
  String? _classErr;
  Map<String, dynamic>? _created;

  final _subName = TextEditingController();
  final _subHi = TextEditingController();
  bool _addingSubject = false;
  String? _subErr;
  List<Map<String, dynamic>>? _subjects;
  late int? _subjectsClassId = widget.anyClassId;

  @override
  void initState() {
    super.initState();
    _loadSubjects();
  }

  @override
  void dispose() {
    _section.dispose();
    _label.dispose();
    _subName.dispose();
    _subHi.dispose();
    super.dispose();
  }

  Future<void> _loadSubjects() async {
    final id = _subjectsClassId;
    if (id == null) return;
    try {
      final s = await AdminApi.subjects(id);
      if (mounted) setState(() => _subjects = s);
    } catch (_) {
      // The list is a nicety; adding a subject still works without it.
    }
  }

  String get _sectionText => _section.text.trim().toUpperCase();

  Future<void> _createClass() async {
    final grade = _grade;
    if (grade == null) {
      setState(
        () => _classErr = tr('Pick a class (1 to 8)', 'कक्षा चुनें (1 से 8)'),
      );
      return;
    }
    if (_sectionText.isEmpty) {
      setState(
        () => _classErr = tr(
          'Type a section, for example A',
          'सेक्शन लिखें, जैसे A',
        ),
      );
      return;
    }
    setState(() {
      _creating = true;
      _classErr = null;
    });
    try {
      final c = await AdminApi.createClass(
        grade,
        _sectionText,
        label: _label.text,
      );
      if (!mounted) return;
      setState(() {
        _creating = false;
        _created = c;
        _subjectsClassId ??= (c['id'] as num?)?.toInt();
      });
      if (_subjects == null) _loadSubjects();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _classErr = (e is ApiError && e.status == 409)
            ? tr('This class already exists', 'यह कक्षा पहले से मौजूद है')
            : friendlyError(e);
      });
    }
  }

  void _another() => setState(() {
    _created = null;
    _grade = null;
    _section.text = 'A';
    _label.clear();
  });

  Future<void> _addSubject() async {
    final name = _subName.text.trim();
    if (name.isEmpty) {
      setState(
        () => _subErr = tr('Type the subject name', 'विषय का नाम लिखें'),
      );
      return;
    }
    setState(() {
      _addingSubject = true;
      _subErr = null;
    });
    try {
      final s = await AdminApi.createSubject(name, nameHi: _subHi.text);
      if (!mounted) return;
      setState(() {
        _addingSubject = false;
        _subjects = [...?_subjects, s];
        _subName.clear();
        _subHi.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(tr('Subject "$name" added', 'विषय "$name" जुड़ गया')),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _addingSubject = false;
        _subErr = (e is ApiError && e.status == 409)
            ? tr('This subject already exists', 'यह विषय पहले से मौजूद है')
            : friendlyError(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final created = _created;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Add class', 'कक्षा जोड़ें'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (created != null) _createdCard(created) else _classForm(),
          const SizedBox(height: 24),
          _subjectsSection(),
        ],
      ),
    );
  }

  Widget _classForm() => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('New class', 'नई कक्षा'),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 12),
          Text(tr('Class', 'कक्षा'), style: const TextStyle(color: Ks.muted)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (var g = 1; g <= 8; g++)
                ChoiceChip(
                  label: Text('$g'),
                  selected: _grade == g,
                  showCheckmark: false,
                  labelStyle: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w600,
                    color: _grade == g ? Colors.white : Ks.ink,
                  ),
                  selectedColor: Ks.accent,
                  onSelected: _creating
                      ? null
                      : (_) => setState(() => _grade = g),
                ),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _section,
            enabled: !_creating,
            maxLength: 3,
            textCapitalization: TextCapitalization.characters,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: tr('Section', 'सेक्शन'),
              counterText: '',
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              for (final s in const ['A', 'B', 'C', 'D'])
                ActionChip(
                  label: Text(s),
                  onPressed: _creating
                      ? null
                      : () => setState(() => _section.text = s),
                ),
            ],
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _label,
            enabled: !_creating,
            decoration: InputDecoration(
              labelText: tr('Name (optional)', 'नाम (वैकल्पिक)'),
              hintText: _grade == null
                  ? null
                  : tr(
                      'Class $_grade $_sectionText',
                      'कक्षा $_grade $_sectionText',
                    ),
            ),
          ),
          if (_classErr != null) ...[
            const SizedBox(height: 10),
            Text(_classErr!, style: const TextStyle(color: Ks.rose)),
          ],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _creating ? null : _createClass,
            child: Text(
              _creating
                  ? tr('Creating…', 'बना रहे हैं…')
                  : tr('Create class', 'कक्षा बनाएँ'),
            ),
          ),
        ],
      ),
    ),
  );

  Widget _createdCard(Map<String, dynamic> c) {
    final id = (c['id'] as num).toInt();
    final label = '${c['label'] ?? ''}';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.check_circle_rounded, color: Ks.green),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    tr('$label created', '$label बन गई'),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            FilledButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => RosterScreen(classId: id, className: label),
                ),
              ),
              icon: const Icon(Icons.person_add_alt_1_rounded),
              label: Text(tr('Add students now', 'अभी बच्चे जोड़ें')),
            ),
            const SizedBox(height: 10),
            OutlinedButton(
              onPressed: _another,
              child: Text(tr('Add another class', 'एक और कक्षा जोड़ें')),
            ),
            const SizedBox(height: 10),
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: Text(tr('Done', 'हो गया')),
            ),
          ],
        ),
      ),
    );
  }

  Widget _subjectsSection() => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            tr('Add a subject', 'विषय जोड़ें'),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            tr(
              'Subjects are shared by all classes in your school.',
              'विषय आपके स्कूल की सभी कक्षाओं के लिए एक जैसे होते हैं।',
            ),
            style: const TextStyle(color: Ks.muted),
          ),
          if (_subjects != null && _subjects!.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final s in _subjects!)
                  Chip(
                    avatar: s['builtin'] == true
                        ? const Icon(Icons.lock_outline_rounded, size: 16)
                        : null,
                    label: Text(_subjectName(s)),
                    backgroundColor: Ks.accentSoft,
                    side: BorderSide.none,
                  ),
              ],
            ),
          ],
          const SizedBox(height: 16),
          TextField(
            controller: _subName,
            enabled: !_addingSubject,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(
              labelText: tr(
                'Subject name (English)',
                'विषय का नाम (अंग्रेज़ी)',
              ),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _subHi,
            enabled: !_addingSubject,
            decoration: InputDecoration(
              labelText: tr(
                'Name in Hindi (optional)',
                'हिंदी में नाम (वैकल्पिक)',
              ),
            ),
          ),
          if (_subErr != null) ...[
            const SizedBox(height: 10),
            Text(_subErr!, style: const TextStyle(color: Ks.rose)),
          ],
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _addingSubject ? null : _addSubject,
            icon: const Icon(Icons.add_rounded),
            label: Text(
              _addingSubject
                  ? tr('Adding…', 'जोड़ रहे हैं…')
                  : tr('Add subject', 'विषय जोड़ें'),
            ),
          ),
        ],
      ),
    ),
  );

  String _subjectName(Map<String, dynamic> s) {
    final n = pick(s, 'name');
    if (n.isNotEmpty) return n;
    return '${s['name_en'] ?? s['name'] ?? s['key'] ?? ''}';
  }
}
