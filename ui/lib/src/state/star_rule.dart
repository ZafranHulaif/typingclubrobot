// Aturan target bintang: bagian rencana & aturan khusus game. Dipakai
// backend (menentukan target level) dan UI (editor + pratinjau), jadi
// murni Dart tanpa Flutter.
//
// Kode target: 1-5 = bintang biasa, 6 = 5 bintang platinum.

const platinumCode = 6;

/// Pola paling panjang (lebih dari ini jarang berguna & sulit dibaca).
const maxPatternLen = 20;

/// Kode -> target mesin (0 = platinum / secepatnya, 1-5).
int engineTarget(int code) => code >= platinumCode ? 0 : code;

/// Target mesin -> kode.
int codeOf(int stars, bool silver) =>
    stars >= 5 && silver ? platinumCode : stars.clamp(1, 5);

int starsOfCode(int code) => code >= platinumCode ? 5 : code;
bool silverOfCode(int code) => code >= platinumCode;

/// Hash string stabil (sama di VM & web, tidak bergantung Random bawaan):
/// polinomial lalu diaduk xorshift supaya indeks berurutan tidak jadi
/// deret berurutan juga.
int stableHash(String s) {
  const m = 0xffffffff;
  var h = 7;
  for (final c in s.codeUnits) {
    h = (h * 31 + c) % 2147483647;
  }
  for (var i = 0; i < 3; i++) {
    h ^= (h << 13) & m;
    h ^= h >> 17;
    h ^= (h << 5) & m;
    h &= m;
  }
  return h;
}

class StarRule {
  StarRule({
    required this.type,
    this.code = platinumCode,
    List<int>? pattern,
    this.min = 3,
    this.max = 5,
  }) : pattern = pattern ?? <int>[];

  StarRule.fixed(int code) : this(type: 'fixed', code: code);

  /// aturan game 'ikut bagian' (tanpa aturan khusus)
  StarRule.follow() : this(type: 'follow');

  /// 'fixed' | 'pattern' | 'random' | 'follow' (game: ikut bagian/mode)
  String type;

  /// target 'fixed'
  int code;

  /// urutan target 'pattern'
  List<int> pattern;

  /// rentang 'random' (kode, min <= max)
  int min;
  int max;

  static int _code(Object? v, int dflt) =>
      v is num ? v.toInt().clamp(1, platinumCode) : dflt;

  /// Dari JSON tersimpan; format lama {stars, silver} = 'fixed'. Data
  /// rusak dirapikan (tanpa error).
  factory StarRule.fromJson(Map m) {
    final st = ((m['stars'] as num?) ?? 5).toInt().clamp(1, 5);
    final code = codeOf(st, m['silver'] == true);
    switch (m['rule']) {
      case 'follow':
        return StarRule.follow();
      case 'pattern':
        final pat = [
          for (final x in (m['pattern'] as List? ?? const [])) _code(x, 5),
        ].take(maxPatternLen).toList();
        if (pat.isNotEmpty) return StarRule(type: 'pattern', code: code, pattern: pat);
      case 'random':
        final a = _code(m['min'], 3), b = _code(m['max'], 5);
        return StarRule(type: 'random', code: code, min: a < b ? a : b, max: a < b ? b : a);
    }
    return StarRule.fixed(code);
  }

  Map<String, dynamic> toJson() => {
        'rule': type,
        // stars/silver tetap ditulis: versi lama membaca bagian ini sebagai
        // target tetap
        'stars': starsOfCode(code),
        'silver': silverOfCode(code),
        if (type == 'pattern') 'pattern': List<int>.from(pattern),
        if (type == 'random') ...{'min': min, 'max': max},
      };

  StarRule copy() =>
      StarRule(type: type, code: code, pattern: List<int>.from(pattern), min: min, max: max);

  bool get follow => type == 'follow';

  /// target berubah per level (perlu urutan tersimpan)
  bool get variable => type == 'pattern' || type == 'random';

  /// Tanda aturan: urutan mulai dari awal kalau aturannya berubah.
  String sig(String key) => '$key|$type|'
      '${switch (type) {
        'pattern' => pattern.join(','),
        'random' => '$min-$max',
        _ => '$code',
      }}';

  /// Target (kode) urutan ke-[idx] (0 = level berbintang pertama).
  /// [seed] = akun + tanda aturan: acaknya beda tiap akun.
  int at(int idx, String seed) => switch (type) {
        'pattern' => pattern[idx % pattern.length],
        'random' => min + stableHash('$seed#$idx') % (max - min + 1),
        _ => code,
      };

  bool sameAs(StarRule o) => sig('') == o.sig('');

  /// Ringkas untuk log: "pola 2,4,4,3,4", "acak 3-5", "4".
  String get label => switch (type) {
        'pattern' => 'pola ${pattern.map(codeLabel).join(',')}',
        'random' => 'acak ${codeLabel(min)}-${codeLabel(max)}',
        'follow' => 'ikut bagian',
        _ => codeLabel(code),
      };
}

/// "4" / "platinum".
String codeLabel(int code) => code >= platinumCode ? 'platinum' : '$code';

/// Pola dari teks ketikan: "2,4,4,3,4" / "2 4 4 3 4" / "p" = platinum.
/// null = ada bagian yang tidak bisa dibaca.
List<int>? parsePattern(String text) {
  final out = <int>[];
  for (final p in text.toLowerCase().split(RegExp(r'[\s,;/.-]+'))) {
    if (p.isEmpty) continue;
    if (p == 'p' || p == 'pl' || p == 'platinum') {
      out.add(platinumCode);
      continue;
    }
    // "24434" tanpa pemisah juga boleh
    if (RegExp(r'^[1-5]+$').hasMatch(p)) {
      out.addAll(p.split('').map(int.parse));
      continue;
    }
    return null;
  }
  return out.take(maxPatternLen).toList();
}

String patternText(List<int> pat) =>
    pat.map((c) => c >= platinumCode ? 'p' : '$c').join(', ');

/// Jenis game yang bisa diatur bintangnya (diuji live).
const gameKinds = ['balloon', 'monster'];

const gameNames = {'balloon': 'Game balon', 'monster': 'Game monster'};
