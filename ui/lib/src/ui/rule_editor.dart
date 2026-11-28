// Editor aturan target bintang (bagian rencana & aturan khusus game):
// tetap / pola / acak, plus pratinjau urutan berikutnya.
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
        return Text('ikut bagian', style: redup);
    }
    return StarRow(starsOfCode(rule.code), silver: silverOfCode(rule.code), size: size);
  }
}

/// Pilih satu target (platinum, 5..1) dari daftar; [onRemove] = baris Hapus.
class CodePicker extends StatelessWidget {
  const CodePicker({
    super.key,
    required this.code,
    required this.onChanged,
    required this.child,
    this.onRemove,
  });
  final int code;
  final ValueChanged<int> onChanged;
  final VoidCallback? onRemove;

  /// isi tombol pemicu
  final Widget child;

  static const opsi = [platinumCode, 5, 4, 3, 2, 1];

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Popover(
      alignRight: false,
      width: 196,
      trigger: (_, toggle, open) => Material(
        color: open ? c.surfaceContainerHighest : c.surfaceContainerHigh,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.sm),
          side: BorderSide(color: open ? c.primary : c.outlineVariant),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.sm),
          hoverColor: c.surfaceContainerHighest,
          onTap: toggle,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
            child: child,
          ),
        ),
      ),
      content: (_, close) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final o in opsi)
            InkWell(
              hoverColor: c.surfaceContainerHighest,
              onTap: () {
                onChanged(o);
                close();
              },
              child: Container(
                color: o == code ? c.surfaceContainerHighest : null,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(children: [
                  SizedBox(
                    width: 18,
                    child: Text('${starsOfCode(o)}',
                        style: t.titleSmall!.copyWith(
                            color: silverOfCode(o) ? silverStar : c.tertiary)),
                  ),
                  StarRow(starsOfCode(o), silver: silverOfCode(o), size: 16),
                  const Spacer(),
                  if (silverOfCode(o))
                    Text('platinum', style: t.labelSmall!.copyWith(color: silverStar)),
                ]),
              ),
            ),
          if (onRemove != null) ...[
            Divider(height: 12, color: c.outlineVariant),
            InkWell(
              hoverColor: c.surfaceContainerHighest,
              onTap: () {
                close();
                onRemove!();
              },
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(children: [
                  Icon(Icons.close_rounded, size: 16, color: c.error),
                  const SizedBox(width: 8),
                  Text('Hapus dari pola', style: t.labelLarge!.copyWith(color: c.error)),
                ]),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}

/// Editor satu aturan. [allowFollow] = ada pilihan 'Ikut bagian' (game).
/// Pratinjau: [seqKey] + [store] utk giliran terpakai & benih acak akun.
class RuleEditor extends StatefulWidget {
  const RuleEditor({
    super.key,
    required this.rule,
    required this.onChanged,
    required this.seqKey,
    required this.saved,
    required this.previewNoun,
    this.allowFollow = false,
  });
  final StarRule rule;
  final ValueChanged<StarRule> onChanged;
  final bool allowFollow;

  /// kunci urutan (sama dgn backend: `p<from>` / `g:balloon`)
  final String seqKey;

  /// aturan yang tersimpan sekarang (null = belum ada): kalau sama,
  /// pratinjau lanjut dari giliran yang sudah terpakai
  final StarRule? saved;

  /// "level berbintang" / "game balon" (teks pratinjau)
  final String previewNoun;

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
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final redup = t.bodySmall!.copyWith(color: c.onSurfaceVariant);
    final jenis = [
      if (widget.allowFollow) ('follow', 'Ikut bagian', Icons.subdirectory_arrow_right_rounded),
      ('fixed', 'Tetap', Icons.star_outline_rounded),
      ('pattern', 'Pola', Icons.repeat_rounded),
      ('random', 'Acak', Icons.shuffle_rounded),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SegmentedButton<String>(
        showSelectedIcon: false,
        segments: [
          for (final (k, label, ikon) in jenis)
            ButtonSegment(value: k, label: Text(label), icon: Icon(ikon, size: 16)),
        ],
        selected: {r.type},
        onSelectionChanged: (v) => _ubah((n) {
          n.type = v.first;
          // pola baru: mulai dari target tetap yang tadi dipilih
          if (n.type == 'pattern' && n.pattern.isEmpty) {
            n.pattern = [n.code];
            _teks.text = patternText(n.pattern);
          }
        }),
      ),
      const SizedBox(height: 14),
      AnimatedSize(
        duration: Motion.medium,
        curve: Motion.out,
        alignment: Alignment.topLeft,
        child: KeyedSubtree(
          key: ValueKey(r.type),
          child: switch (r.type) {
            'follow' => Text(
                'Tanpa aturan khusus: game ini ikut target bagian rencana atau target '
                'bintang tanpa rencana.',
                style: redup),
            'pattern' => _polaEditor(t, c, redup),
            'random' => _acakEditor(t, c, redup),
            _ => _tetapEditor(c),
          },
        ),
      ),
      if (r.variable) ...[
        const SizedBox(height: 16),
        _Preview(
            rule: r,
            seqKey: widget.seqKey,
            saved: widget.saved,
            noun: widget.previewNoun),
      ],
    ]);
  }

  Widget _tetapEditor(ColorScheme c) => Wrap(spacing: 6, runSpacing: 6, children: [
        for (final o in CodePicker.opsi)
          _Pilihan(
            selected: r.code == o,
            onTap: () => _ubah((n) => n.code = o),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              StarRow(starsOfCode(o), silver: silverOfCode(o), size: 14),
              if (silverOfCode(o)) ...[
                const SizedBox(width: 6),
                Text('platinum',
                    style: Theme.of(context).textTheme.labelSmall!.copyWith(color: silverStar)),
              ],
            ]),
          ),
      ]);

  Widget _polaEditor(TextTheme t, ColorScheme c, TextStyle redup) {
    final p = r.pattern;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
        for (final (i, code) in p.indexed)
          CodePicker(
            key: ValueKey('pola$i'),
            code: code,
            onChanged: (v) => _pola([...p]..[i] = v),
            onRemove: p.length > 1 ? () => _pola([...p]..removeAt(i)) : null,
            child: TargetBadge(code, size: 14),
          ),
        if (p.length < maxPatternLen)
          Tip(
            message: 'Tambah target (salinan yang terakhir)',
            child: IconButton.outlined(
              visualDensity: VisualDensity.compact,
              iconSize: 18,
              onPressed: () => _pola([...p, p.isEmpty ? 5 : p.last]),
              icon: const Icon(Icons.add_rounded),
            ),
          ),
      ]),
      const SizedBox(height: 12),
      SizedBox(
        width: 260,
        child: TextField(
          controller: _teks,
          style: t.bodyMedium!.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
          inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9pPlLaAtTiInNuUmM ,;/.-]'))],
          decoration: InputDecoration(
            isDense: true,
            labelText: 'Atau ketik polanya',
            hintText: '2, 4, 4, 3, 4',
            errorText: _teksSalah ? 'Pakai angka 1-5, p = platinum' : null,
          ),
          onChanged: (v) {
            final hasil = parsePattern(v);
            setState(() => _teksSalah = hasil == null);
            if (hasil != null && hasil.isNotEmpty) _pola(hasil, dariTeks: true);
          },
        ),
      ),
      const SizedBox(height: 6),
      Text('Diulang terus dari awal. Klik target untuk mengganti atau menghapusnya.',
          style: redup),
    ]);
  }

  Widget _acakEditor(TextTheme t, ColorScheme c, TextStyle redup) {
    Widget ujung(int code, ValueChanged<int> f) => CodePicker(
          code: code,
          onChanged: f,
          child: StarRow(starsOfCode(code), silver: silverOfCode(code), size: 14),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Text('Dari', style: t.bodyMedium),
        ujung(r.min, (v) => _ubah((n) {
              n.min = v;
              if (n.max < v) n.max = v;
            })),
        Text('sampai', style: t.bodyMedium),
        ujung(r.max, (v) => _ubah((n) {
              n.max = v;
              if (n.min > v) n.min = v;
            })),
      ]),
      const SizedBox(height: 6),
      Text('Tiap level dapat target acak di rentang ini. Acaknya beda di tiap akun.',
          style: redup),
    ]);
  }
}

/// Pilihan kotak (target tetap).
class _Pilihan extends StatelessWidget {
  const _Pilihan({required this.selected, required this.onTap, required this.child});
  final bool selected;
  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Press(
      child: Material(
        color: selected ? c.primary.withValues(alpha: 0.12) : c.surfaceContainerHigh,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.sm),
          side: BorderSide(color: selected ? c.primary : c.outlineVariant),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.sm),
          hoverColor: c.surfaceContainerHighest,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// "Berikutnya": urutan target yang akan dipakai.
class _Preview extends StatelessWidget {
  const _Preview(
      {required this.rule, required this.seqKey, required this.saved, required this.noun});
  final StarRule rule;
  final String seqKey;
  final StarRule? saved;
  final String noun;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final sig = rule.sig(seqKey);
    // aturan tidak berubah: lanjut dari giliran yang sudah dipakai
    final sama = saved != null && saved!.sig(seqKey) == sig;
    final mulai = sama ? s.usedFor(sig) : 0;
    const n = 12;
    final seed = '${s.seqAcct}|$sig';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: BoxDecoration(
        color: c.surfaceContainer,
        borderRadius: BorderRadius.circular(Radii.md),
        border: Border.all(color: c.outlineVariant),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(mulai > 0 ? 'Berikutnya (lanjut dari $noun ke-${mulai + 1})' : 'Urutannya nanti',
            style: t.labelMedium!.copyWith(color: c.onSurfaceVariant)),
        const SizedBox(height: 8),
        Wrap(spacing: 4, runSpacing: 8, children: [
          for (var i = 0; i < n; i++)
            SizedBox(
              width: 38,
              child: Column(children: [
                TargetBadge(rule.at(mulai + i, seed), size: 13),
                const SizedBox(height: 2),
                Text('${mulai + i + 1}',
                    style: t.labelSmall!.copyWith(
                        color: c.outline,
                        fontFeatures: const [FontFeature.tabularFigures()])),
              ]),
            ),
          SizedBox(
            width: 24,
            child: Text('…', style: t.labelMedium!.copyWith(color: c.outline)),
          ),
        ]),
        const SizedBox(height: 6),
        Text(
            noun.startsWith('game')
                ? 'Angka bawah = $noun ke-berapa.'
                : 'Angka bawah = $noun ke-berapa. Hanya yang dinilai bintang yang '
                    'dihitung, video & tutorial dilewati.',
            style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
      ]),
    );
  }
}
