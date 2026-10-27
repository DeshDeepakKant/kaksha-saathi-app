import 'package:flutter/material.dart';

import '../l10n.dart';

/// Syllabus & progress: every lesson (checkpoint) of a subject with how many children are
/// done / in progress / not started, plus add-topic and index-photo import.
/// Stub: the real screen replaces this file; the constructor is the contract other screens use.
class SyllabusScreen extends StatefulWidget {
  const SyllabusScreen({
    super.key,
    required this.classId,
    required this.subject,
    required this.className,
  });
  final int classId;
  final String subject;
  final String className;
  @override
  State<SyllabusScreen> createState() => _SyllabusScreenState();
}

class _SyllabusScreenState extends State<SyllabusScreen> {
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(tr('Syllabus', 'पाठ्यक्रम'))),
    body: const SizedBox.shrink(),
  );
}
