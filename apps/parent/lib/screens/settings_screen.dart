import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'gate_screen.dart';

/// Parent settings: language and voice (saved per parent), and sign out.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  @override
  Widget build(BuildContext context) {
    final c = Api.i.child;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Settings', 'सेटिंग्स'))),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (c != null) ...[
                Card(
                  child: ListTile(
                    leading: const Icon(
                      Icons.child_care_rounded,
                      color: Ks.accent,
                    ),
                    title: Text('${c['first_name'] ?? ''}'),
                    subtitle: Text(
                      [
                        if (c['class'] != null) '${c['class']}',
                        if (c['roll_no'] != null)
                          '${tr('Roll', 'रोल')} ${c['roll_no']}',
                      ].join(' · '),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              const LanguageVoiceCard(),
              const SizedBox(height: 20),
              OutlinedButton.icon(
                onPressed: () async {
                  await Api.i.logout();
                  if (!context.mounted) return;
                  Navigator.of(context).pushAndRemoveUntil(
                    MaterialPageRoute(builder: (_) => const GateScreen()),
                    (_) => false,
                  );
                },
                icon: const Icon(Icons.logout_rounded),
                label: Text(tr('Log out', 'लॉगआउट')),
              ),
            ],
          ),
        ),
      ),
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
