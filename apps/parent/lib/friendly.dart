import 'dart:async';

import 'package:http/http.dart' as http;

import 'api.dart';
import 'l10n.dart';

/// One plain-language message for anything that can go wrong on a request, so a parent never sees
/// "SocketException", a server address or a raw server string. Hindi first-class via [tr].
String friendlyError(Object e) {
  final s = e.toString();
  final network =
      e is TimeoutException ||
      e is http.ClientException ||
      s.contains('SocketException') ||
      s.contains('Failed host lookup') ||
      s.contains('Connection refused') ||
      s.contains('Network is unreachable');
  if (network) {
    return tr(
      'No internet. Please check your connection and try again.',
      'इंटरनेट नहीं है। कनेक्शन जाँचकर फिर कोशिश करें।',
    );
  }
  if (e is ApiError) {
    if (e.status == 401) {
      return tr('Please sign in again.', 'कृपया फिर से साइन इन करें।');
    }
    if (e.status == 502 || e.status == 503 || e.status == 504) {
      return tr(
        'The server is waking up. Please try again in a minute.',
        'सर्वर जाग रहा है। एक मिनट बाद फिर कोशिश करें।',
      );
    }
    if (e.status >= 500) {
      return tr(
        'Something went wrong on our side. Please try again.',
        'हमारी तरफ़ कुछ गड़बड़ हुई। फिर से कोशिश करें।',
      );
    }
  }
  return tr(
    'Something went wrong. Please try again.',
    'कुछ गड़बड़ हुई। फिर से कोशिश करें।',
  );
}

/// What the sign-in / first-time screen says for a failed request.
String friendlyGateError(Object e) {
  if (e is ApiError) {
    switch (e.status) {
      case 401:
        return tr(
          'The school code, roll number, phone number or PIN is not right. Please check and try again.',
          'स्कूल कोड, रोल नंबर, फ़ोन नंबर या पिन सही नहीं है। जाँचकर फिर कोशिश करें।',
        );
      case 403:
        return tr(
          'The school has not recorded this child\'s parent consent. Please meet the teacher.',
          'स्कूल ने इस बच्चे के अभिभावक की सहमति दर्ज नहीं की। अध्यापिका से मिलें।',
        );
      case 404:
        return tr(
          'We could not find this school or child. Please check the school code and roll number.',
          'यह स्कूल या बच्चा नहीं मिला। स्कूल कोड और रोल नंबर जाँचें।',
        );
      case 409:
        return tr(
          'This account is already set up. Please use Sign in.',
          'यह खाता पहले से बना है। कृपया साइन इन करें।',
        );
      case 422:
        return tr(
          'Please check the numbers you typed. The PIN needs 4 to 6 digits.',
          'लिखे हुए नंबर जाँचें। पिन में 4 से 6 अंक होने चाहिए।',
        );
    }
  }
  return friendlyError(e);
}
