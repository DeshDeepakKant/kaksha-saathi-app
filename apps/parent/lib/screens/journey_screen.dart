import 'package:flutter/material.dart';

import '../l10n.dart';

/// Stub (see docs/parent_insights_contract.md); the UI agent replaces the body, the constructor stays.
class JourneyScreen extends StatefulWidget {
  const JourneyScreen({super.key});
  @override
  State<JourneyScreen> createState() => _JourneyScreenState();
}

class _JourneyScreenState extends State<JourneyScreen> {
  @override
  Widget build(BuildContext context) =>
      Scaffold(appBar: AppBar(title: Text(tr('Learning journey', 'सीखने का सफ़र'))));
}
