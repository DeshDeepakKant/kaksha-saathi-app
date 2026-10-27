import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../l10n.dart';
import '../theme.dart';
import 'syllabus_widgets.dart';

/// Import the syllabus from a photo of the book's index page, or from typed lines.
///
/// The AI only proposes: the draft is shown as an editable list (rename, drop, unlink from a
/// matched lesson) and nothing is saved until the teacher presses Confirm. Pops `true` once the
/// syllabus was saved.
class SylImportScreen extends StatefulWidget {
  const SylImportScreen({
    super.key,
    required this.classId,
    required this.subject,
    required this.existingChapters,
    required this.confirmed,
  });
  final int classId;
  final String subject;

  /// The chapters (from `GET .../syllabus`) currently on the screen.
  final List<Map<String, dynamic>> existingChapters;

  /// True when the teacher already confirmed a syllabus (then offer to keep its topics, since
  /// `POST .../syllabus` writes a whole new version).
  final bool confirmed;
  @override
  State<SylImportScreen> createState() => _SylImportScreenState();
}

enum _Stage { pick, uploading, error, typing, review }

class _Row {
  _Row({this.checkpointId, required String text, this.matchTitle})
    : ctl = TextEditingController(text: text);
  String? checkpointId;
  String? matchTitle;
  final TextEditingController ctl;
  bool get matched => checkpointId != null;
}

class _Chap {
  _Chap(String name) : name = TextEditingController(text: name);
  final TextEditingController name;
  final List<_Row> rows = [];
}

final _devanagari = RegExp(r'[ऀ-ॿ]');

class _SylImportScreenState extends State<SylImportScreen> {
  _Stage _stage = _Stage.pick;
  String? _error;
  int _errorStatus = 0;
  Uint8List? _bytes;
  String _filename = 'index.jpg';
  String _source = 'photo';
  String? _note;
  final List<_Chap> _chaps = [];
  final _typeCtl = TextEditingController();
  Map<String, String> _titles = {};
  late bool _keep = widget.confirmed && _existingCount > 0;
  bool _saving = false;
  String? _saveError;

  int get _existingCount => widget.existingChapters.fold(
    0,
    (n, c) => n + sylMaps(c['topics']).length,
  );

  @override
  void dispose() {
    _typeCtl.dispose();
    for (final c in _chaps) {
      c.name.dispose();
      for (final r in c.rows) {
        r.ctl.dispose();
      }
    }
    super.dispose();
  }

  void _toast(String s) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));

  // ---- step 1: photo -> draft
  Future<void> _pickPhoto(ImageSource src) async {
    try {
      final file = await ImagePicker().pickImage(
        source: src,
        maxWidth: 1800,
        imageQuality: 85,
      );
      if (file == null) return;
      final bytes = await file.readAsBytes();
      _bytes = bytes;
      _filename = file.name.isEmpty ? 'index.jpg' : file.name;
      await _upload();
    } catch (_) {
      if (!mounted) return;
      _toast(
        tr(
          'Could not open the camera or gallery.',
          'कैमरा या गैलरी नहीं खुली।',
        ),
      );
    }
  }

  Future<void> _upload() async {
    final bytes = _bytes;
    if (bytes == null) return;
    setState(() {
      _stage = _Stage.uploading;
      _error = null;
    });
    try {
      final r = await Api.i.postMultipart(
        '/v1/classes/${widget.classId}/roadmap/draft',
        fields: {'subject': widget.subject},
        file: bytes,
        filename: _filename,
      );
      final m = (r as Map).cast<String, dynamic>();
      final items = sylMaps(m['items']);
      if (items.isEmpty) {
        _fail(
          (m['note'] as String?) ??
              tr(
                'The index could not be read from this photo.',
                'इस फ़ोटो से अनुक्रम नहीं पढ़ा जा सका।',
              ),
          422,
        );
        return;
      }
      await _loadTitles(items);
      if (!mounted) return;
      _fillFromDraft(items);
      setState(() {
        _source = 'photo';
        _note = m['status'] == 'ready' ? null : m['note'] as String?;
        _saveError = null;
        _stage = _Stage.review;
      });
    } on ApiError catch (e) {
      _fail(e.message, e.status);
    } catch (_) {
      _fail(
        tr(
          'Could not reach the server. Check the network and try again.',
          'सर्वर तक नहीं पहुँच सके। नेटवर्क देखकर दोबारा कोशिश करें।',
        ),
        0,
      );
    }
  }

  void _fail(String msg, int status) {
    if (!mounted) return;
    setState(() {
      _stage = _Stage.error;
      _error = msg;
      _errorStatus = status;
    });
  }

  /// Titles of the lessons the draft matched, so a matched row can show what it matched.
  Future<void> _loadTitles(List<Map<String, dynamic>> items) async {
    if (!items.any((i) => i['checkpoint_id'] != null)) return;
    try {
      final r = await Api.i.get(
        '/v1/content/checkpoints?subject=${Uri.encodeQueryComponent(widget.subject)}',
      );
      _titles = {for (final c in sylMaps(r)) c['id'].toString(): cpTitle(c)};
    } catch (_) {
      // Rows fall back to a generic "existing lesson" label.
    }
  }

  /// Turns the flat draft items into chapters. The backend emits a heading item per chapter
  /// (custom title == chapter name, no lesson); it is dropped when the chapter has other rows.
  void _fillFromDraft(List<Map<String, dynamic>> items) {
    _resetChapters();
    final groups = <String, List<Map<String, dynamic>>>{};
    for (final it in items) {
      final ch = (it['chapter'] ?? '').toString().trim();
      groups.putIfAbsent(ch, () => []).add(it);
    }
    groups.forEach((ch, list) {
      final first = list.first;
      final isHeading =
          list.length > 1 &&
          ch.isNotEmpty &&
          first['checkpoint_id'] == null &&
          (first['custom_title'] ?? '').toString().trim() == ch;
      final chap = _Chap(ch);
      for (final it in isHeading ? list.skip(1) : list) {
        final cp = it['checkpoint_id']?.toString();
        if (cp != null && cp.isNotEmpty) {
          chap.rows.add(
            _Row(
              checkpointId: cp,
              text: '',
              matchTitle: _titles[cp] ?? tr('Existing lesson', 'मौजूदा पाठ'),
            ),
          );
        } else {
          chap.rows.add(
            _Row(text: (it['custom_title'] ?? '').toString().trim()),
          );
        }
      }
      if (chap.rows.isNotEmpty) _chaps.add(chap);
    });
  }

  void _resetChapters() {
    for (final c in _chaps) {
      c.name.dispose();
      for (final r in c.rows) {
        r.ctl.dispose();
      }
    }
    _chaps.clear();
  }

  // ---- fallback: typed topics
  /// One topic per line; "Chapter: topic" sets the chapter, which then carries on to the
  /// following lines that have no chapter of their own.
  void _fillFromTyped() {
    _resetChapters();
    final byName = <String, _Chap>{};
    var current = '';
    for (final raw in _typeCtl.text.split('\n')) {
      var line = raw.trim();
      if (line.isEmpty) continue;
      final i = line.indexOf(RegExp('[:：]'));
      if (i > 0 && i < line.length - 1) {
        current = line.substring(0, i).trim();
        line = line.substring(i + 1).trim();
      }
      if (line.isEmpty) continue;
      byName
          .putIfAbsent(current, () => _Chap(current))
          .rows
          .add(_Row(text: line));
    }
    _chaps.addAll(byName.values);
  }

  void _reviewTyped() {
    _fillFromTyped();
    if (_chaps.isEmpty) {
      _toast(tr('Type at least one topic.', 'कम से कम एक विषय लिखें।'));
      return;
    }
    setState(() {
      _source = 'import';
      _note = null;
      _saveError = null;
      _stage = _Stage.review;
    });
  }

  // ---- step 2: confirm
  int get _topicCount {
    var n = 0;
    final seen = <String>{};
    for (final c in _chaps) {
      for (final r in c.rows) {
        if (r.matched
            ? seen.add(r.checkpointId!)
            : r.ctl.text.trim().isNotEmpty) {
          n++;
        }
      }
    }
    return n;
  }

  List<Map<String, dynamic>> _buildItems() {
    final items = <Map<String, dynamic>>[];
    final seen = <String>{};
    var pos = 0;
    if (_keep) {
      for (final c in widget.existingChapters) {
        final ch = (c['chapter'] ?? '').toString().trim();
        for (final t in sylMaps(c['topics'])) {
          final cp = t['checkpoint_id']?.toString();
          if (cp == null || !seen.add(cp)) continue;
          items.add({
            'checkpoint_id': cp,
            'chapter': ?(ch.isEmpty ? null : ch),
            'position': pos++,
          });
        }
      }
    }
    for (final c in _chaps) {
      final ch = c.name.text.trim();
      for (final r in c.rows) {
        if (r.matched) {
          if (!seen.add(r.checkpointId!)) continue;
          items.add({
            'checkpoint_id': r.checkpointId,
            'chapter': ?(ch.isEmpty ? null : ch),
            'position': pos++,
          });
        } else {
          final text = r.ctl.text.trim();
          if (text.isEmpty) continue;
          items.add({
            'custom_title': text,
            if (_devanagari.hasMatch(text)) 'custom_title_hi': text,
            'chapter': ?(ch.isEmpty ? null : ch),
            'position': pos++,
          });
        }
      }
    }
    return items;
  }

  Future<void> _confirm() async {
    final items = _buildItems();
    if (items.isEmpty) return;
    setState(() {
      _saving = true;
      _saveError = null;
    });
    try {
      await Api.i.postJson('/v1/classes/${widget.classId}/syllabus', {
        'subject': widget.subject,
        'source': _source,
        'items': items,
      });
      if (mounted) Navigator.pop(context, true);
    } on ApiError catch (e) {
      // The draft and every edit stay on screen so the teacher can retry.
      if (mounted) {
        setState(() {
          _saving = false;
          _saveError = e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _saving = false;
          _saveError = tr(
            'Could not save. Your edits are kept: check the network and try again.',
            'सहेज नहीं सके। आपके बदलाव सुरक्षित हैं: नेटवर्क देखकर दोबारा कोशिश करें।',
          );
        });
      }
    }
  }

  // ---- UI
  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _stage != _Stage.review || _saving,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final leave = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: Text(tr('Discard this draft?', 'यह मसौदा छोड़ दें?')),
            content: Text(
              tr(
                'Your edits have not been saved.',
                'आपके बदलाव अभी सहेजे नहीं गए हैं।',
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: Text(tr('Keep editing', 'संपादन जारी रखें')),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: Text(tr('Discard', 'छोड़ दें')),
              ),
            ],
          ),
        );
        if (leave == true && mounted) Navigator.pop(this.context);
      },
      child: Scaffold(
        appBar: AppBar(title: Text(tr('Import syllabus', 'पाठ्यक्रम जोड़ें'))),
        body: switch (_stage) {
          _Stage.pick => _pickView(),
          _Stage.uploading => Loading(
            label: tr('Reading the index page…', 'अनुक्रम पृष्ठ पढ़ रहे हैं…'),
          ),
          _Stage.error => _errorView(),
          _Stage.typing => _typingView(),
          _Stage.review => _reviewView(),
        },
      ),
    );
  }

  Widget _proposeNote() => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: Ks.accentSoft,
      borderRadius: BorderRadius.circular(14),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.auto_awesome_rounded, color: Ks.accent, size: 20),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            tr(
              'The AI only proposes a list. You check it, fix it and confirm. Nothing is saved until you press Confirm.',
              'AI सिर्फ़ एक सूची सुझाता है। आप उसे जाँचें, ठीक करें और पक्का करें। "पक्का करें" दबाने तक कुछ सहेजा नहीं जाता।',
            ),
            style: const TextStyle(fontSize: 14.5, color: Ks.ink, height: 1.35),
          ),
        ),
      ],
    ),
  );

  Widget _pickView() => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Text(
        tr(
          'Take a photo of the contents page of the book.',
          'किताब के विषय-सूची वाले पन्ने की फ़ोटो लें।',
        ),
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 6),
      Text(
        tr(
          'Keep the whole page in the frame, in good light.',
          'पूरा पन्ना फ़्रेम में रखें, अच्छी रोशनी में।',
        ),
        style: const TextStyle(color: Ks.muted),
      ),
      const SizedBox(height: 14),
      _proposeNote(),
      const SizedBox(height: 20),
      FilledButton.icon(
        onPressed: () => _pickPhoto(ImageSource.camera),
        icon: const Icon(Icons.photo_camera_rounded),
        label: Text(tr('Take a photo', 'फ़ोटो लें')),
      ),
      const SizedBox(height: 10),
      OutlinedButton.icon(
        onPressed: () => _pickPhoto(ImageSource.gallery),
        icon: const Icon(Icons.photo_library_rounded),
        label: Text(tr('Choose from gallery', 'गैलरी से चुनें')),
      ),
      const SizedBox(height: 10),
      TextButton.icon(
        onPressed: () => setState(() => _stage = _Stage.typing),
        icon: const Icon(Icons.keyboard_rounded),
        label: Text(tr('Type the topics instead', 'इसके बजाय विषय टाइप करें')),
      ),
    ],
  );

  Widget _errorView() {
    // 503 / 422: the reader (AI) is unavailable or could not read the page, so typing is the way on.
    final typeFirst = _errorStatus == 503 || _errorStatus == 422;
    final typeBtn = typeFirst
        ? FilledButton.icon(
            onPressed: () => setState(() => _stage = _Stage.typing),
            icon: const Icon(Icons.keyboard_rounded),
            label: Text(
              tr('Type the topics instead', 'इसके बजाय विषय टाइप करें'),
            ),
          )
        : OutlinedButton.icon(
            onPressed: () => setState(() => _stage = _Stage.typing),
            icon: const Icon(Icons.keyboard_rounded),
            label: Text(
              tr('Type the topics instead', 'इसके बजाय विषय टाइप करें'),
            ),
          );
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const SizedBox(height: 24),
        const Icon(Icons.error_outline_rounded, size: 48, color: Ks.rose),
        const SizedBox(height: 12),
        Text(
          tr('Could not read the photo', 'फ़ोटो पढ़ी नहीं जा सकी'),
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        Text(
          _error ?? '',
          textAlign: TextAlign.center,
          style: const TextStyle(color: Ks.muted),
        ),
        const SizedBox(height: 20),
        if (_bytes != null) ...[
          if (!typeFirst)
            FilledButton.icon(
              onPressed: _upload,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Retry', 'दोबारा कोशिश करें')),
            )
          else
            OutlinedButton.icon(
              onPressed: _upload,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Retry', 'दोबारा कोशिश करें')),
            ),
          const SizedBox(height: 10),
        ],
        typeBtn,
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => setState(() => _stage = _Stage.pick),
          child: Text(tr('Choose another photo', 'दूसरी फ़ोटो चुनें')),
        ),
      ],
    );
  }

  Widget _typingView() => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Text(
        tr('Type the topics', 'विषय टाइप करें'),
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: 6),
      Text(
        tr(
          'One topic per line. To group them, write "Chapter: topic"; the lines after it stay in that chapter.',
          'हर पंक्ति में एक विषय। समूह के लिए "अध्याय: विषय" लिखें; उसके बाद की पंक्तियाँ उसी अध्याय में रहेंगी।',
        ),
        style: const TextStyle(color: Ks.muted),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _typeCtl,
        minLines: 8,
        maxLines: 14,
        keyboardType: TextInputType.multiline,
        textCapitalization: TextCapitalization.sentences,
        decoration: InputDecoration(
          hintText: tr(
            'Numbers to 20: Counting objects\nAddition without carrying\nShapes around us: Circle and square',
            'संख्याएँ 20 तक: वस्तुएँ गिनना\nबिना हासिल का जोड़\nआकार: गोला और चौकोर',
          ),
        ),
      ),
      const SizedBox(height: 16),
      FilledButton(
        onPressed: _reviewTyped,
        child: Text(tr('Review the list', 'सूची देखें')),
      ),
      const SizedBox(height: 8),
      TextButton(
        onPressed: () => setState(() => _stage = _Stage.pick),
        child: Text(tr('Use a photo instead', 'फ़ोटो से जोड़ें')),
      ),
    ],
  );

  Widget _reviewView() {
    final n = _topicCount;
    var matched = 0;
    for (final c in _chaps) {
      matched += c.rows.where((r) => r.matched).length;
    }
    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            children: [
              _proposeNote(),
              if (_note != null && _note!.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  _note!,
                  style: const TextStyle(color: Ks.muted, fontSize: 13.5),
                ),
              ],
              const SizedBox(height: 12),
              Text(
                tr(
                  '$n topics: $matched match lessons already in Kaksha Saathi, ${n - matched} are new.',
                  '$n विषय: $matched कक्षा साथी के मौजूदा पाठों से मिलते हैं, ${n - matched} नए हैं।',
                ),
                style: const TextStyle(fontSize: 14.5, color: Ks.ink),
              ),
              if (widget.confirmed && _existingCount > 0)
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _keep,
                  onChanged: _saving ? null : (v) => setState(() => _keep = v),
                  title: Text(
                    tr(
                      'Keep my current $_existingCount topics',
                      'मेरे मौजूदा $_existingCount विषय रखें',
                    ),
                  ),
                  subtitle: Text(
                    _keep
                        ? tr(
                            'These are added after them.',
                            'ये उनके बाद जुड़ेंगे।',
                          )
                        : tr(
                            'The list below replaces the current syllabus.',
                            'नीचे की सूची मौजूदा पाठ्यक्रम की जगह लेगी।',
                          ),
                  ),
                ),
              const SizedBox(height: 8),
              for (final c in _chaps) _chapterCard(c),
              const SizedBox(height: 4),
              TextButton.icon(
                onPressed: _saving
                    ? null
                    : () => setState(
                        () => _chaps.add(_Chap('')..rows.add(_Row(text: ''))),
                      ),
                icon: const Icon(Icons.add_rounded),
                label: Text(tr('Add a chapter', 'अध्याय जोड़ें')),
              ),
            ],
          ),
        ),
        Material(
          elevation: 6,
          color: Ks.paper,
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (_saveError != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        _saveError!,
                        style: const TextStyle(color: Ks.rose, fontSize: 14.5),
                      ),
                    ),
                  FilledButton.icon(
                    onPressed: (_saving || n == 0) ? null : _confirm,
                    icon: _saving
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2.5,
                              color: Colors.white,
                            ),
                          )
                        : Icon(
                            _saveError == null
                                ? Icons.check_rounded
                                : Icons.refresh_rounded,
                          ),
                    label: Text(
                      _saveError == null
                          ? tr(
                              'Confirm syllabus ($n topics)',
                              'पक्का करें ($n विषय)',
                            )
                          : tr('Try again', 'दोबारा कोशिश करें'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _chapterCard(_Chap chap) {
    return Padding(
      key: ObjectKey(chap),
      padding: const EdgeInsets.only(bottom: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 10, 4, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: chap.name,
                      enabled: !_saving,
                      onChanged: (_) => setState(() {}),
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 16,
                      ),
                      decoration: InputDecoration(
                        labelText: tr('Chapter', 'अध्याय'),
                        isDense: true,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: tr('Remove chapter', 'अध्याय हटाएँ'),
                    onPressed: _saving
                        ? null
                        : () => setState(() => _chaps.remove(chap)),
                    icon: const Icon(Icons.delete_outline_rounded),
                    color: Ks.muted,
                  ),
                ],
              ),
              const SizedBox(height: 8),
              for (final r in List.of(chap.rows)) _rowTile(chap, r),
              TextButton.icon(
                onPressed: _saving
                    ? null
                    : () => setState(() => chap.rows.add(_Row(text: ''))),
                icon: const Icon(Icons.add_rounded, size: 20),
                label: Text(tr('Add a topic', 'विषय जोड़ें')),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _rowTile(_Chap chap, _Row r) {
    return Padding(
      key: ObjectKey(r),
      padding: const EdgeInsets.only(bottom: 10, right: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (r.matched)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      r.matchTitle ?? '',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Ks.ink,
                      ),
                    ),
                  )
                else
                  TextField(
                    controller: r.ctl,
                    enabled: !_saving,
                    onChanged: (_) => setState(() {}),
                    minLines: 1,
                    maxLines: 3,
                    decoration: InputDecoration(
                      isDense: true,
                      hintText: tr('Topic name', 'विषय का नाम'),
                    ),
                  ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    if (r.matched)
                      SylTag(
                        tr(
                          'Matches an existing lesson',
                          'मौजूदा पाठ से मिलता है',
                        ),
                        icon: Icons.link_rounded,
                        bg: Ks.accentSoft,
                        fg: Ks.accent,
                      )
                    else
                      SylTag(
                        tr('New custom topic', 'नया अपना विषय'),
                        icon: Icons.edit_note_rounded,
                        bg: Ks.amberSoft,
                        fg: SylColors.amberText,
                      ),
                    if (r.matched)
                      InkWell(
                        onTap: _saving
                            ? null
                            : () => setState(() {
                                r.ctl.text = r.matchTitle ?? '';
                                r.checkpointId = null;
                              }),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Text(
                            tr('Make it a new topic', 'नया विषय बनाएँ'),
                            style: const TextStyle(
                              fontSize: 13.5,
                              color: Ks.accent,
                              fontWeight: FontWeight.w600,
                              decoration: TextDecoration.underline,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: tr('Remove this line', 'यह पंक्ति हटाएँ'),
            onPressed: _saving
                ? null
                : () => setState(() => chap.rows.remove(r)),
            icon: const Icon(Icons.close_rounded),
            color: Ks.muted,
          ),
        ],
      ),
    );
  }
}
