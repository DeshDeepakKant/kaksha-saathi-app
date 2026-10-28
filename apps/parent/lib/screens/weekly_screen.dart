import 'package:flutter/material.dart';

import '../l10n.dart';

/// Stub (see docs/parent_insights_contract.md); the UI agent replaces the body, the constructor stays.
class WeeklyScreen extends StatefulWidget {
  const WeeklyScreen({super.key});
  @override
  State<WeeklyScreen> createState() => _WeeklyScreenState();
}

class _WeeklyScreenState extends State<WeeklyScreen> {
  @override
  Widget build(BuildContext context) =>
      Scaffold(appBar: AppBar(title: Text(tr('This week', 'इस हफ़्ते'))));
}
