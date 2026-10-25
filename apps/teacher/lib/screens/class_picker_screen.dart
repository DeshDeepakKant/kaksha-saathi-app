import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import '../l10n.dart';

class ClassPickerScreen extends StatelessWidget {
  const ClassPickerScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Classes', 'कक्षाएँ'))),
      body: FutureBuilder(
        future: Api.i.classes(),
        builder: (context, snap) {
          if (!snap.hasData) return const Loading();
          final list = (snap.data as List).cast<Map<String, dynamic>>();
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: list.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (_, i) {
              final c = list[i];
              return Card(
                child: ListTile(
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
                    c['label'],
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w600,
                    ),
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
              );
            },
          );
        },
      ),
    );
  }
}
