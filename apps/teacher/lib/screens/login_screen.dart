import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'board_screen.dart';
import '../l10n.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _code = TextEditingController();
  final _pin = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Api.i.login(_code.text.trim().toUpperCase(), _pin.text.trim());
      if (!mounted) return;
      Navigator.of(
        context,
      ).pushReplacement(MaterialPageRoute(builder: (_) => const BoardScreen()));
    } on ApiError catch (e) {
      setState(
        () => _error = e.status == 401
            ? tr('School code or PIN is wrong.', 'स्कूल कोड या पिन गलत है।')
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
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Align(
                  alignment: Alignment.centerRight,
                  child: LangToggle(),
                ),
                const SizedBox(height: 16),
                const Icon(Icons.school_rounded, size: 64, color: Ks.accent),
                const SizedBox(height: 12),
                Text(
                  tr('Kaksha Saathi', 'कक्षा साथी'),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleLarge
                      ?.copyWith(fontSize: 30),
                ),
                const SizedBox(height: 4),
                Text(
                  tr(
                    'Where every child is, and what to do today',
                    'हर बच्चा कहाँ है, और आज क्या करें',
                  ),
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Ks.muted, fontSize: 16),
                ),
                const SizedBox(height: 32),
                TextField(
                  controller: _code,
                  textCapitalization: TextCapitalization.characters,
                  decoration: InputDecoration(
                    labelText: tr('School code', 'स्कूल कोड'),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pin,
                  keyboardType: TextInputType.number,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: tr('PIN', 'पिन'),
                    hintText: '••••',
                  ),
                  onSubmitted: (_) => _login(),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Ks.rose)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _login,
                  child: _busy
                      ? const SizedBox(
                          height: 22,
                          width: 22,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text(tr('Log in', 'लॉगिन')),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
