import 'package:flutter/material.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'syllabus_widgets.dart';

/// Bottom sheet: add one custom topic to the syllabus. Pops `true` once it is saved.
class SylAddTopicSheet extends StatefulWidget {
  const SylAddTopicSheet({
    super.key,
    required this.classId,
    required this.subject,
    required this.chapters,
  });
  final int classId;
  final String subject;

  /// Existing chapter names (may be empty).
  final List<String> chapters;
  @override
  State<SylAddTopicSheet> createState() => _SylAddTopicSheetState();
}

class _SylAddTopicSheetState extends State<SylAddTopicSheet> {
  static const _newChapter = '\u0000new';
  final _newChapterCtl = TextEditingController();
  final _titleCtl = TextEditingController();
  final _titleHiCtl = TextEditingController();
  late String _chapter = widget.chapters.isEmpty
      ? _newChapter
      : widget.chapters.last;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _newChapterCtl.dispose();
    _titleCtl.dispose();
    _titleHiCtl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final en = _titleCtl.text.trim();
    final hi = _titleHiCtl.text.trim();
    final chapter = _chapter == _newChapter
        ? _newChapterCtl.text.trim()
        : _chapter;
    if (en.isEmpty && hi.isEmpty) {
      setState(() => _error = tr('Type the topic name.', 'विषय का नाम लिखें।'));
      return;
    }
    if (chapter.isEmpty) {
      setState(
        () => _error = tr('Type a chapter name.', 'अध्याय का नाम लिखें।'),
      );
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Api.i.postJson('/v1/classes/${widget.classId}/syllabus/topics', {
        'subject': widget.subject,
        'chapter': chapter,
        'title': en.isNotEmpty ? en : hi,
        if (hi.isNotEmpty) 'title_hi': hi,
      });
      if (mounted) Navigator.pop(context, true);
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = tr(
            'Could not save. Check the network and try again.',
            'सहेज नहीं सके। नेटवर्क देखकर दोबारा कोशिश करें।',
          );
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = [
      for (final c in widget.chapters)
        DropdownMenuItem(
          value: c,
          child: Text(sylChapterName(c), overflow: TextOverflow.ellipsis),
        ),
      DropdownMenuItem(
        value: _newChapter,
        child: Text(tr('+ New chapter', '+ नया अध्याय')),
      ),
    ];
    return SafeArea(
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(
          20,
          16,
          20,
          20 + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              tr('Add a topic', 'विषय जोड़ें'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              tr(
                'It joins your syllabus and can be checked like any other lesson.',
                'यह आपके पाठ्यक्रम में जुड़ जाएगा और बाकी पाठों की तरह जाँचा जा सकेगा।',
              ),
              style: const TextStyle(color: Ks.muted, fontSize: 14),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _chapter,
              isExpanded: true,
              decoration: InputDecoration(labelText: tr('Chapter', 'अध्याय')),
              items: items,
              onChanged: _busy
                  ? null
                  : (v) => setState(() => _chapter = v ?? _chapter),
            ),
            if (_chapter == _newChapter) ...[
              const SizedBox(height: 12),
              TextField(
                controller: _newChapterCtl,
                enabled: !_busy,
                textCapitalization: TextCapitalization.sentences,
                decoration: InputDecoration(
                  labelText: tr('New chapter name', 'नए अध्याय का नाम'),
                ),
              ),
            ],
            const SizedBox(height: 12),
            TextField(
              controller: _titleCtl,
              enabled: !_busy,
              textCapitalization: TextCapitalization.sentences,
              decoration: InputDecoration(
                labelText: tr(
                  'Topic name (English)',
                  'विषय का नाम (अंग्रेज़ी)',
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _titleHiCtl,
              enabled: !_busy,
              decoration: InputDecoration(
                labelText: tr(
                  'Topic name in Hindi (optional)',
                  'हिन्दी में नाम (वैकल्पिक)',
                ),
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: const TextStyle(color: Ks.rose, fontSize: 14.5),
              ),
            ],
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy ? null : _save,
              child: _busy
                  ? const SizedBox(
                      height: 22,
                      width: 22,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.5,
                        color: Colors.white,
                      ),
                    )
                  : Text(tr('Add to syllabus', 'पाठ्यक्रम में जोड़ें')),
            ),
          ],
        ),
      ),
    );
  }
}
