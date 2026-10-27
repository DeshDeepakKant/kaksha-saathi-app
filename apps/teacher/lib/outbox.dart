import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// What happened when an entry was replayed (decided by `Api`, which owns the HTTP layer).
enum OutboxResult {
  /// The server accepted it: remove the entry.
  sent,

  /// Network failure or a retryable server error: keep the entry and stop for now.
  retry,

  /// The server refused it for good (4xx) or it belongs to someone else: remove and move on.
  drop,
}

/// One parked write.
class OutboxEntry {
  OutboxEntry({
    required this.id,
    required this.path,
    required this.body,
    required this.createdAt,
    this.attempts = 0,
    this.owner = '',
  });

  final String id;
  final String path;
  final Map<String, dynamic> body;
  final int createdAt; // ms since epoch
  int attempts;

  /// Teacher id the write was made under, so one teacher's writes are never sent as another's.
  final String owner;

  Map<String, dynamic> toJson() => {
    'id': id,
    'path': path,
    'body': body,
    'createdAt': createdAt,
    'attempts': attempts,
    'owner': owner,
  };

  static OutboxEntry? fromJson(dynamic j) {
    if (j is! Map) return null;
    final id = j['id'], path = j['path'], body = j['body'];
    if (id is! String || path is! String || body is! Map) return null;
    return OutboxEntry(
      id: id,
      path: path,
      body: body.cast<String, dynamic>(),
      createdAt: (j['createdAt'] as num?)?.toInt() ?? 0,
      attempts: (j['attempts'] as num?)?.toInt() ?? 0,
      owner: (j['owner'] as String?) ?? '',
    );
  }
}

/// Offline queue of JSON writes, persisted in SharedPreferences (the app sets the
/// `ks_teacher.` prefix in main.dart, so the key lives under it). Plain Dart, no HTTP:
/// `Api` hands [flush] a send callback.
class Outbox {
  Outbox({this.cap = 200});

  static const _key = 'outbox';

  /// Most entries kept. When full, the OLDEST is dropped so the newest write is never lost.
  final int cap;

  /// Entries waiting to be sent (drives the "N waiting to send" chip).
  final ValueNotifier<int> pending = ValueNotifier<int>(0);

  final List<OutboxEntry> _items = [];
  bool _flushing = false;

  int get length => _items.length;
  bool get isEmpty => _items.isEmpty;
  bool get flushing => _flushing;
  List<OutboxEntry> get items => List.unmodifiable(_items);

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    final raw = p.getString(_key);
    _items.clear();
    if (raw != null && raw.isNotEmpty) {
      try {
        for (final j in jsonDecode(raw) as List) {
          final e = OutboxEntry.fromJson(j);
          if (e != null) _items.add(e);
        }
      } catch (_) {
        // A corrupt blob is not worth crashing the app over; start empty.
      }
    }
    pending.value = _items.length;
  }

  Future<void> _persist() async {
    pending.value = _items.length;
    final p = await SharedPreferences.getInstance();
    if (_items.isEmpty) {
      await p.remove(_key);
    } else {
      await p.setString(
        _key,
        jsonEncode(_items.map((e) => e.toJson()).toList()),
      );
    }
  }

  Future<void> add(OutboxEntry e) async {
    _items.add(e);
    while (_items.length > cap) {
      _items.removeAt(0);
    }
    await _persist();
  }

  Future<void> removeWhere(bool Function(OutboxEntry) test) async {
    _items.removeWhere(test);
    await _persist();
  }

  Future<void> clear() async {
    _items.clear();
    await _persist();
  }

  /// Replays entries in order. Stops at the first [OutboxResult.retry]. Only one run at a time:
  /// a second call while one is running returns immediately.
  Future<void> flush(Future<OutboxResult> Function(OutboxEntry e) send) async {
    if (_flushing) return;
    _flushing = true;
    try {
      while (_items.isNotEmpty) {
        final e = _items.first;
        final r = await send(e);
        if (r == OutboxResult.retry) {
          e.attempts++;
          // The entry may have been pushed out by the cap while it was in flight.
          if (_items.any((x) => x.id == e.id)) await _persist();
          break;
        }
        // Remove by id: the cap may have shifted the list while we were awaiting.
        _items.removeWhere((x) => x.id == e.id);
        await _persist();
      }
    } finally {
      _flushing = false;
    }
  }
}

final _rng = Random.secure();

/// Random 32-hex-char id (UUID-shaped, no packages) used for queue ids and `client_uuid`.
String newClientUuid() {
  String hex(int n) =>
      List.generate(n, (_) => _rng.nextInt(16).toRadixString(16)).join();
  // 8-4-4-4-12 with the version nibble set to 4 and the variant to 8..b.
  final variant = (8 + _rng.nextInt(4)).toRadixString(16);
  return '${hex(8)}-${hex(4)}-4${hex(3)}-$variant${hex(3)}-${hex(12)}';
}
