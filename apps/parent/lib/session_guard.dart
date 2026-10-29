import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/gate_screen.dart';

/// When the server says the sign-in has expired (401), clear it and go back to the sign-in screen,
/// the same way Home does. Returns true when it did, so a screen can stop handling the error.
Future<bool> handleExpiredSession(BuildContext context, Object error) async {
  if (error is! ApiError || error.status != 401) return false;
  await Api.i.logout();
  if (context.mounted) {
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const GateScreen()),
      (_) => false,
    );
  }
  return true;
}
