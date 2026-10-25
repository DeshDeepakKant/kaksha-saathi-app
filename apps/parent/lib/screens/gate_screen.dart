import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'home_screen.dart';
import '../l10n.dart';

/// Parent gate: the child cannot open the session alone. Consent is read aloud and must be
/// actively accepted; the parent's phone + PIN is the only key.
class GateScreen extends StatefulWidget {
  const GateScreen({super.key});
  @override
  State<GateScreen> createState() => _GateScreenState();
}

class _GateScreenState extends State<GateScreen> {
  int _mode = 0; // 0 sign-in, 1 new consent
  final _school = TextEditingController(text: 'DEMO');
  final _roll = TextEditingController();
  final _phone = TextEditingController();
  final _pin = TextEditingController();
  bool _consent = false;
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_mode == 1) {
        await Api.i.consent({
          'school_code': _school.text.trim().toUpperCase(),
          'child_roll': int.tryParse(_roll.text.trim()) ?? 0,
          'parent_phone': _phone.text.trim(),
          'consents': _consent,
          'pin': _pin.text.trim(),
        });
      } else {
        await Api.i.login({
          'school_code': _school.text.trim().toUpperCase(),
          'child_roll': int.tryParse(_roll.text.trim()) ?? 0,
          'parent_phone': _phone.text.trim(),
          'pin': _pin.text.trim(),
        });
      }
      if (!mounted) return;
      Navigator.of(
        context,
      ).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
    } on ApiError catch (e) {
      setState(
        () => _error = e.status == 403
            ? tr(
                'The school has not recorded this child\'s parent consent. Please meet the teacher.',
                'स्कूल ने इस बच्चे के अभिभावक की सहमति दर्ज नहीं की। अध्यापिका से मिलें।',
              )
            : e.message,
      );
    } catch (_) {
      setState(
        () => _error = tr(
          'Could not connect to the server. Check your internet.',
          'सर्वर से नहीं जुड़ सके। इंटरनेट जाँचें।',
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Align(
                    alignment: Alignment.centerRight,
                    child: LangToggle(),
                  ),
                  const SizedBox(height: 10),
                  const Icon(
                    Icons.family_restroom_rounded,
                    size: 60,
                    color: Ks.accent,
                  ),
                  const SizedBox(height: 10),
                  Text(
                    tr('Kaksha Saathi', 'कक्षा साथी'),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleLarge
                        ?.copyWith(fontSize: 30),
                  ),
                  Text(
                    tr(
                      'Fun 25–30 minute practice at home — by speaking',
                      'घर पर 25–30 मिनट का मज़ेदार अभ्यास — बोलकर',
                    ),
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Ks.muted, fontSize: 16),
                  ),
                  const SizedBox(height: 24),
                  SegmentedButton<int>(
                    segments: [
                      ButtonSegment(
                        value: 0,
                        label: Text(tr('Sign in', 'साइन इन')),
                      ),
                      ButtonSegment(
                        value: 1,
                        label: Text(tr('First time', 'पहली बार')),
                      ),
                    ],
                    selected: {_mode},
                    onSelectionChanged: (s) => setState(() => _mode = s.first),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _school,
                    textCapitalization: TextCapitalization.characters,
                    decoration: InputDecoration(
                      labelText: tr('School code', 'स्कूल कोड'),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _roll,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: tr(
                        'Child\'s roll number',
                        'बच्चे का रोल नंबर',
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    decoration: InputDecoration(
                      labelText: tr(
                        'Parent\'s mobile number',
                        'अभिभावक का मोबाइल नंबर',
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _pin,
                    keyboardType: TextInputType.number,
                    obscureText: true,
                    decoration: InputDecoration(
                      labelText: _mode == 1
                          ? tr('New 4-digit PIN', 'नया 4 अंकों का पिन')
                          : tr('PIN', 'पिन'),
                    ),
                  ),
                  if (_mode == 1) ...[
                    const SizedBox(height: 16),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              tr('Parent consent', 'अभिभावक की सहमति'),
                              style: TextStyle(
                                fontWeight: FontWeight.w700,
                                fontSize: 16,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              tr(
                                'We keep only the child\'s first name, roll number and learning evidence. Photos are deleted after 7 days and voice is not saved. Practice is for learning only — if the child talks about something else, Saathi brings them back to the lesson. You can have the data deleted at any time.',
                                'हम बच्चे का पहला नाम, रोल नंबर और सीखने के सबूत ही रखते हैं। फ़ोटो 7 दिन में हट जाती हैं और आवाज़ सहेजी नहीं जाती। '
                                    'अभ्यास केवल पढ़ाई का है — बच्चा किसी और विषय की बात करे तो साथी पढ़ाई पर लौटाता है। आप कभी भी डेटा हटवा सकते हैं।',
                              ),
                              style: TextStyle(fontSize: 15),
                            ),
                            CheckboxListTile(
                              contentPadding: EdgeInsets.zero,
                              value: _consent,
                              onChanged: (v) =>
                                  setState(() => _consent = v ?? false),
                              title: Text(
                                tr(
                                  'I am this child\'s parent/guardian and I give consent.',
                                  'मैं इस बच्चे के अभिभावक/संरक्षक हूँ और सहमति देता/देती हूँ।',
                                ),
                                style: TextStyle(fontSize: 15),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Ks.rose)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy || (_mode == 1 && !_consent)
                        ? null
                        : _submit,
                    child: _busy
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : Text(
                            _mode == 1
                                ? tr(
                                    'Consent and start',
                                    'सहमति दें और शुरू करें',
                                  )
                                : tr('Sign in', 'साइन इन'),
                          ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    tr(
                      'Demo: code DEMO · roll 12 · phone 9876500000 · PIN 0000',
                      'डेमो: कोड DEMO · रोल 12 · फ़ोन 9876500000 · पिन 0000',
                    ),
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Ks.muted, fontSize: 13),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
