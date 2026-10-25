import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'l10n.dart';
import 'screens/gate_screen.dart';
import 'screens/home_screen.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setPrefix('ks_parent.');
  await Lang.load();
  await Api.i.load();
  runApp(const KakshaParentApp());
}

class KakshaParentApp extends StatelessWidget {
  const KakshaParentApp({super.key});
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: Lang.code,
      builder: (_, _, _) => MaterialApp(
        title: tr('Kaksha Saathi — Practice', 'कक्षा साथी — अभ्यास'),
        debugShowCheckedModeBanner: false,
        theme: Ks.theme(),
        locale: Lang.locale,
        supportedLocales: const [Locale('en', 'IN'), Locale('hi', 'IN')],
        localizationsDelegates: const [
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Api.i.signedIn ? const HomeScreen() : const GateScreen(),
      ),
    );
  }
}
