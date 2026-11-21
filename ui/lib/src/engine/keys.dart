// Tata letak keyboard US utk Input.dispatchKeyEvent, meniru tabel
// usKeyboardLayout milik Playwright (yang dipakai engine 3.5.x) supaya
// event yang sampai ke edclub sama persis: keyCode, code, key, text.

class KeyDef {
  const KeyDef(this.code, this.keyCode, this.key,
      {this.shiftKey, this.text, this.location = 0});
  final String code;
  final int keyCode;
  final String key;
  final String? shiftKey;
  final String? text;
  final int location;
}

/// Bit modifier CDP.
const modAlt = 1, modCtrl = 2, modMeta = 4, modShift = 8;

const _defs = <KeyDef>[
  KeyDef('Digit0', 48, '0', shiftKey: ')'),
  KeyDef('Digit1', 49, '1', shiftKey: '!'),
  KeyDef('Digit2', 50, '2', shiftKey: '@'),
  KeyDef('Digit3', 51, '3', shiftKey: '#'),
  KeyDef('Digit4', 52, '4', shiftKey: r'$'),
  KeyDef('Digit5', 53, '5', shiftKey: '%'),
  KeyDef('Digit6', 54, '6', shiftKey: '^'),
  KeyDef('Digit7', 55, '7', shiftKey: '&'),
  KeyDef('Digit8', 56, '8', shiftKey: '*'),
  KeyDef('Digit9', 57, '9', shiftKey: '('),
  KeyDef('Minus', 189, '-', shiftKey: '_'),
  KeyDef('Equal', 187, '=', shiftKey: '+'),
  KeyDef('BracketLeft', 219, '[', shiftKey: '{'),
  KeyDef('BracketRight', 221, ']', shiftKey: '}'),
  KeyDef('Backslash', 220, r'\', shiftKey: '|'),
  KeyDef('Semicolon', 186, ';', shiftKey: ':'),
  KeyDef('Quote', 222, "'", shiftKey: '"'),
  KeyDef('Backquote', 192, '`', shiftKey: '~'),
  KeyDef('Comma', 188, ',', shiftKey: '<'),
  KeyDef('Period', 190, '.', shiftKey: '>'),
  KeyDef('Slash', 191, '/', shiftKey: '?'),
  KeyDef('Space', 32, ' '),
  KeyDef('Enter', 13, 'Enter', text: '\r'),
  KeyDef('Tab', 9, 'Tab'),
  KeyDef('Backspace', 8, 'Backspace'),
  KeyDef('Escape', 27, 'Escape'),
  KeyDef('Delete', 46, 'Delete'),
  KeyDef('Insert', 45, 'Insert'),
  KeyDef('Home', 36, 'Home'),
  KeyDef('End', 35, 'End'),
  KeyDef('PageUp', 33, 'PageUp'),
  KeyDef('PageDown', 34, 'PageDown'),
  KeyDef('ArrowLeft', 37, 'ArrowLeft'),
  KeyDef('ArrowUp', 38, 'ArrowUp'),
  KeyDef('ArrowRight', 39, 'ArrowRight'),
  KeyDef('ArrowDown', 40, 'ArrowDown'),
  KeyDef('ShiftLeft', 16, 'Shift', location: 1),
  KeyDef('ShiftRight', 16, 'Shift', location: 2),
  KeyDef('ControlLeft', 17, 'Control', location: 1),
  KeyDef('ControlRight', 17, 'Control', location: 2),
  KeyDef('AltLeft', 18, 'Alt', location: 1),
  KeyDef('AltRight', 18, 'Alt', location: 2),
  KeyDef('MetaLeft', 91, 'Meta', location: 1),
  KeyDef('MetaRight', 92, 'Meta', location: 2),
  KeyDef('CapsLock', 20, 'CapsLock'),
];

final Map<String, KeyDef> _byName = () {
  final m = <String, KeyDef>{};
  for (var i = 0; i < 26; i++) {
    final lo = String.fromCharCode(97 + i);
    final up = String.fromCharCode(65 + i);
    final d = KeyDef('Key$up', 65 + i, lo, shiftKey: up);
    m['Key$up'] = d;
    m[lo] = d;
    m[up] = d;
  }
  for (final d in _defs) {
    m[d.code] = d;
    // kunci kiri jadi wakil nama ('Shift' -> ShiftLeft)
    m.putIfAbsent(d.key, () => d);
  }
  for (final d in _defs) {
    if (d.shiftKey != null) m.putIfAbsent(d.shiftKey!, () => d);
  }
  m['\n'] = m['Enter']!;
  m['\r'] = m['Enter']!;
  m['\t'] = m['Tab']!;
  return m;
}();

/// Deskripsi lengkap satu tombol, sudah memperhitungkan modifier aktif.
class KeyDesc {
  KeyDesc(this.code, this.keyCode, this.key, this.text, this.location);
  final String code;
  final int keyCode;
  final String key;
  final String text;
  final int location;
}

KeyDef? keyDef(String name) => _byName[name];

/// Seperti Keyboard._keyDescriptionForString milik Playwright.
KeyDesc? describeKey(String name, int modifiers) {
  final d = _byName[name];
  if (d == null) return null;
  var key = d.key;
  var text = d.text ?? (d.key.length == 1 ? d.key : '');
  // nama yang diminta = varian shift ('A', '!')
  if (d.shiftKey != null && name == d.shiftKey) {
    key = d.shiftKey!;
    text = d.shiftKey!;
  }
  if ((modifiers & modShift) != 0 && d.shiftKey != null) {
    key = d.shiftKey!;
    text = d.shiftKey!;
  }
  // modifier selain shift -> tanpa teks
  if ((modifiers & ~modShift) != 0) text = '';
  return KeyDesc(d.code, d.keyCode, key, text, d.location);
}

int modifierBit(String key) => switch (key) {
      'Alt' => modAlt,
      'Control' => modCtrl,
      'Meta' => modMeta,
      'Shift' => modShift,
      _ => 0,
    };
