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
        title: tr('Kaksha Saathi: Practice', 'कक्षा साथी: अभ्यास'),
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
        home: Api.i.signedIn ? const HomeScreen() : const GateScreen(),
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
