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
  runApp(const KakshaTeacherApp());
}

class KakshaTeacherApp extends StatelessWidget {
  const KakshaTeacherApp({super.key});
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: Lang.code,
      builder: (_, _, _) => MaterialApp(
        title: tr('Kaksha Saathi — Teacher', 'कक्षा साथी — शिक्षिका'),
        debugShowCheckedModeBanner: false,
        theme: Ks.theme(),
        locale: Lang.locale,
        supportedLocales: const [Locale('en', 'IN'), Locale('hi', 'IN')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Api.i.loggedIn ? const BoardScreen() : const LoginScreen(),
      ),
    );
  }
}
