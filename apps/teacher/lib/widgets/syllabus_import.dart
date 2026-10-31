import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';
import '../l10n.dart';
import '../record_audio.dart';
import '../theme.dart';
import 'syllabus_widgets.dart';

/// Import the syllabus from the textbook (cover + index page photos and/or the book's name), or
/// from typed lines.
///
/// The AI only proposes: the draft is shown as an editable list (rename, drop, unlink from a
/// matched lesson), can be corrected by voice or a typed sentence, and nothing is saved until the
/// teacher presses Confirm. Pops `true` once the syllabus was saved.
class SylImportScreen extends StatefulWidget {
  const SylImportScreen({
    super.key,
    required this.classId,
    required this.subject,
    required this.existingChapters,
    required this.confirmed,
    this.grade,
  });
  final int classId;
  final String subject;

  /// The class's grade, used as the book's class by default; looked up from `/v1/classes` if null.
  final int? grade;

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

  /// From the book flow: true when the topics were not read off a photographed page, and where
  /// they came from instead (`page` / `book_knowledge` / `web` / `template`).
  bool inferred = false;
  String basis = 'page';
}

/// At most this many photos (cover + index pages) go to the book reader.
const _maxPhotos = 6;

final _devanagari = RegExp(r'[ऀ-ॿ]');

class _SylImportScreenState extends State<SylImportScreen> {
  _Stage _stage = _Stage.pick;
  String? _error;
  int _errorStatus = 0;
  final List<(Uint8List, String)> _photos = []; // (bytes, filename)
  final _bookCtl = TextEditingController();
  final _otherBoardCtl = TextEditingController();
  int? _grade;
  String? _board; // NCERT / SCERT / other; none = let the reader identify it
  Map<String, dynamic>? _book; // what the reader identified
  String _source = 'photo';
  String? _note;
  final Recorder _rec = Recorder();
  bool _recording = false;
  bool _revising = false;
  String? _heard; // what the last correction was understood as
  final _fixCtl = TextEditingController();
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

  /// Editing is locked while saving or while a correction is being applied.
  bool get _busy => _saving || _revising;

  bool get _canMap => _photos.isNotEmpty || _bookCtl.text.trim().isNotEmpty;

  @override
  void initState() {
    super.initState();
    _grade = widget.grade;
    if (_grade == null) _loadGrade();
  }

  Future<void> _loadGrade() async {
    try {
      for (final c in sylMaps(await Api.i.classes())) {
        final g = sylInt(c['grade']);
        if (sylInt(c['id']) == widget.classId && g >= 1 && g <= 8) {
          if (mounted && _grade == null) setState(() => _grade = g);
          return;
        }
      }
    } catch (_) {
      // The teacher picks the class.
    }
  }

  @override
  void dispose() {
    _typeCtl.dispose();
    _bookCtl.dispose();
    _otherBoardCtl.dispose();
    _fixCtl.dispose();
    _rec.dispose();
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

  // ---- step 1: book (photos and/or name) -> draft
  Future<void> _addPhotos(ImageSource src) async {
    final room = _maxPhotos - _photos.length;
    if (room <= 0) return;
    try {
      final picker = ImagePicker();
      final files = src == ImageSource.gallery && room > 1
          ? await picker.pickMultiImage(
              maxWidth: 1800,
              imageQuality: 85,
              limit: room,
            )
          : [
              ?await picker.pickImage(
                source: src,
                maxWidth: 1800,
                imageQuality: 85,
              ),
            ];
      final added = <(Uint8List, String)>[];
      for (final f in files.take(room)) {
        added.add((
          await f.readAsBytes(),
          f.name.isEmpty
              ? 'page${_photos.length + added.length + 1}.jpg'
              : f.name,
        ));
      }
      if (!mounted || added.isEmpty) return;
      setState(() => _photos.addAll(added));
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

  /// "NCERT" / "SCERT" / "Other" and, for Other, what the teacher typed as the publisher.
  (String, String) _boardChoice() => switch (_board) {
    'NCERT' => ('NCERT', 'NCERT'),
    'SCERT' => ('SCERT', ''),
    'other' => ('Other', _otherBoardCtl.text.trim()),
    _ => ('', ''),
  };

  /// The book as the teacher described it, filled in with what the reader identified.
  Map<String, dynamic> _bookJson() {
    final got = _book ?? const <String, dynamic>{};
    final (board, publisher) = _boardChoice();
    String or(String mine, Object? theirs) =>
        mine.isNotEmpty ? mine : (theirs ?? '').toString().trim();
    return {
      'title': or(_bookCtl.text.trim(), got['title']),
      'grade': _grade ?? (got['grade'] is int ? got['grade'] : null),
      'board': or(board, got['board']),
      'publisher': or(publisher, got['publisher']),
    };
  }

  /// The current (edited) review state in the book contract's chapter shape.
  List<Map<String, dynamic>> _chaptersJson() => [
    for (final c in _chaps)
      {
        'title': c.name.text.trim(),
        'inferred': c.inferred,
        'basis': c.basis,
        'topics': [
          for (final r in c.rows)
            if (r.matched || r.ctl.text.trim().isNotEmpty)
              {
                'text': r.matched ? (r.matchTitle ?? '') : r.ctl.text.trim(),
                'checkpoint_id': r.checkpointId,
              },
        ],
      },
  ];

  Future<void> _mapBook() async {
    if (!_canMap) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _stage = _Stage.uploading;
      _error = null;
    });
    final (board, publisher) = _boardChoice();
    final title = _bookCtl.text.trim();
    try {
      var fromBook = true;
      Map<String, dynamic> m;
      try {
        final r = await Api.i.postMultipartFiles(
          '/v1/classes/${widget.classId}/books/map',
          fields: {
            'subject': widget.subject,
            if (title.isNotEmpty) 'book_title': title,
            if (board.isNotEmpty) 'board': board,
            if (publisher.isNotEmpty) 'publisher': publisher,
            if (_grade != null) 'book_grade': '$_grade',
          },
          files: [for (final (bytes, name) in _photos) ('images', bytes, name)],
        );
        m = (r as Map).cast<String, dynamic>();
      } on ApiError catch (e) {
        // A server without the book reader: read the last photo as a single index page.
        if ((e.status != 404 && e.status != 405) || _photos.isEmpty) rethrow;
        final (bytes, name) = _photos.last;
        final r = await Api.i.postMultipartFiles(
          '/v1/classes/${widget.classId}/roadmap/draft',
          fields: {'subject': widget.subject},
          files: [('image', bytes, name)],
        );
        m = (r as Map).cast<String, dynamic>();
        fromBook = false;
      }
      final items = sylMaps(m['items']);
      if (items.isEmpty) {
        _fail(
          (m['note'] as String?) ??
              tr(
                'The chapters could not be read from these photos.',
                'इन फ़ोटो से अध्याय नहीं पढ़े जा सके।',
              ),
          422,
        );
        return;
      }
      await _loadTitles(items);
      if (!mounted) return;
      _fillFromDraft(items);
      _applyChapterMeta(sylMaps(m['chapters']));
      setState(() {
        _source = fromBook ? 'book' : 'photo';
        _book = m['book'] is Map
            ? (m['book'] as Map).cast<String, dynamic>()
            : null;
        _note = m['status'] == 'ready' ? null : m['note'] as String?;
        _heard = null;
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

  /// Marks chapters whose topics were inferred (matched to the response's chapters by title).
  void _applyChapterMeta(List<Map<String, dynamic>> chapters) {
    final byTitle = {
      for (final c in chapters) (c['title'] ?? '').toString().trim(): c,
    };
    for (final chap in _chaps) {
      final c = byTitle[chap.name.text.trim()];
      chap.inferred = c?['inferred'] == true;
      chap.basis = (c?['basis'] ?? 'page').toString();
    }
  }

  // ---- step 1b: correct the draft by voice or a typed sentence
  Future<void> _toggleRecord() async {
    if (!_recording) {
      final ok = await _rec.start();
      if (!mounted) return;
      if (!ok) {
        _toast(
          tr(
            'Mic not available: type the correction instead.',
            'माइक उपलब्ध नहीं: सुधार लिखकर बताएँ।',
          ),
        );
        return;
      }
      setState(() => _recording = true);
    } else {
      final bytes = await _rec.stop();
      if (!mounted) return;
      setState(() => _recording = false);
      if (bytes == null || bytes.isEmpty) {
        _toast(tr('Recording was empty', 'रिकॉर्डिंग खाली रही'));
        return;
      }
      await _revise(audio: bytes);
    }
  }

  /// Sends the CURRENT edited list plus the correction; the reply replaces the list. On any
  /// failure the list stays exactly as it was.
  Future<void> _revise({Uint8List? audio}) async {
    final typed = _fixCtl.text.trim();
    if (audio == null && typed.isEmpty) return;
    FocusScope.of(context).unfocus();
    setState(() => _revising = true);
    try {
      final r = await Api.i.postMultipartFiles(
        '/v1/classes/${widget.classId}/books/map/revise',
        fields: {
          'subject': widget.subject,
          'draft': jsonEncode({
            'book': {...?_book, ..._bookJson()},
            'chapters': _chaptersJson(),
          }),
          if (audio == null) 'transcript': typed,
        },
        files: [if (audio != null) ('audio', audio, 'correction.wav')],
      );
      final m = (r as Map).cast<String, dynamic>();
      final heard = (m['heard'] ?? '').toString().trim();
      final items = sylMaps(m['items']);
      if (items.isEmpty) {
        if (!mounted) return;
        setState(() => _heard = heard.isEmpty ? null : heard);
        _toast(
          (m['note'] as String?) ??
              tr(
                'Could not apply that correction. Your list is unchanged.',
                'यह सुधार लागू नहीं हो सका। आपकी सूची जैसी थी वैसी है।',
              ),
        );
        return;
      }
      await _loadTitles(items);
      if (!mounted) return;
      setState(() {
        _fillFromDraft(items, disposeLater: true);
        _applyChapterMeta(sylMaps(m['chapters']));
        if (m['book'] is Map) {
          _book = (m['book'] as Map).cast<String, dynamic>();
        }
        _note = m['status'] == 'ready' ? null : m['note'] as String?;
        _heard = heard.isNotEmpty ? heard : (audio == null ? typed : null);
        _fixCtl.clear();
        _saveError = null;
      });
    } on ApiError catch (e) {
      _toast(e.message);
    } catch (_) {
      _toast(
        tr(
          'Could not apply that correction. Your list is unchanged.',
          'यह सुधार लागू नहीं हो सका। आपकी सूची जैसी थी वैसी है।',
        ),
      );
    } finally {
      if (mounted) setState(() => _revising = false);
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
    if (_titles.isNotEmpty || !items.any((i) => i['checkpoint_id'] != null)) {
      return;
    }
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
  void _fillFromDraft(
    List<Map<String, dynamic>> items, {
    bool disposeLater = false,
  }) {
    _resetChapters(disposeLater: disposeLater);
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

  /// With [disposeLater] the old controllers are disposed after the next frame, because the
  /// review list on screen still holds them until it rebuilds.
  void _resetChapters({bool disposeLater = false}) {
    final old = List.of(_chaps);
    _chaps.clear();
    void dispose() {
      for (final c in old) {
        c.name.dispose();
        for (final r in c.rows) {
          r.ctl.dispose();
        }
      }
    }

    if (disposeLater) {
      WidgetsBinding.instance.addPostFrameCallback((_) => dispose());
    } else {
      dispose();
    }
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
        if (_source == 'book')
          'book': {..._bookJson(), 'chapters': _chaptersJson()},
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
            label: tr(
              'Reading the book… this can take a minute.',
              'किताब पढ़ रहे हैं… इसमें एक मिनट लग सकता है।',
            ),
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

  Widget _label(String text) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Text(
      text,
      style: const TextStyle(fontWeight: FontWeight.w700, color: Ks.ink),
    ),
  );

  Widget _pickView() {
    final full = _photos.length >= _maxPhotos;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          tr('Take photos of your textbook.', 'अपनी किताब की फ़ोटो लें।'),
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 6),
        Text(
          tr(
            'Add the cover and every index page. Keep each page in the frame, in good light.',
            'कवर और विषय-सूची के सभी पन्ने जोड़ें। हर पन्ना फ़्रेम में रखें, अच्छी रोशनी में।',
          ),
          style: const TextStyle(color: Ks.muted),
        ),
        const SizedBox(height: 14),
        _photoStrip(),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: full ? null : () => _addPhotos(ImageSource.camera),
                icon: const Icon(Icons.photo_camera_rounded),
                label: Text(tr('Camera', 'कैमरा')),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: full ? null : () => _addPhotos(ImageSource.gallery),
                icon: const Icon(Icons.photo_library_rounded),
                label: Text(tr('Gallery', 'गैलरी')),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          trf(
            '{photosCount} of {maxPhotos} photos',
            '{maxPhotos} में से {photosCount} फ़ोटो', {'photosCount': _photos.length, 'maxPhotos': _maxPhotos},
          ),
          style: const TextStyle(color: Ks.muted, fontSize: 13.5),
        ),
        const SizedBox(height: 18),
        _label(tr('Book name', 'किताब का नाम')),
        TextField(
          controller: _bookCtl,
          onChanged: (_) => setState(() {}),
          textCapitalization: TextCapitalization.words,
          decoration: InputDecoration(
            hintText: tr('e.g. Math-Magic', 'जैसे: गणित का जादू'),
          ),
        ),
        const SizedBox(height: 16),
        _label(tr('Class', 'कक्षा')),
        Wrap(
          spacing: 8,
          runSpacing: 6,
          children: [
            for (var g = 1; g <= 8; g++)
              ChoiceChip(
                label: Text('$g', style: const TextStyle(fontSize: 16)),
                selected: _grade == g,
                onSelected: (_) => setState(() => _grade = g),
              ),
          ],
        ),
        const SizedBox(height: 16),
        _label(tr('Board or publisher', 'बोर्ड या प्रकाशक')),
        Wrap(
          spacing: 8,
          runSpacing: 6,
          children: [
            for (final (key, label) in [
              ('NCERT', 'NCERT'),
              ('SCERT', tr('State board (SCERT)', 'राज्य बोर्ड (SCERT)')),
              ('other', tr('Other', 'अन्य')),
            ])
              ChoiceChip(
                label: Text(label, style: const TextStyle(fontSize: 15)),
                selected: _board == key,
                onSelected: (on) => setState(() => _board = on ? key : null),
              ),
          ],
        ),
        if (_board == 'other') ...[
          const SizedBox(height: 10),
          TextField(
            controller: _otherBoardCtl,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(
              hintText: tr(
                'Board or publisher name',
                'बोर्ड या प्रकाशक का नाम',
              ),
            ),
          ),
        ],
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: _canMap ? _mapBook : null,
          icon: const Icon(Icons.auto_awesome_rounded),
          label: Text(tr('Map chapters', 'अध्याय बनाएँ')),
        ),
        if (!_canMap)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              tr(
                'Add a photo or the book name first.',
                'पहले एक फ़ोटो या किताब का नाम जोड़ें।',
              ),
              textAlign: TextAlign.center,
              style: const TextStyle(color: Ks.muted, fontSize: 13.5),
            ),
          ),
        const SizedBox(height: 14),
        _proposeNote(),
        const SizedBox(height: 10),
        TextButton.icon(
          onPressed: () => setState(() => _stage = _Stage.typing),
          icon: const Icon(Icons.keyboard_rounded),
          label: Text(
            tr('Type the topics instead', 'इसके बजाय विषय टाइप करें'),
          ),
        ),
      ],
    );
  }

  Widget _photoStrip() {
    if (_photos.isEmpty) {
      return Container(
        height: 112,
        decoration: BoxDecoration(
          color: Ks.card,
          border: Border.all(color: Ks.line),
          borderRadius: BorderRadius.circular(14),
        ),
        alignment: Alignment.center,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.menu_book_rounded, color: Ks.muted, size: 32),
            const SizedBox(height: 6),
            Text(
              tr('No photos yet', 'अभी कोई फ़ोटो नहीं'),
              style: const TextStyle(color: Ks.muted),
            ),
          ],
        ),
      );
    }
    return SizedBox(
      height: 112,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _photos.length,
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemBuilder: (_, i) => Stack(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.memory(
                _photos[i].$1,
                width: 84,
                height: 112,
                fit: BoxFit.cover,
                cacheWidth: 252,
              ),
            ),
            Positioned(
              left: 4,
              bottom: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${i + 1}',
                  style: const TextStyle(color: Colors.white, fontSize: 12.5),
                ),
              ),
            ),
            Positioned(
              top: 2,
              right: 2,
              child: Material(
                color: Colors.black54,
                shape: const CircleBorder(),
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: () => setState(() => _photos.removeAt(i)),
                  child: Padding(
                    padding: const EdgeInsets.all(7),
                    child: Icon(
                      Icons.close_rounded,
                      size: 20,
                      color: Colors.white,
                      semanticLabel: tr('Remove photo', 'फ़ोटो हटाएँ'),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

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
          tr('Could not map the chapters', 'अध्याय नहीं बन सके'),
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
        if (_canMap) ...[
          if (!typeFirst)
            FilledButton.icon(
              onPressed: _mapBook,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Retry', 'दोबारा कोशिश करें')),
            )
          else
            OutlinedButton.icon(
              onPressed: _mapBook,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(tr('Retry', 'दोबारा कोशिश करें')),
            ),
          const SizedBox(height: 10),
        ],
        typeBtn,
        const SizedBox(height: 10),
        TextButton(
          onPressed: () => setState(() => _stage = _Stage.pick),
          child: Text(
            tr(
              'Change the photos or book details',
              'फ़ोटो या किताब की जानकारी बदलें',
            ),
          ),
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
              if (_source == 'book') ...[
                _bookHeader(),
                const SizedBox(height: 10),
              ],
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
                trf(
                  '{n} topics: {matched} match lessons already in Kaksha Saathi, {n2} are new.',
                  '{n} विषय: {matched} कक्षा साथी के मौजूदा पाठों से मिलते हैं, {n2} नए हैं।', {'n': n, 'matched': matched, 'n2': n - matched},
                ),
                style: const TextStyle(fontSize: 14.5, color: Ks.ink),
              ),
              if (widget.confirmed && _existingCount > 0)
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _keep,
                  onChanged: _busy ? null : (v) => setState(() => _keep = v),
                  title: Text(
                    trf(
                      'Keep my current {existingCount} topics',
                      'मेरे मौजूदा {existingCount} विषय रखें', {'existingCount': _existingCount},
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
              if (_source == 'book') ...[
                _correctionCard(),
                const SizedBox(height: 12),
              ],
              for (final c in _chaps) _chapterCard(c),
              const SizedBox(height: 4),
              TextButton.icon(
                onPressed: _busy
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
                    onPressed: (_busy || _recording || n == 0)
                        ? null
                        : _confirm,
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
                          ? trf(
                              'Confirm syllabus ({n} topics)',
                              'पक्का करें ({n} विषय)', {'n': n},
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

  /// Badge for a chapter whose topics were not read off a photographed page.
  String? _inferredText(_Chap chap) {
    if (!chap.inferred && chap.basis != 'template') return null;
    return switch (chap.basis) {
      'book_knowledge' => tr(
        'Topics guessed from the book, please check',
        'विषय किताब के अनुमान से, कृपया जाँचें',
      ),
      'web' => tr(
        'Topics found online: please check',
        'विषय इंटरनेट से मिले, कृपया जाँचें',
      ),
      'template' => tr(
        'Not read from the book: the usual class syllabus, please check',
        'किताब से नहीं पढ़ा: कक्षा का सामान्य पाठ्यक्रम, कृपया जाँचें',
      ),
      _ => tr('Please check these topics', 'कृपया ये विषय जाँचें'),
    };
  }

  /// Title · class · board of the book the draft came from.
  Widget _bookHeader() {
    final b = _bookJson();
    final title = (b['title'] as String).isEmpty
        ? tr('Your textbook', 'आपकी किताब')
        : b['title'] as String;
    final board = b['board'] == 'Other' && (b['publisher'] as String).isNotEmpty
        ? b['publisher'] as String
        : b['board'] as String;
    final parts = [
      if (b['grade'] != null) trf('Class {grade}', 'कक्षा {grade}', {'grade': b['grade']}),
      if (board.isNotEmpty) board,
    ];
    return Row(
      children: [
        const Icon(Icons.menu_book_rounded, color: Ks.accent, size: 28),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                  color: Ks.ink,
                ),
              ),
              if (parts.isNotEmpty)
                Text(
                  parts.join(' · '),
                  style: const TextStyle(fontSize: 14, color: Ks.muted),
                ),
            ],
          ),
        ),
      ],
    );
  }

  /// Fix the draft by speaking (or typing) a correction; hand edits below still work after it.
  Widget _correctionCard() {
    final canSend = !_busy && !_recording && _fixCtl.text.trim().isNotEmpty;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Ks.card,
        border: Border.all(color: Ks.line),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              InkWell(
                onTap: _busy ? null : _toggleRecord,
                customBorder: const CircleBorder(),
                child: Container(
                  width: 60,
                  height: 60,
                  decoration: BoxDecoration(
                    color: _busy ? Ks.line : (_recording ? Ks.rose : Ks.accent),
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    _recording ? Icons.stop_rounded : Icons.mic_rounded,
                    color: Colors.white,
                    size: 32,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tr('Explain a correction', 'सुधार बोलकर बताएँ'),
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: Ks.ink,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _recording
                          ? tr(
                              'Listening… tap again to stop.',
                              'सुन रहे हैं… रोकने के लिए फिर दबाएँ।',
                            )
                          : tr(
                              'e.g. "Chapter 3 also has subtraction with borrowing"',
                              'जैसे: "अध्याय 3 में उधार वाला घटाव भी है"',
                            ),
                      style: TextStyle(
                        fontSize: 13.5,
                        color: _recording ? Ks.rose : Ks.muted,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (_revising) ...[
            const SizedBox(height: 10),
            const LinearProgressIndicator(minHeight: 3, color: Ks.accent),
            const SizedBox(height: 4),
            Text(
              tr('Updating the list…', 'सूची बदल रहे हैं…'),
              style: const TextStyle(color: Ks.muted, fontSize: 13.5),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _fixCtl,
                  enabled: !_busy && !_recording,
                  onChanged: (_) => setState(() {}),
                  minLines: 1,
                  maxLines: 3,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: InputDecoration(
                    isDense: true,
                    hintText: tr('Type a correction', 'सुधार लिखें'),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                tooltip: tr('Send correction', 'सुधार भेजें'),
                onPressed: canSend ? () => _revise() : null,
                iconSize: 24,
                style: IconButton.styleFrom(minimumSize: const Size(52, 52)),
                icon: const Icon(Icons.send_rounded),
              ),
            ],
          ),
          if (_heard != null && _heard!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              trf('Heard: "{heard}"', 'सुना: "{heard}"', {'heard': _heard}),
              style: const TextStyle(
                color: Ks.muted,
                fontSize: 13.5,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _chapterCard(_Chap chap) {
    return Padding(
      key: ObjectKey(chap),
      padding: const EdgeInsets.only(bottom: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(12, 10, 4, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: chap.name,
                      enabled: !_busy,
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
                    onPressed: _busy
                        ? null
                        : () => setState(() => _chaps.remove(chap)),
                    icon: const Icon(Icons.delete_outline_rounded),
                    color: Ks.muted,
                  ),
                ],
              ),
              if (_inferredText(chap) case final t?)
                Padding(
                  padding: const EdgeInsetsDirectional.only(top: 8, end: 8),
                  child: SylTag(
                    t,
                    icon: chap.basis == 'web'
                        ? Icons.travel_explore_rounded
                        : Icons.help_outline_rounded,
                    bg: Ks.amberSoft,
                    fg: SylColors.amberText,
                  ),
                ),
              const SizedBox(height: 8),
              for (final r in List.of(chap.rows)) _rowTile(chap, r),
              TextButton.icon(
                onPressed: _busy
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
      padding: const EdgeInsetsDirectional.only(bottom: 10, end: 8),
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
                    enabled: !_busy,
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
                        onTap: _busy
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
            onPressed: _busy ? null : () => setState(() => chap.rows.remove(r)),
            icon: const Icon(Icons.close_rounded),
            color: Ks.muted,
          ),
        ],
      ),
    );
  }
}
