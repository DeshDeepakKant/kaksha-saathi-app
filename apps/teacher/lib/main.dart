import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'l10n.dart';
import 'screens/board_screen.dart';
import 'screens/login_screen.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Teacher and parent apps can share an origin in the demo; keep their stored sessions apart.
  SharedPreferences.setPrefix('ks_teacher.');
  await Lang.load();
  await Api.i.loadSession();
  // Send anything parked while offline in a previous run (no-op when the queue is empty).
  unawaited(Api.i.flushOutbox());
  // A rejected session (expired token, or a token from another server) goes back to login.
  Api.i.onSessionExpired = () => _nav.currentState?.pushAndRemoveUntil(
    MaterialPageRoute(builder: (_) => const LoginScreen()),
    (_) => false,
  );
  runApp(const KakshaTeacherApp());
  // Retry parked writes about once a minute while the app is open.
  Api.i.startOutboxTimer();
}

final _nav = GlobalKey<NavigatorState>();

class KakshaTeacherApp extends StatelessWidget {
  const KakshaTeacherApp({super.key});
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: Lang.code,
      builder: (_, _, _) => MaterialApp(
        navigatorKey: _nav,
        title: tr('Kaksha Saathi — Teacher', 'कक्षा साथी — शिक्षिका'),
        debugShowCheckedModeBanner: false,
        theme: _theme(),
        locale: Lang.locale,
        supportedLocales: Lang.supportedLocales,
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        // Urdu, Kashmiri and Sindhi lay out right to left, whatever Flutter locale they borrow.
        builder: (_, child) => Directionality(
          textDirection: Lang.isRtl ? TextDirection.rtl : TextDirection.ltr,
          child: child!,
        ),
        home: Api.i.loggedIn ? const BoardScreen() : const LoginScreen(),
      ),
    );
  }
}

/// The app theme, with bundled fonts as fallback for Ol Chiki and Meetei Mayek text.
ThemeData _theme() {
  final t = Ks.theme();
  return t.copyWith(
    textTheme: t.textTheme.apply(fontFamilyFallback: Lang.fontFallback),
    primaryTextTheme: t.primaryTextTheme.apply(fontFamilyFallback: Lang.fontFallback),
  );
}
