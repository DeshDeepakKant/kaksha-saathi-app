import 'package:flutter_test/flutter_test.dart';
import 'package:kaksha_teacher/l10n.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _tamil = RegExp('[஀-௿]');
final _arabic = RegExp('[؀-ۿ]');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() => Lang.set('en'));

  test('English and Hindi are unchanged', () async {
    await Lang.set('en');
    expect(tr('Cancel', 'रद्द करें'), 'Cancel');
    expect(trf('{time_min} min', '{time_min} मिनट', {'time_min': 5}), '5 min');
    await Lang.set('hi');
    expect(tr('Cancel', 'रद्द करें'), 'रद्द करें');
    expect(trf('{time_min} min', '{time_min} मिनट', {'time_min': 5}), '5 मिनट');
  });

  test('Tamil reads the table, fills placeholders, falls back to English', () async {
    await Lang.set('ta');
    expect(Lang.code.value, 'ta');
    expect(Lang.isRtl, isFalse);
    final cancel = tr('Cancel', 'रद्द करें');
    expect(_tamil.hasMatch(cancel), isTrue, reason: cancel);
    final mins = trf('{time_min} min', '{time_min} मिनट', {'time_min': 5});
    expect(mins, contains('5'));
    expect(mins, isNot(contains('{')));
    expect(_tamil.hasMatch(mins), isTrue, reason: mins);
    expect(tr('Not a key in any table', 'कोई कुंजी नहीं'), 'Not a key in any table');
    // One English string, two Hindi meanings: both resolve.
    expect(_tamil.hasMatch(tr('T', 'मं')), isTrue);
    expect(tr('T', 'मं'), isNot(tr('T', 'गु')));
  });

  test('Urdu is right to left and in Arabic script', () async {
    await Lang.set('ur');
    expect(Lang.isRtl, isTrue);
    expect(Lang.locale.languageCode, 'ur');
    final cancel = tr('Cancel', 'रद्द करें');
    expect(_arabic.hasMatch(cancel), isTrue, reason: cancel);
  });

  test('Languages without Material strings borrow a locale; unknown codes are English', () async {
    await Lang.set('sat');
    expect(Lang.locale.languageCode, 'hi');
    await Lang.set('ks');
    expect(Lang.locale.languageCode, 'ur');
    expect(Lang.isRtl, isTrue);
    await Lang.set('zz');
    expect(Lang.code.value, 'en');
    expect(appLanguages(), hasLength(23));
    expect(appLanguages().where((l) => l.beta).map((l) => l.code).toSet(),
        {'brx', 'doi', 'ks', 'kok', 'mai', 'mni', 'sa', 'sat', 'sd'});
  });

  test('cpTitle uses the learning-language title when it is not Hindi or English', () async {
    final cp = {'checkpoint_id': 'cp1', 'title_hi': 'जोड़', 'title_en': 'Addition'};
    expect(cpTitle(cp), 'Addition');
    ContentLang.apply('mr', {'cp1': 'बेरीज'});
    expect(cpTitle(cp), 'बेरीज');
    expect(cpTitle({'checkpoint_id': 'cp2', 'title_hi': 'घटाना', 'title_en': 'Subtraction'}), 'Subtraction');
    ContentLang.apply('hi', const {});
    expect(cpTitle(cp), 'Addition');
  });
}
