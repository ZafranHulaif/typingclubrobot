// Editor aturan target bintang (bagian rencana & aturan khusus game):
// tetap / pola / acak. Semua pilihan bintang memakai satu skala yang
// sama: 1 bintang di kiri, platinum di kanan.
import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'widgets/common.dart';

/// Satu target ringkas: angka + bintang (platinum = perak).
class TargetBadge extends StatelessWidget {
  const TargetBadge(this.code, {super.key, this.size = 13, this.dim = false});
  final int code;
  final double size;
  final bool dim;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final pl = silverOfCode(code);
    final warna = (pl ? silverStar : c.tertiary).withValues(alpha: dim ? 0.55 : 1);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Text('${starsOfCode(code)}',
          style: t.labelMedium!.copyWith(
              color: warna,
              fontSize: size,
              height: 1,
              fontFeatures: const [FontFeature.tabularFigures()])),
      Icon(Icons.star_rounded, size: size + 1, color: warna),
    ]);
  }
}

/// Ringkasan aturan untuk kotak bagian / kapsul.
class RuleSummary extends StatelessWidget {
  const RuleSummary(this.rule, {super.key, this.size = 15});
  final StarRule rule;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final redup = t.labelMedium!.copyWith(color: c.onSurfaceVariant);
    switch (rule.type) {
      case 'pattern':
        const maks = 5;
        final p = rule.pattern;
        return Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.repeat_rounded, size: size, color: c.onSurfaceVariant),
          const SizedBox(width: 4),
          for (final (i, code) in p.take(maks).indexed) ...[
            if (i > 0) Text('·', style: redup),
            TargetBadge(code, size: size - 3),
          ],
          if (p.length > maks) Text(' +${p.length - maks}', style: redup),
        ]);
      case 'random':
        return Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.shuffle_rounded, size: size, color: c.onSurfaceVariant),
          const SizedBox(width: 4),
          TargetBadge(rule.min, size: size - 3),
          Text(' – ', style: redup),
          TargetBadge(rule.max, size: size - 3),
        ]);
      case 'follow':
        return Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.subdirectory_arrow_right_rounded, size: size, color: c.outline),
          const SizedBox(width: 4),
          Text('ikut rencana', style: redup),
        ]);
    }
    return StarRow(starsOfCode(rule.code), silver: silverOfCode(rule.code), size: size);
  }
}

/// Skala target dari 1 bintang (kiri) sampai platinum (kanan). Satu
/// pilihan ([value]) atau rentang ([min]-[max], bisa digeser).
class StarScale extends StatefulWidget {
  const StarScale.single({super.key, required int this.value, required this.onChanged})
      : min = null,
        max = null,
        onRange = null;

  const StarScale.range({super.key, required int this.min, required int this.max, required this.onRange})
      : value = null,
        onChanged = null;

  final int? value;
  final ValueChanged<int>? onChanged;
  final int? min;
  final int? max;
  final void Function(int min, int max)? onRange;

  /// urutan kiri -> kanan
  static const codes = [1, 2, 3, 4, 5, platinumCode];

  @override
  State<StarScale> createState() => _StarScaleState();
}

class _StarScaleState extends State<StarScale> {
  /// ujung rentang yang sedang digeser: true = min
  bool? _ujungMin;
  int? _hover;

  bool get _range => widget.onRange != null;

  int _idx(double dx, double w) => (dx / w).floor().clamp(0, StarScale.codes.length - 1);

  void _pilih(int i, {bool mulaiGeser = false}) {
    final code = StarScale.codes[i];
    if (!_range) {
      if (code != widget.value) widget.onChanged!(code);
      return;
    }
    var a = widget.min!, b = widget.max!;
    if (mulaiGeser || _ujungMin == null) {
      // ujung terdekat; di luar rentang = ujung di sisi itu
      _ujungMin = code < a
          ? true
          : code > b
              ? false
              : (code - a) <= (b - code);
    }
    if (_ujungMin!) {
      a = code;
      if (a > b) {
        a = b;
        b = code;
        _ujungMin = false;
      }
    } else {
      b = code;
      if (b < a) {
        b = a;
        a = code;
        _ujungMin = true;
      }
    }
    if (a != widget.min || b != widget.max) widget.onRange!(a, b);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    const tinggi = 40.0;
    return LayoutBuilder(builder: (_, box) {
      final n = StarScale.codes.length;
      final w = (box.maxWidth.isFinite ? box.maxWidth : 6 * 52.0) / n;
      final lo = _range ? StarScale.codes.indexOf(widget.min!) : StarScale.codes.indexOf(widget.value!);
      final hi = _range ? StarScale.codes.indexOf(widget.max!) : lo;
      return MouseRegion(
        cursor: SystemMouseCursors.click,
        onHover: (e) {
          final i = _idx(e.localPosition.dx, w);
          if (i != _hover) setState(() => _hover = i);
        },
        onExit: (_) => setState(() => _hover = null),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapUp: (d) {
            _ujungMin = null;
            _pilih(_idx(d.localPosition.dx, w));
          },
          onHorizontalDragStart: (d) => _pilih(_idx(d.localPosition.dx, w), mulaiGeser: true),
          onHorizontalDragUpdate: (d) => _pilih(_idx(d.localPosition.dx, w)),
          onHorizontalDragEnd: (_) => _ujungMin = null,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SizedBox(
              height: tinggi,
              child: Stack(children: [
                // alur
                Positioned.fill(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: c.surfaceContainerHigh,
                      borderRadius: BorderRadius.circular(Radii.md),
                      border: Border.all(color: c.outlineVariant),
                    ),
                  ),
                ),
                // pilihan / rentang
                AnimatedPositioned(
                  duration: Motion.short,
                  curve: Motion.out,
                  left: lo * w,
                  width: (hi - lo + 1) * w,
                  top: 0,
                  bottom: 0,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: c.primary.withValues(alpha: 0.14),
                      borderRadius: BorderRadius.circular(Radii.md),
                      border: Border.all(color: c.primary, width: 1.5),
                    ),
                  ),
                ),
                Row(children: [
                  for (var i = 0; i < n; i++)
                    SizedBox(
                      width: w,
                      child: Center(
                        child: AnimatedScale(
                          duration: Motion.short,
                          curve: Motion.out,
                          scale: _hover == i ? 1.12 : 1,
                          child: TargetBadge(StarScale.codes[i],
                              size: 14, dim: i < lo || i > hi),
                        ),
                      ),
                    ),
                ]),
              ]),
            ),
            const SizedBox(height: 4),
            Row(children: [
              for (var i = 0; i < n; i++)
                SizedBox(
                  width: w,
                  child: Text(
                    i == n - 1 ? 'platinum' : '',
                    textAlign: TextAlign.center,
                    style: t.labelSmall!.copyWith(color: silverStar.withValues(alpha: 0.8)),
                  ),
                ),
            ]),
          ]),
        ),
      );
    });
  }
}

/// Kotak target kecil (pola): klik = skala bintang + hapus.
class CodePicker extends StatelessWidget {
  const CodePicker({
    super.key,
    required this.code,
    required this.onChanged,
    this.onRemove,
    this.index,
  });
  final int code;
  final ValueChanged<int> onChanged;
  final VoidCallback? onRemove;

  /// nomor urut kecil di pojok (pola)
  final int? index;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Popover(
      alignRight: false,
      width: 320,
      trigger: (_, toggle, open) => Press(
        child: Material(
          color: open ? c.primary.withValues(alpha: 0.14) : c.surfaceContainerHigh,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(Radii.md),
            side: BorderSide(color: open ? c.primary : c.outlineVariant),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(Radii.md),
            hoverColor: c.surfaceContainerHighest,
            onTap: toggle,
            child: SizedBox(
              width: 46,
              height: 44,
              child: Stack(children: [
                Center(child: TargetBadge(code, size: 14)),
                if (index != null)
                  Positioned(
                    left: 5,
                    top: 3,
                    child: Text('$index',
                        style: t.labelSmall!.copyWith(color: c.outline, fontSize: 9)),
                  ),
              ]),
            ),
          ),
        ),
      ),
      content: (_, close) => Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
          StarScale.single(
            value: code,
            onChanged: (v) {
              onChanged(v);
              close();
            },
          ),
          if (onRemove != null) ...[
            const SizedBox(height: 4),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                style: TextButton.styleFrom(foregroundColor: c.error),
                onPressed: () {
                  close();
                  onRemove!();
                },
                icon: const Icon(Icons.close_rounded, size: 16),
                label: const Text('Hapus dari pola'),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Editor satu aturan. [allowFollow] = ada pilihan 'Ikut rencana' (game).
class RuleEditor extends StatefulWidget {
  const RuleEditor({
    super.key,
    required this.rule,
    required this.onChanged,
    this.allowFollow = false,
    this.enabled = true,
    this.maxPattern,
  });
  final StarRule rule;
  final ValueChanged<StarRule> onChanged;
  final bool allowFollow;
  final bool enabled;

  /// panjang pola yang terpakai (= jumlah level bagian). Sisanya tetap
  /// disimpan di draf (tidak hilang kalau rentang tak sengaja dipendekkan),
  /// hanya disembunyikan. null = tanpa batas (sampai habis / game).
  final int? maxPattern;

  @override
  State<RuleEditor> createState() => _RuleEditorState();
}

class _RuleEditorState extends State<RuleEditor> {
  late final _teks = TextEditingController(text: patternText(widget.rule.pattern));
  bool _teksSalah = false;

  StarRule get r => widget.rule;

  void _ubah(void Function(StarRule) f) {
    final n = r.copy();
    f(n);
    widget.onChanged(n);
  }

  void _pola(List<int> p, {bool dariTeks = false}) {
    _ubah((n) => n.pattern = p);
    if (!dariTeks) {
      _teks.text = patternText(p);
      _teksSalah = false;
    }
  }

  @override
  void dispose() {
    _teks.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final jenis = [
      if (widget.allowFollow) ('follow', 'Ikut rencana', Icons.subdirectory_arrow_right_rounded),
      ('fixed', 'Tetap', Icons.star_outline_rounded),
      ('pattern', 'Pola', Icons.repeat_rounded),
      ('random', 'Acak', Icons.shuffle_rounded),
    ];
    return IgnorePointer(
      ignoring: !widget.enabled,
      child: AnimatedOpacity(
        duration: Motion.short,
        opacity: widget.enabled ? 1 : 0.6,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: [
              for (final (k, label, ikon) in jenis)
                ButtonSegment(value: k, label: Text(label), icon: Icon(ikon, size: 16)),
            ],
            selected: {r.type},
            onSelectionChanged: (v) => _ubah((n) {
              // dari 'ikut rencana': mulai dari 3 bintang, bukan platinum
              if (n.follow) n.code = 3;
              n.type = v.first;
              // pola baru: mulai dari target tetap yang tadi dipilih
              if (n.type == 'pattern' && n.pattern.isEmpty) {
                n.pattern = [n.code];
                _teks.text = patternText(n.pattern);
              }
            }),
          ),
          AnimatedSize(
            duration: Motion.medium,
            curve: Motion.out,
            alignment: Alignment.topLeft,
            child: KeyedSubtree(
              key: ValueKey(r.type),
              child: switch (r.type) {
                'follow' => const SizedBox(width: double.infinity),
                'pattern' => Padding(padding: const EdgeInsets.only(top: 14), child: _polaEditor()),
                'random' => Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: StarScale.range(
                      min: r.min,
                      max: r.max,
                      onRange: (a, b) => _ubah((n) => n
                        ..min = a
                        ..max = b),
                    ),
                  ),
                _ => Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: StarScale.single(value: r.code, onChanged: (v) => _ubah((n) => n.code = v)),
                  ),
              },
            ),
          ),
        ]),
      ),
    );
  }

  Widget _polaEditor() {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final p = r.pattern;
    final batas = math.min(widget.maxPattern ?? maxPatternLen, maxPatternLen);
    final tampil = math.min(p.length, batas);
    final sembunyi = p.length - tampil;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
        for (var i = 0; i < tampil; i++)
          CodePicker(
            key: ValueKey('pola$i'),
            code: p[i],
            index: i + 1,
            onChanged: (v) => _pola([...p]..[i] = v),
            onRemove: tampil > 1 ? () => _pola([...p]..removeAt(i)) : null,
          ),
        if (p.length < batas)
          Tip(
            message: 'Tambah target',
            child: SizedBox(
              width: 46,
              height: 44,
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  padding: EdgeInsets.zero,
                  side: BorderSide(color: c.outlineVariant),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(Radii.md)),
                ),
                onPressed: () => _pola([...p, p.isEmpty ? 5 : p.last]),
                child: const Icon(Icons.add_rounded, size: 18),
              ),
            ),
          ),
        if (sembunyi > 0)
          Tip(
            message: 'Rentang levelnya cuma $batas. $sembunyi target sisanya muncul lagi '
                'kalau rentangnya dipanjangkan (tidak ikut tersimpan).',
            child: Text('+$sembunyi',
                style: t.labelMedium!.copyWith(color: c.outline)),
          ),
      ]),
      const SizedBox(height: 12),
      SizedBox(
        width: 240,
        child: TextField(
          controller: _teks,
          style: t.bodyMedium!.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9pPlLaAtTiInNuUmM ,;/.-]'))],
          decoration: InputDecoration(
            isDense: true,
            prefixIcon: const Icon(Icons.keyboard_rounded, size: 18),
            hintText: 'Ketik pola: 2, 4, 4, 3, 4',
            errorText: _teksSalah ? 'Angka 1-5, p = platinum' : null,
          ),
          onChanged: (v) {
            final hasil = parsePattern(v);
            setState(() => _teksSalah = hasil == null);
            if (hasil != null && hasil.isNotEmpty) _pola(hasil, dariTeks: true);
          },
        ),
      ),
    ]);
  }
}

/// Urutan target berikutnya (aturan game pola/acak): kotak kecil + nomor.
class SeqStrip extends StatelessWidget {
  const SeqStrip({super.key, required this.rule, required this.seqKey, this.count = 10});
  final StarRule rule;
  final String seqKey;
  final int count;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final sig = rule.sig(seqKey);
    final mulai = s.usedFor(sig);
    final seed = '${s.seqAcct}|$sig';
    return Wrap(spacing: 4, runSpacing: 4, children: [
      for (var i = 0; i < count; i++)
        Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: i == 0 ? c.primary.withValues(alpha: 0.1) : c.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(Radii.sm),
            border: Border.all(color: i == 0 ? c.primary.withValues(alpha: 0.6) : c.outlineVariant),
          ),
          child: Stack(children: [
            Center(child: TargetBadge(rule.at(mulai + i, seed), size: 12)),
            Positioned(
              left: 4,
              top: 2,
              child: Text('${mulai + i + 1}',
                  style: t.labelSmall!.copyWith(color: c.outline, fontSize: 9)),
            ),
          ]),
        ),
    ]);
  }
}
