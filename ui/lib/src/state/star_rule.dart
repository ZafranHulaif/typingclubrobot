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

  /// aturan game 'ikut rencana' (tanpa aturan khusus)
  StarRule.follow() : this(type: 'follow');

  /// 'fixed' | 'pattern' | 'random' | 'follow' (game: ikut rencana)
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
        'follow' => 'ikut rencana',
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

// ------------------------------------------------------------ peta level
/// Jenis level yang dinilai bintang & bisa diatur (memakai giliran pola).
const scoredKinds = {'star', 'balloon', 'monster'};

/// Jenis level yang dilewati tanpa giliran: video, tutorial, tes/objektif,
/// tahan tombol, game lain (belum bisa diatur), premium (terkunci Pro).
/// 'free' = catatan lama (sebelum jenisnya dirinci).
const skipKinds = {'free', 'video', 'tutorial', 'test', 'hold', 'game', 'premium'};

bool isSkipKind(String k) => skipKinds.contains(k);

/// Satu kotak di peta level editor rencana.
class LevelCell {
  const LevelCell({
    required this.level,
    required this.kind,
    this.code,
    this.idx,
    this.assigned = false,
    this.game,
    this.done = false,
    this.planned,
    this.title,
  });
  final int level;

  /// jenis dari katalog: [scoredKinds] / [skipKinds]; '' = level belum
  /// pernah dibuka (dianggap berbintang)
  final String kind;

  /// sudah selesai di akun ini ([code] = bintang hasilnya / targetnya)
  final bool done;

  /// level selesai: target menurut aturan sekarang (kalau diulang)
  final int? planned;

  /// target (kode) level ini; null = tanpa target (video, tutorial, dll.)
  final int? code;

  /// giliran ke-berapa di urutannya (0 = pertama); null = aturan tetap /
  /// tanpa giliran
  final int? idx;

  /// giliran sudah tersimpan (level ini pernah dibuka dgn aturan ini)
  final bool assigned;

  /// game yang ikut aturan khusus game ('balloon' / 'monster')
  final String? game;

  /// judul lesson dari daftar level edclub (mis. 'Keys f & j'), kalau
  /// sudah terbaca
  final String? title;

  bool get known => kind.isNotEmpty;
  bool get skip => isSkipKind(kind);

  /// selesai tapi edclub tidak memberi bintang ('Lesson completed'):
  /// level tanpa bintang (video, tutorial, dll.) yang jenisnya belum
  /// pernah dilihat bot
  bool get noStar => done && code == null && !skip;
}

/// Hasil level selesai dari snapshot {level: {c: target, e: bintang
/// asli}} -> kode (bintang asli didahulukan).
int? doneCode(Map? done, int level) {
  final m = done?['$level'];
  if (m is! Map) return null;
  final e = m['e'], c = m['c'];
  if (e is num && e > 0) return e.toInt().clamp(1, platinumCode);
  if (c is num && c > 0) return c.toInt();
  return 0; // selesai tanpa bintang tercatat
}

/// Urutan (tanda aturan) tersimpan: giliran berikutnya + giliran per level.
({int n, Map<int, int> lv}) seqState(Map? seq, String sig) {
  final m = (seq?[sig] as Map?) ?? const {};
  final lv = <int, int>{};
  ((m['lv'] as Map?) ?? const {}).forEach((k, v) {
    final l = int.tryParse('$k');
    if (l != null && v is num) lv[l] = v.toInt();
  });
  return (n: ((m['n'] as num?) ?? 0).toInt(), lv: lv);
}

/// Peta level satu bagian rencana: target tiap level dari [from], sama
/// dgn cara backend membagi giliran. Level tersimpan pakai gilirannya;
/// level baru mengambil giliran berikutnya berurutan, kecuali yang di
/// [kinds] tercatat 'free' (tidak memakai giliran) dan game yang punya
/// aturan khusus di [games] (urutannya sendiri).
List<LevelCell> levelMap({
  required int from,
  required int to,
  required int lastLevel,
  required StarRule rule,
  required String key,
  required String acct,
  required Map kinds,
  required Map? seq,
  Map<String, StarRule> games = const {},
  Map? done,
  int start = 0,
  int count = 30,
}) {
  final sig = rule.sig(key);
  final st = seqState(seq, sig);
  var n = st.n;
  // game dgn aturan khusus: giliran masing2
  final gs = {
    for (final e in games.entries)
      if (!e.value.follow) e.key: (e.value, e.value.sig('g:${e.key}'), seqState(seq, e.value.sig('g:${e.key}'))),
  };
  final gn = {for (final e in gs.entries) e.key: e.value.$3.n};
  final akhir = to == 0 ? lastLevel : to;
  final mulai = start < from ? from : start;
  final out = <LevelCell>[];
  for (var l = from; l <= akhir && out.length < count; l++) {
    final kind = '${kinds['$l'] ?? ''}';
    final dc = doneCode(done, l);
    // selesai tanpa bintang & belum pernah dapat giliran: level tanpa
    // bintang yg dikerjakan di luar bot, tidak memakai giliran
    final tanpaGiliran = dc == 0;
    LevelCell cell;
    final g = gs[kind];
    if (isSkipKind(kind)) {
      cell = LevelCell(level: l, kind: kind);
    } else if (g != null) {
      final (gr, gsig, gst) = g;
      final simpan = gst.lv[l];
      final i = gr.variable ? (simpan ?? (tanpaGiliran ? null : gn[kind]!)) : null;
      if (gr.variable && simpan == null && !tanpaGiliran) gn[kind] = gn[kind]! + 1;
      cell = LevelCell(
          level: l,
          kind: kind,
          code: i == null ? gr.code : gr.at(i, '$acct|$gsig'),
          idx: i,
          assigned: simpan != null,
          game: kind);
    } else {
      final simpan = st.lv[l];
      final i = rule.variable ? (simpan ?? (tanpaGiliran ? null : n)) : null;
      if (rule.variable && simpan == null && !tanpaGiliran) n++;
      cell = LevelCell(
          level: l,
          kind: kind,
          code: i == null ? rule.code : rule.at(i, '$acct|$sig'),
          idx: i,
          assigned: simpan != null);
    }
    // sudah selesai: tampilkan hasilnya, bukan target aturan sekarang
    if (dc != null) {
      final t = (done?['$l'] as Map?)?['t'];
      cell = LevelCell(
          level: l,
          kind: cell.kind,
          code: dc == 0 ? null : dc,
          idx: cell.idx,
          assigned: cell.assigned,
          game: cell.game,
          done: true,
          planned: cell.code,
          title: t is String && t.isNotEmpty ? t : null);
    }
    if (l >= mulai) out.add(cell);
  }
  return out;
}
