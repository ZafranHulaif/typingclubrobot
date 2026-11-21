// Sidik jari mesin SAMA dgn gui/licensing.py::_machine_data supaya kode
// mesin (dan lisensi yang sudah disetujui) tidak berubah saat pindah ke v4:
//   "mac=<12 hex>|host=<COMPUTERNAME>|vol=<serial volume sistem>"
// mac = uuid.getnode() python di Windows = node dari UuidCreateSequential
// (byte 10..15 GUID); dilewati kalau bit multicast menyala (MAC acak).
import 'dart:ffi';
import 'dart:io';

import 'license.dart';

typedef _UuidNative = Int32 Function(Pointer<Uint8>);
typedef _UuidDart = int Function(Pointer<Uint8>);
typedef _VolNative = Int32 Function(Pointer<Uint16>, Pointer<Uint16>, Uint32,
    Pointer<Uint32>, Pointer<Uint32>, Pointer<Uint32>, Pointer<Uint16>, Uint32);
typedef _VolDart = int Function(Pointer<Uint16>, Pointer<Uint16>, int,
    Pointer<Uint32>, Pointer<Uint32>, Pointer<Uint32>, Pointer<Uint16>, int);

/// Node 48-bit dari 16 byte GUID (format bytes_le python).
int nodeFromGuid(List<int> g) {
  var n = 0;
  for (var i = 10; i < 16; i++) {
    n = (n << 8) | g[i];
  }
  return n;
}

String machineDataFrom({int? node, required String host, int? vol}) {
  final bagian = <String>[];
  if (node != null && node != 0 && (node & 0x010000000000) == 0) {
    bagian.add('mac=${node.toRadixString(16).padLeft(12, '0')}');
  }
  bagian.add('host=${host.toUpperCase()}');
  if (vol != null) bagian.add('vol=$vol');
  return bagian.join('|');
}

typedef _AllocNative = Pointer<Void> Function(Uint32, IntPtr);
typedef _AllocDart = Pointer<Void> Function(int, int);
typedef _FreeNative = Pointer<Void> Function(Pointer<Void>);
typedef _FreeDart = Pointer<Void> Function(Pointer<Void>);

/// Memori native lewat LocalAlloc (tanpa package:ffi).
T _withMem<T>(int bytes, T Function(Pointer<Void> p) f) {
  final k = DynamicLibrary.open('kernel32.dll');
  final alloc = k.lookupFunction<_AllocNative, _AllocDart>('LocalAlloc');
  final free = k.lookupFunction<_FreeNative, _FreeDart>('LocalFree');
  final p = alloc(0x40, bytes); // LMEM_ZEROINIT
  if (p == nullptr) throw StateError('LocalAlloc gagal');
  try {
    return f(p);
  } finally {
    free(p);
  }
}

int? _windowsNode() {
  try {
    final f = DynamicLibrary.open('rpcrt4.dll')
        .lookupFunction<_UuidNative, _UuidDart>('UuidCreateSequential');
    return _withMem(16, (p) {
      f(p.cast<Uint8>());
      return nodeFromGuid(p.cast<Uint8>().asTypedList(16));
    });
  } catch (_) {
    return null;
  }
}

int? _windowsVolume() {
  try {
    final f = DynamicLibrary.open('kernel32.dll')
        .lookupFunction<_VolNative, _VolDart>('GetVolumeInformationW');
    final drive = '${Platform.environment['SystemDrive'] ?? 'C:'}\\';
    return _withMem((drive.length + 1) * 2 + 8, (p) {
      final w = p.cast<Uint16>();
      w.asTypedList(drive.length + 1).setAll(0, [...drive.codeUnits, 0]);
      final serial = Pointer<Uint32>.fromAddress(p.address + (drive.length + 1) * 2 + 4 & ~3);
      final ok = f(w, nullptr, 0, serial, nullptr, nullptr, nullptr, 0);
      return ok != 0 ? serial.value : null;
    });
  } catch (_) {
    return null;
  }
}

/// Kode mesin perangkat ini ("XXXXX-XXXXX").
String machineCode() {
  final host = Platform.environment['COMPUTERNAME'] ?? Platform.localHostname;
  if (!Platform.isWindows) return machineCodeFrom(machineDataFrom(host: host));
  return machineCodeFrom(machineDataFrom(node: _windowsNode(), host: host, vol: _windowsVolume()));
}
