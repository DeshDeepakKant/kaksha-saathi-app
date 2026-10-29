// Layout and permission tests for the voice session screen (VoiceSessionScreen).
//
// Layout: the item the child reads must be fully visible and never overlapped by the mic panel,
// the help panels, the transcript or the control bar, at 360x640 .. 411x900 dp, text scale 1.0
// and 1.3, in Hindi and English. Permission: a slow system dialog is not a denial, and the
// screen re-checks the permission when the app resumes.
//
// Seams as in e2e_voice_session_screen_test.dart: HTTP is a MockClient, the `record` plugin and
// flutter_tts are faked at the platform-channel level.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:kaksha_parent/l10n.dart';
import 'package:kaksha_parent/screens/voice_session_screen.dart';
import 'package:kaksha_parent/theme.dart';
import 'package:kaksha_parent/voice_recorder.dart';
import 'package:kaksha_parent/widgets/voice_item_view.dart';
import 'package:kaksha_parent/widgets/voice_mic.dart';
import 'package:kaksha_parent/widgets/voice_transcript.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ---- items ------------------------------------------------------------------------------------

Map<String, dynamic> _item(String kind, Map<String, dynamic> display) => {
  'id': 'i1',
  'stage': 'letter',
  'kind': kind,
  'lang': 'hi',
  'checkpoint_id': null,
  'prompt': 'p',
  'display': display,
  'max_record_s': 5,
  'difficulty': 1,
  'source': 'bank',
};

const _para =
    'एक छोटा सा गाँव था। वहाँ एक लड़की रहती थी, उसका नाम गीता था। हर सुबह वह नदी से पानी लाती थी। '
    'रास्ते में एक बड़ा पेड़ था, जिसके नीचे वह थोड़ी देर बैठती थी। पेड़ पर चिड़ियाँ गाना गाती थीं। '
    'गीता को चिड़ियाँ बहुत पसंद थीं। वह रोज़ उनके लिए थोड़े दाने लाती थी।';

final _items = <String, Map<String, dynamic>>{
  'letter': _item('read_letter', {'text': 'S'}),
  'word': _item('say_sound', {'text': 'sun'}),
  'paragraph': _item('read_paragraph', {'text': _para}),
  'build': _item('build_word', {
    'tiles': ['क', 'म', 'ल'],
  }),
  'sentence': _item('make_sentence', {
    'words': ['गीता', 'नदी', 'पानी'],
  }),
};

const _tutor =
    'Hello कविता! Today we will play a reading game together. Listen to this word, sun. '
    'What sound does sun start with?';

Map<String, dynamic> _session(Map<String, dynamic> item) => {
  'id': 7,
  'lang': 'hi',
  'status': 'active',
  'elapsed_s': 58,
  'remaining_s': 1742,
  'target_minutes': 30,
  'stage': 'letter',
  'item': item,
  'attempt': 1,
  'attempts_left': 5,
  'done': false,
  'tutor': {'text': _tutor, 'lang': 'hi'},
  'safety_flag': null,
};

Map<String, dynamic> _turn(
  Map<String, dynamic> item, {
  String verdict = 'wrong',
}) => {
  'verdict': verdict,
  'score': 0.2,
  'heard': 'x',
  'words': <dynamic>[],
  'errors': <String>[],
  'attempt': 1,
  'attempts_left': 4,
  'tutor': {'text': 'Try again.', 'lang': 'hi'},
  'next_item': item,
  'stage': 'letter',
  'stage_changed': false,
  'elapsed_s': 70,
  'remaining_s': 1730,
  'done': false,
  'transcript_append': [
    {'role': 'child', 'text': 'x', 'verdict': verdict, 'words': <dynamic>[]},
    {'role': 'tutor', 'text': 'Try again.'},
  ],
};

// ---- fakes ------------------------------------------------------------------------------------

/// Stands in for the `record` plugin (via VoiceRecorder.recorderFactory): the permission answer
/// can be held back like the system dialog, and the PCM stream is fed by the test.
class _Mic implements AudioRecorder {
  bool granted = true;
  Completer<bool>?
  permGate; // hold hasPermission open (system dialog on screen)
  int starts = 0;
  int permCalls = 0;
  int softChecks = 0; // hasPermission(request: false)
  StreamController<Uint8List>? _ctl;

  bool get listening => _ctl?.hasListener ?? false;

  @override
  Future<bool> hasPermission({bool request = true}) async {
    if (!request) {
      softChecks++;
      return granted;
    }
    permCalls++;
    if (permGate != null) return permGate!.future;
    return granted;
  }

  @override
  Future<Stream<Uint8List>> startStream(RecordConfig config) async {
    starts++;
    // onCancel returns a future made inside the test zone: a plain cancel() resolves through
    // Future.nullFuture (root zone), which fake-async tests only reach at the very end.
    _ctl = StreamController<Uint8List>(onCancel: () async {});
    return _ctl!.stream;
  }

  @override
  Future<String?> stop() async {
    _ctl = null; // left open: VoiceRecorder cancels its subscription itself
    return null;
  }

  @override
  Future<void> dispose() async {}

  @override
  dynamic noSuchMethod(Invocation invocation) =>
      throw UnimplementedError('${invocation.memberName}');

  static Uint8List _pcm(int ms, int amp) {
    final n = 16 * ms;
    final d = ByteData(n * 2);
    for (var i = 0; i < n; i++) {
      d.setInt16(i * 2, i.isEven ? amp : -amp, Endian.little);
    }
    return d.buffer.asUint8List();
  }

  void say() {
    void push(int ms, int amp) {
      for (var i = 0; i < ms ~/ 100; i++) {
        _ctl!.add(_pcm(100, amp));
      }
    }

    push(300, 0);
    push(500, 9000);
    push(1800, 0);
  }
}

void _installTts() {
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(const MethodChannel('flutter_tts'), (
        call,
      ) async {
        if (call.method == 'isLanguageAvailable') return true;
        return 1;
      });
}

Future<void> _loadFonts() async {
  final flutter =
      Platform.environment['FLUTTER_ROOT'] ?? '/home/anya/.local/flutter';
  final art = '$flutter/bin/cache/artifacts/material_fonts';
  for (final e in {
    'Roboto': ['$art/Roboto-Regular.ttf', '$art/Roboto-Bold.ttf'],
    'NotoSansDevanagari': [
      '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf',
      '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf',
    ],
  }.entries) {
    final l = FontLoader(e.key);
    var any = false;
    for (final path in e.value) {
      final f = File(path);
      if (f.existsSync()) {
        l.addFont(Future.value(ByteData.sublistView(f.readAsBytesSync())));
        any = true;
      }
    }
    if (any) await l.load();
  }
}

// ---- rig --------------------------------------------------------------------------------------

class _Host extends StatelessWidget {
  const _Host();
  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: ElevatedButton(
        onPressed: () => Navigator.of(
          context,
        ).push(MaterialPageRoute(builder: (_) => const VoiceSessionScreen())),
        child: const Text('open'),
      ),
    ),
  );
}

class _Rig {
  _Rig(this.t, this.lang, this.size, this.scale, String itemKey)
    : item = _items[itemKey]!;
  final WidgetTester t;
  final String lang;
  final Size size;
  final double scale;
  final Map<String, dynamic> item;
  final mic = _Mic();
  Completer<Map<String, dynamic>>? turnGate;
  Map<String, dynamic>? turnReply;

  Future<http.Response> _handle(http.Request req) async {
    http.Response js(Object o) => http.Response.bytes(
      utf8.encode(jsonEncode(o)),
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
    final path = req.url.path;
    if (path.endsWith('/turn')) {
      final r = turnGate != null
          ? await turnGate!.future
          : (turnReply ?? _turn(item));
      return js(r);
    }
    if (path.endsWith('/end')) return js({});
    return js(_session(item));
  }

  Future<void> run(Future<void> Function() body) async {
    SharedPreferences.setMockInitialValues({});
    Lang.code.value = lang;
    VoiceRecorder.recorderFactory = () => mic;
    addTearDown(() => VoiceRecorder.recorderFactory = AudioRecorder.new);
    _installTts();
    t.view.physicalSize = size;
    t.view.devicePixelRatio = 1;
    t.view.padding = const FakeViewPadding(top: 24, bottom: 16);
    t.view.viewPadding = const FakeViewPadding(top: 24, bottom: 16);
    addTearDown(t.view.reset);
    await http.runWithClient(() async {
      await t.pumpWidget(
        MaterialApp(
          theme: Ks.theme(),
          builder: (c, child) => MediaQuery(
            data: MediaQuery.of(c)
                .copyWith(textScaler: TextScaler.linear(scale)),
            child: DefaultTextStyle.merge(
              style: const TextStyle(
                fontFamily: 'Roboto',
                fontFamilyFallback: ['NotoSansDevanagari'],
              ),
              child: child!,
            ),
          ),
          home: const _Host(),
        ),
      );
      try {
        await body();
      } finally {
        if (turnGate?.isCompleted == false) turnGate!.complete(_turn(item));
        if (mic.permGate?.isCompleted == false) mic.permGate!.complete(false);
        await t.pumpWidget(const SizedBox());
        await adv(30000, step: 1000);
        t.takeException();
      }
    }, () => MockClient(_handle));
    Lang.code.value = 'en';
  }

  Future<void> adv(int ms, {int step = 100}) async {
    for (var left = ms; left > 0; left -= step) {
      await t.pump(Duration(milliseconds: left > step ? step : left));
    }
  }

  Future<void> until(
    bool Function() cond, {
    int maxMs = 8000,
    String? what,
  }) async {
    var waited = 0;
    while (!cond()) {
      if (waited >= maxMs) {
        final texts = t
            .widgetList<Text>(find.byType(Text))
            .map((x) => x.data ?? x.textSpan?.toPlainText() ?? '')
            .take(30)
            .toList();
        fail(
          'timed out waiting for ${what ?? 'condition'}: perm=${mic.permCalls} starts=${mic.starts} $texts',
        );
      }
      await t.pump(const Duration(milliseconds: 50));
      waited += 50;
    }
  }

  Future<void> begin() async {
    await t.tap(find.text('open'));
    await adv(500);
    await t.tap(find.text('हिंदी'));
    await adv(100);
  }

  /// A long paragraph on a short screen may scroll inside its area instead of shrinking.
  bool scrolls(String key) =>
      key == 'paragraph' && (size.height < 700 || scale > 1);

  Finder txt(String en, String hi) => find.text(tr(en, hi));

  void noExceptions(String where) {
    final e = t.takeException();
    if (e != null) fail('$where: ${e is FlutterError ? e.toStringDeep() : e}');
  }

  /// Rect of a widget on screen, including any scale transform between it and the root.
  Rect rect(Finder f) {
    final box = t.renderObject<RenderBox>(f.first);
    return MatrixUtils.transformRect(
      box.getTransformTo(null),
      Offset.zero & box.size,
    );
  }

  /// The item must be fully visible in its own viewport (a very long paragraph on a short
  /// screen may scroll instead, but must start at the top), and that viewport must not touch
  /// the mic panel, help panel, buttons, transcript, Saathi card or control bar.
  void checkItem(String where, {bool mayScroll = false}) {
    noExceptions(where);
    final item = rect(find.byType(VoiceItemView));
    final vp = rect(
      find.ancestor(
        of: find.byType(VoiceFit),
        matching: find.byType(SingleChildScrollView),
      ),
    );
    final screen = Offset.zero & size;
    final hint = '$where item=$item viewport=$vp screen=$screen';
    expect(
      screen.inflate(.5).contains(vp.topLeft) &&
          screen.inflate(.5).contains(vp.bottomRight),
      isTrue,
      reason: 'viewport inside the screen: $hint',
    );
    if (mayScroll) {
      expect(
        item.top,
        greaterThanOrEqualTo(vp.top - .5),
        reason: 'starts at top: $hint',
      );
    } else {
      expect(
        item.top,
        greaterThanOrEqualTo(vp.top - .5),
        reason: 'item top: $hint',
      );
      expect(
        item.bottom,
        lessThanOrEqualTo(vp.bottom + .5),
        reason: 'item bottom: $hint',
      );
      expect(
        item.left,
        greaterThanOrEqualTo(vp.left - .5),
        reason: 'item left: $hint',
      );
      expect(
        item.right,
        lessThanOrEqualTo(vp.right + .5),
        reason: 'item right: $hint',
      );
    }
    final visible = item.intersect(vp);
    final others = <String, Finder>{
      'mic': find.byType(VoiceMicIndicator),
      'transcript': find.byType(VoiceTranscript),
      'buttons': find.byWidgetPredicate(
        (w) => w is FilledButton || w is OutlinedButton,
      ),
      'tutor': find.byType(Card),
      'controls': find.byType(InkWell),
    };
    for (final e in others.entries) {
      for (final el in e.value.evaluate()) {
        final r = rect(find.byElementPredicate((x) => x == el));
        final x = r.intersect(visible);
        expect(
          x.width > .5 && x.height > .5,
          isFalse,
          reason: '${e.key} $r overlaps visible item $hint',
        );
        final y = r.intersect(vp);
        expect(
          y.width > .5 && y.height > .5,
          isFalse,
          reason: '${e.key} $r overlaps item viewport $hint',
        );
      }
    }
  }

  /// Tap targets of the Done button and the control bar are at least 56 dp tall.
  void checkTargets(String where) {
    final done = txt('Done speaking', 'बोल लिया');
    if (done.evaluate().isNotEmpty) {
      final b = find.ancestor(of: done, matching: find.byType(FilledButton));
      expect(
        rect(b).height,
        greaterThanOrEqualTo(56),
        reason: '$where Done button',
      );
      final bottom = rect(b).bottom;
      expect(
        bottom,
        lessThanOrEqualTo(size.height),
        reason: '$where Done on screen',
      );
      // inside the (scrollable) status area: not clipped, no scrolling needed to reach it
      final area = rect(
        find
            .ancestor(of: b, matching: find.byType(SingleChildScrollView))
            .first,
      );
      expect(
        rect(b).top,
        greaterThanOrEqualTo(area.top - .5),
        reason: '$where Done clipped (top)',
      );
      expect(
        rect(b).bottom,
        lessThanOrEqualTo(area.bottom + .5),
        reason: '$where Done clipped (bottom)',
      );
    }
    for (final l in [
      ['Pause', 'रोकें'],
      ['Repeat', 'दोहराएँ'],
      ['Skip', 'छोड़ें'],
      ['Stop', 'बंद करें'],
      ['Resume', 'शुरू'],
    ]) {
      final f = txt(l[0], l[1]);
      if (f.evaluate().isEmpty) continue;
      final w = find.ancestor(of: f, matching: find.byType(InkWell)).first;
      final r = rect(w);
      expect(
        r.height,
        greaterThanOrEqualTo(56),
        reason: '$where ${l[0]} target',
      );
      expect(
        r.bottom,
        lessThanOrEqualTo(size.height),
        reason: '$where ${l[0]} on screen',
      );
    }
  }
}

const _sizes = [Size(360, 640), Size(400, 889), Size(411, 900)];

void _layout(String name, String itemKey, Future<void> Function(_Rig r) body) {
  for (final size in _sizes) {
    for (final scale in [1.0, 1.3]) {
      for (final lang in ['en', 'hi']) {
        testWidgets(
          '$name $itemKey ${size.width.toInt()}x${size.height.toInt()} x$scale $lang',
          (t) async {
            final r = _Rig(t, lang, size, scale, itemKey);
            await r.run(() => body(r));
          },
        );
      }
    }
  }
}

void main() {
  setUpAll(_loadFonts);

  for (final k in ['letter', 'word', 'paragraph', 'build', 'sentence']) {
    _layout('listening', k, (r) async {
      await r.begin();
      await r.until(() => r.mic.listening, what: 'mic listening');
      await r.adv(300);
      expect(
        r.txt('Listening… speak now', 'सुन रहा हूँ… अब बोलो'),
        findsOneWidget,
      );
      r.checkItem('listening', mayScroll: r.scrolls(k));
      r.checkTargets('listening');
    });
  }

  for (final k in ['letter', 'paragraph']) {
    _layout('listening+transcript', k, (r) async {
      await r.begin();
      await r.until(() => r.mic.listening, what: 'mic listening');
      await r.adv(300);
      // collapsed by default while listening
      expect(find.byType(VoiceTranscript), findsNothing);
      await r.t.tap(
        find.byIcon(
          r.size.height < 700
              ? Icons.forum_outlined
              : Icons.expand_less_rounded,
        ),
      );
      await r.adv(300);
      expect(find.byType(VoiceTranscript), findsOneWidget);
      r.checkItem('listening+transcript', mayScroll: r.scrolls(k));
      r.checkTargets('listening+transcript');
    });

    _layout('thinking', k, (r) async {
      r.turnGate = Completer();
      await r.begin();
      await r.until(() => r.mic.listening, what: 'mic listening');
      r.mic.say();
      await r.until(
        () => r
            .txt('Saathi is thinking…', 'साथी सोच रहा है…')
            .evaluate()
            .isNotEmpty,
        what: 'thinking',
      );
      r.checkItem('thinking', mayScroll: r.scrolls(k));
      r.checkTargets('thinking');
    });

    _layout('paused', k, (r) async {
      await r.begin();
      await r.until(() => r.mic.listening, what: 'mic listening');
      await r.t.tap(
        find.ancestor(
          of: r.txt('Pause', 'रोकें'),
          matching: find.byType(InkWell),
        ),
      );
      await r.adv(500);
      expect(r.txt('Paused', 'रुका हुआ'), findsOneWidget);
      r.checkItem('paused', mayScroll: r.scrolls(k));
      r.checkTargets('paused');
    });

    _layout('mic denied panel', k, (r) async {
      r.mic.granted = false;
      await r.begin();
      await r.until(
        () => r.txt('Try the mic again', 'माइक फिर से').evaluate().isNotEmpty,
        what: 'mic panel',
      );
      await r.adv(200);
      r.checkItem('mic denied', mayScroll: r.scrolls(k));
      r.checkTargets('mic denied');
    });

    _layout('retry attempt', k, (r) async {
      await r.begin();
      await r.until(() => r.mic.listening, what: 'mic listening');
      r.mic.say();
      // the server answers "wrong" with the same item: Try 2 of 5 and the cheer badge show
      await r.until(
        () => find.textContaining(tr('Try 2', 'कोशिश 2')).evaluate().isNotEmpty,
        what: 'try 2',
      );
      r.checkItem('retry (cheer visible)', mayScroll: r.scrolls(k));
      await r.until(() => r.mic.listening, what: 'listening again');
      await r.adv(3000); // cheer gone
      expect(find.textContaining(tr('Try 2', 'कोशिश 2')), findsOneWidget);
      r.checkItem('retry (listening)', mayScroll: r.scrolls(k));
      r.checkTargets('retry');
    });
  }

  // ---- permission --------------------------------------------------------------------------

  _perm('slow permission dialog is not a denial', (r) async {
    r.mic.permGate = Completer();
    await r.begin();
    await r.adv(15000, step: 500); // way beyond the old 3 s / 20 s waits
    expect(r.txt('Try the mic again', 'माइक फिर से'), findsNothing);
    expect(r.mic.starts, 0);
    r.mic.permGate!.complete(true); // the parent taps Allow
    await r.until(() => r.mic.listening, what: 'listening after Allow');
    expect(r.mic.starts, 1);
    expect(r.txt('Try the mic again', 'माइक फिर से'), findsNothing);
  });

  _perm('dialog answered Deny shows the denied panel', (r) async {
    r.mic.permGate = Completer();
    await r.begin();
    await r.adv(20000, step: 500);
    r.mic.permGate!.complete(false);
    await r.until(
      () => r.txt('Try the mic again', 'माइक फिर से').evaluate().isNotEmpty,
      what: 'mic panel',
    );
    expect(
      find.textContaining(tr('Allow microphone access', 'माइक चालू करें')),
      findsOneWidget,
    );
  });

  _perm(
    'hung permission call ends after the 60 s safety net, not as a denial',
    (r) async {
      r.mic.permGate = Completer();
      await r.begin();
      await r.adv(58000, step: 1000);
      expect(r.txt('Try the mic again', 'माइक फिर से'), findsNothing);
      await r.adv(4000, step: 500);
      await r.until(
        () => r.txt('Try the mic again', 'माइक फिर से').evaluate().isNotEmpty,
        what: 'mic panel after the safety net',
      );
      expect(
        r.txt('The microphone did not start.', 'माइक चालू नहीं हुआ।'),
        findsOneWidget,
      );
    },
  );

  _perm(
    'back from Settings with the permission granted starts listening by itself',
    (r) async {
      r.mic.granted = false;
      await r.begin();
      await r.until(
        () => r.txt('Try the mic again', 'माइक फिर से').evaluate().isNotEmpty,
        what: 'mic panel',
      );
      expect(r.mic.listening, isFalse);
      // still denied when the app resumes: stays on the panel, no dialog is shown again
      r.t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      r.t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await r.adv(500);
      expect(r.mic.softChecks, 1);
      expect(r.mic.permCalls, 1);
      expect(r.txt('Try the mic again', 'माइक फिर से'), findsOneWidget);
      // the parent grants it in Settings and comes back
      r.mic.granted = true;
      r.t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await r.until(() => r.mic.listening, what: 'listening after resume');
      expect(r.txt('Try the mic again', 'माइक फिर से'), findsNothing);
      expect(
        r.txt('Listening… speak now', 'सुन रहा हूँ… अब बोलो'),
        findsOneWidget,
      );
    },
  );
}

void _perm(String name, Future<void> Function(_Rig r) body) {
  for (final lang in ['en', 'hi']) {
    testWidgets('permission: $name [$lang]', (t) async {
      final r = _Rig(t, lang, const Size(400, 889), 1.0, 'letter');
      await r.run(() => body(r));
    });
  }
}
