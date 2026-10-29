import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:kaksha_parent/api.dart';
import 'package:kaksha_parent/friendly.dart';
import 'package:kaksha_parent/l10n.dart';
import 'package:kaksha_parent/widgets/insight_cards.dart';

/// Regressions for what a real phone showed (moto g64 5G, 2026-10-30).
void main() {
  tearDown(() => Lang.code.value = 'en');

  group('friendlyError', () {
    test('no internet never shows a socket error or the server address', () {
      for (final e in <Object>[
        http.ClientException(
          "SocketException: Failed host lookup: 'kaksha-saathi-558g.onrender.com' "
          '(OS Error: No address associated with hostname, errno = 7)',
          Uri.parse('https://kaksha-saathi-558g.onrender.com/v1/parent/child'),
        ),
        TimeoutException('slow'),
      ]) {
        for (final lang in ['en', 'hi']) {
          Lang.code.value = lang;
          final m = friendlyError(e);
          expect(m, isNot(contains('Socket')));
          expect(m, isNot(contains('onrender')));
          expect(m, isNot(contains('uri=')));
          expect(m, lang == 'en' ? contains('internet') : contains('इंटरनेट'));
        }
      }
    });

    test('a sleeping server and a server fault read as plain sentences', () {
      expect(friendlyError(ApiError('x', 503)), contains('waking up'));
      expect(friendlyError(ApiError('Internal', 500)), contains('our side'));
      Lang.code.value = 'hi';
      expect(friendlyError(ApiError('x', 503)), contains('सर्वर'));
    });
  });

  group('friendlyGateError', () {
    test('wrong details are not shown as the raw server string', () {
      final en = friendlyGateError(ApiError('invalid credentials', 401));
      expect(en, isNot(contains('invalid credentials')));
      expect(en, contains('PIN'));
      Lang.code.value = 'hi';
      final hi = friendlyGateError(ApiError('invalid credentials', 401));
      expect(hi, contains('पिन'));
    });

    test(
      'consent, not found, already set up and bad numbers each have a sentence',
      () {
        expect(friendlyGateError(ApiError('x', 403)), contains('consent'));
        expect(
          friendlyGateError(ApiError('x', 404)),
          contains('could not find'),
        );
        expect(
          friendlyGateError(ApiError('x', 409)),
          contains('already set up'),
        );
        expect(
          friendlyGateError(ApiError('[{"loc":"pin"}]', 422)),
          contains('4 to 6 digits'),
        );
      },
    );
  });

  group('speechLang', () {
    test('an English line carrying a Hindi name is read in English', () {
      expect(
        speechLang(
          'This week the class is learning “Addition”. कविता is practising “Place value”.',
        ),
        'en',
      );
    });
    test('a Hindi line with a Latin word is read in Hindi', () {
      expect(speechLang('इस हफ़्ते कक्षा में NIPUN अभ्यास हुआ।'), 'hi');
    });
    test('a line with no letters follows the app language', () {
      expect(speechLang('52 − 17 = 35'), 'en');
      Lang.code.value = 'hi';
      expect(speechLang('52 − 17 = 35'), 'hi');
    });
  });
}
