// Lembar editor rencana: terbuka di samping panel Rencana (menimpa
// halaman). Kiri: rentang level & target. Kanan: peta level (kotak per
// level dgn targetnya), level yang sedang jalan jadi yang utama.
//
// Tiga rasa, isi sama: bagian baru (aksen hijau, "Tambahkan"), ubah
// bagian (netral, "Simpan perubahan"), sedang jalan (hanya lihat).
import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'rule_editor.dart';
import 'widgets/common.dart';
import 'widgets/web_layer.dart';

class PlanEditorSheet extends StatelessWidget {
  const PlanEditorSheet({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final e = s.planOpen ? s.edit : null;
    return AnimatedSwitcher(
      duration: Motion.medium,
      reverseDuration: Motion.short,
      switchInCurve: Motion.out,
      transitionBuilder: (child, a) => FadeTransition(
        opacity: a,
        child: SlideTransition(
          position: Tween(begin: const Offset(-0.02, 0), end: Offset.zero).animate(a),
          child: child,
        ),
      ),
      child: e == null
          ? const SizedBox.shrink(key: ValueKey('tutup'))
          : WebHole(
              key: ValueKey(e),
              child: e.games ? const _GamesForm() : _SegmentForm(edit: e),
            ),
    );
  }
}

enum _Feel { create, edit, view, games }

/// Kerangka lembar: kepala (beda rasa per mode) + isi + tombol bawah.
class _Frame extends StatelessWidget {
  const _Frame({
    required this.feel,
    required this.title,
    required this.body,
    required this.footer,
    this.badge,
  });
  final _Feel feel;
  final String title;
  final Widget body;
  final List<Widget> footer;

  /// tanda kecil di samping judul ("belum disimpan" / "sedang jalan")
  final Widget? badge;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final baru = feel == _Feel.create;
    final jalan = feel == _Feel.view;
    final (IconData ikon, Color latar, Color warna) = switch (feel) {
      _Feel.create => (Icons.add_rounded, c.primary, c.onPrimary),
      _Feel.edit => (Icons.edit_rounded, c.surfaceContainerHighest, c.onSurface),
      _Feel.view => (Icons.play_arrow_rounded, c.primary.withValues(alpha: 0.18), c.primary),
      _Feel.games => (Icons.sports_esports_rounded, c.surfaceContainerHighest, c.onSurface),
    };
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(
            color: baru || jalan ? c.primary.withValues(alpha: 0.55) : c.outlineVariant),
      ),
      child: Shortcuts(
        shortcuts: const {SingleActivator(LogicalKeyboardKey.escape): DismissIntent()},
        child: Actions(
          actions: {
            DismissIntent: CallbackAction<DismissIntent>(onInvoke: (_) => s.openEdit(null)),
          },
          child: FocusScope(
            autofocus: true,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Container(
                color: baru ? c.primary.withValues(alpha: 0.07) : null,
                padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
                child: Row(children: [
                  Container(
                    width: 30,
                    height: 30,
                    decoration: BoxDecoration(color: latar, shape: BoxShape.circle),
                    child: Icon(ikon, size: 18, color: warna),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Row(children: [
                      Flexible(
                        child: Text(title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: t.titleMedium!.copyWith(
                                fontFeatures: const [FontFeature.tabularFigures()])),
                      ),
                      if (badge != null) ...[const SizedBox(width: 10), badge!],
                    ]),
                  ),
                  Tip(
                    message: 'Tutup (Esc)',
                    child: IconButton(
                      onPressed: () => s.openEdit(null),
                      icon: const Icon(Icons.close_rounded, size: 20),
                    ),
                  ),
                ]),
              ),
              Divider(height: 1, color: baru ? c.primary.withValues(alpha: 0.3) : c.outlineVariant),
              Expanded(child: body),
              Divider(height: 1, color: c.outlineVariant),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
                child: Row(children: footer),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// Tanda kecil berbentuk pil di kepala lembar.
class _Pill extends StatelessWidget {
  const _Pill(this.text, {required this.color, this.dot = false});
  final String text;
  final Color color;
  final bool dot;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (dot) ...[StatusDot(color: color, pulse: true), const SizedBox(width: 6)],
        Text(text, style: t.labelSmall!.copyWith(color: color)),
      ]),
    );
  }
}

/// Hapus dua langkah (klik lagi untuk yakin).
class _ConfirmButton extends StatefulWidget {
  const _ConfirmButton({required this.onConfirm});
  final VoidCallback onConfirm;
  @override
  State<_ConfirmButton> createState() => _ConfirmButtonState();
}

class _ConfirmButtonState extends State<_ConfirmButton> {
  bool _armed = false;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return TextButton.icon(
      style: TextButton.styleFrom(foregroundColor: c.error),
      onPressed: () {
        if (_armed) {
          widget.onConfirm();
          return;
        }
        setState(() => _armed = true);
        Future<void>.delayed(const Duration(seconds: 3), () {
          if (mounted) setState(() => _armed = false);
        });
      },
      icon: const Icon(Icons.delete_outline_rounded, size: 18),
      label: Text(_armed ? 'Yakin hapus?' : 'Hapus'),
    );
  }
}

/// Judul bagian kecil di dalam lembar.
class _Label extends StatelessWidget {
  const _Label(this.text, {this.icon, this.trailing});
  final String text;
  final IconData? icon;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(children: [
        if (icon != null) ...[
          Icon(icon, size: 16, color: c.onSurfaceVariant),
          const SizedBox(width: 6),
        ],
        Text(text, style: t.labelLarge!.copyWith(color: c.onSurface)),
        if (trailing != null) ...[const Spacer(), trailing!],
      ]),
    );
  }
}

// ------------------------------------------------------------- bagian
class _SegmentForm extends StatefulWidget {
  const _SegmentForm({required this.edit});
  final PlanEdit edit;
  @override
  State<_SegmentForm> createState() => _SegmentFormState();
}

class _SegmentFormState extends State<_SegmentForm> {
  late final Segment _sg = widget.edit.seg!.copy();
  late final _a = TextEditingController(text: '${_sg.from}');
  late final _b = TextEditingController(text: _sg.to == 0 ? '' : '${_sg.to}');
  late bool _habis = _sg.to == 0;

  @override
  void initState() {
    super.initState();
    // peta level ikut angka yang sedang diketik
    _a.addListener(_ulang);
    _b.addListener(_ulang);
  }

  void _ulang() => setState(() {});

  @override
  void dispose() {
    _a.dispose();
    _b.dispose();
    super.dispose();
  }

  bool get _isFirst {
    final e = widget.edit;
    final segs = StoreScope.read(context).segments;
    return e.isNew ? segs.isEmpty || e.gap == 0 : e.index == 0;
  }

  Segment? _saved(AppStore s) {
    final i = widget.edit.index;
    return i != null && i < s.segments.length ? s.segments[i] : null;
  }

  int? get _from => int.tryParse(_a.text.trim());
  int? get _to => _habis ? 0 : int.tryParse(_b.text.trim());

  /// jumlah level bagian ini (null = sampai habis / belum valid)
  int? get _levels {
    final a = _from, b = _to;
    if (a == null || b == null || b == 0 || b < a) return null;
    return b - a + 1;
  }

  /// aturan yang benar2 dipakai: pola dipotong sepanjang rentang level
  /// (draf lengkapnya tetap di _sg selama lembar terbuka)
  StarRule get _rule {
    final n = _levels;
    final r = _sg.rule;
    if (r.type != 'pattern' || n == null || r.pattern.length <= n) return r;
    return r.copy()..pattern = r.pattern.take(n).toList();
  }

  bool _dirty(Segment? saved) =>
      saved == null ||
      _from != saved.from ||
      _to != saved.to ||
      !_rule.sameAs(saved.rule);

  Future<void> _simpan(AppStore s) async {
    final a = _from;
    final b = _to;
    if (a == null) {
      s.say('Isi level awal dengan angka ya.', error: true);
      return;
    }
    if (b == null) {
      s.say('Isi sampai level berapa, atau centang "Sampai habis".', error: true);
      return;
    }
    if (a < 1 || a > AppStore.lastLevel || b > AppStore.lastLevel) {
      s.say('Level 1 sampai ${AppStore.lastLevel} ya.', error: true);
      return;
    }
    if (b != 0 && b < a) {
      s.say('Level akhir harus sesudah level awal.', error: true);
      return;
    }
    // hanya bagian pertama yg harus mulai di level terbuka; sisanya
    // terbuka sendiri selagi bot jalan
    if (_isFirst && s.unlocked > 0 && a > s.unlocked) {
      s.say('Level $a belum terbuka. Level terbuka terakhir: ${s.unlocked}.', error: true);
      return;
    }
    _sg
      ..rule = _rule
      ..from = a
      ..to = b;
    final segs = s.segments;
    final i = widget.edit.index;
    if (i == null) {
      segs.add(_sg);
    } else {
      if (i >= segs.length) return;
      segs[i] = _sg;
    }
    // bagian pengisi celah masuk di tengah: urutkan
    segs.sort((x, y) => x.from.compareTo(y.from));
    if (await s.savePlan(segs)) s.openEdit(null);
  }

  Future<void> _hapus(AppStore s) async {
    final i = widget.edit.index;
    if (i == null) return;
    final l = s.segments;
    if (i >= l.length) return;
    l.removeAt(i);
    if (await s.savePlan(l)) s.openEdit(null);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final e = widget.edit;
    final saved = _saved(s);
    // bagian yang sedang dikerjakan: hanya dilihat
    final lihat = saved != null && s.locked(saved);
    final aktif = lihat && s.activeSegment == e.index;
    final feel = e.isNew ? _Feel.create : (lihat ? _Feel.view : _Feel.edit);
    final dirty = !lihat && _dirty(saved);

    Widget angka(TextEditingController ctl, String label, {bool fokus = false}) => SizedBox(
          width: 104,
          child: TextField(
            controller: ctl,
            enabled: !lihat,
            autofocus: fokus,
            style: t.bodyLarge!.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(3),
            ],
            onSubmitted: (_) => _simpan(s),
            decoration: InputDecoration(labelText: label, isDense: true),
          ),
        );

    final form = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const _Label('Level', icon: Icons.format_list_numbered_rounded),
      Row(children: [
        angka(_a, 'Dari', fokus: e.isNew),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Icon(Icons.arrow_forward_rounded, size: 16, color: c.outline),
        ),
        AnimatedSwitcher(
          duration: Motion.short,
          child: _habis
              ? Container(
                  key: const ValueKey('habis'),
                  width: 104,
                  height: 48,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(Radii.md),
                    border: Border.all(color: c.outlineVariant),
                  ),
                  child: Text('${AppStore.lastLevel}',
                      style: t.bodyLarge!.copyWith(color: c.onSurfaceVariant)),
                )
              : KeyedSubtree(key: const ValueKey('sampai'), child: angka(_b, 'Sampai')),
        ),
      ]),
      const SizedBox(height: 6),
      InkWell(
        borderRadius: BorderRadius.circular(Radii.sm),
        onTap: lihat ? null : () => setState(() => _habis = !_habis),
        child: Padding(
          padding: const EdgeInsets.only(right: 8),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Checkbox(
              value: _habis,
              visualDensity: VisualDensity.compact,
              onChanged: lihat ? null : (v) => setState(() => _habis = v ?? false),
            ),
            Text('Sampai habis', style: t.bodyMedium),
          ]),
        ),
      ),
      const SizedBox(height: 18),
      const _Label('Target bintang', icon: Icons.star_rounded),
      RuleEditor(
        rule: _sg.rule,
        maxPattern: _levels,
        enabled: !lihat,
        onChanged: (r) => setState(() => _sg.rule = r),
      ),
    ]);

    final from = _from;
    final to = _to;
    final peta = from == null || from < 1 || from > AppStore.lastLevel
        ? null
        : _LevelMap(
            from: from,
            to: to == null || (to != 0 && to < from) ? from : to,
            rule: _rule,
            current: aktif && s.levelNum >= from ? s.levelNum : 0,
          );

    final judul = e.isNew
        ? 'Bagian baru'
        : 'Bagian ${saved?.label ?? ''}';

    return _Frame(
      feel: feel,
      title: judul,
      badge: lihat
          ? _Pill(aktif ? 'Sedang jalan' : 'Segera jalan', color: c.primary, dot: aktif)
          : (!e.isNew && dirty ? _Pill('Belum disimpan', color: c.tertiary) : null),
      body: LayoutBuilder(builder: (_, box) {
        final lebar = box.maxWidth >= 620;
        if (!lebar) {
          return ListView(padding: const EdgeInsets.fromLTRB(20, 18, 20, 24), children: [
            form,
            if (peta != null) ...[const SizedBox(height: 22), peta],
          ]);
        }
        return Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SizedBox(
            width: math.min(360, box.maxWidth * 0.46),
            child: ListView(padding: const EdgeInsets.fromLTRB(20, 18, 16, 24), children: [form]),
          ),
          VerticalDivider(width: 1, color: c.outlineVariant),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 18, 18, 24),
              children: [?peta],
            ),
          ),
        ]);
      }),
      footer: switch (feel) {
        _Feel.view => [
            Icon(Icons.lock_outline_rounded, size: 16, color: c.onSurfaceVariant),
            const SizedBox(width: 8),
            Expanded(
              child: Text('Stop dulu untuk mengubah bagian ini.',
                  style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
            ),
            TextButton(onPressed: () => s.openEdit(null), child: const Text('Tutup')),
          ],
        _Feel.create => [
            const Spacer(),
            TextButton(onPressed: () => s.openEdit(null), child: const Text('Batal')),
            const SizedBox(width: 6),
            Press(
              child: FilledButton.icon(
                onPressed: () => _simpan(s),
                icon: const Icon(Icons.add_rounded, size: 18),
                label: const Text('Tambahkan'),
              ),
            ),
          ],
        _ => [
            _ConfirmButton(onConfirm: () => _hapus(s)),
            const Spacer(),
            TextButton(onPressed: () => s.openEdit(null), child: const Text('Batal')),
            const SizedBox(width: 6),
            Press(
              enabled: dirty,
              child: FilledButton(
                onPressed: dirty ? () => _simpan(s) : null,
                child: const Text('Simpan perubahan'),
              ),
            ),
          ],
      },
    );
  }
}

// ------------------------------------------------------------- peta level
/// Kotak per level dgn targetnya, mulai dari level awal bagian. Saat
/// bagian ini jalan, level sekarang jadi yang utama.
class _LevelMap extends StatelessWidget {
  const _LevelMap({
    required this.from,
    required this.to,
    required this.rule,
    required this.current,
  });
  final int from;

  /// 0 = sampai habis
  final int to;
  final StarRule rule;

  /// level yang sedang dikerjakan (0 = bagian ini tidak sedang jalan)
  final int current;

  static const _kotak = 50.0;
  static const _jarak = 6.0;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final akhir = to == 0 ? AppStore.lastLevel : to;
    final jalan = current >= from && current <= akhir;
    return LayoutBuilder(builder: (_, box) {
      final kolom = math.max(4, ((box.maxWidth + _jarak) / (_kotak + _jarak)).floor());
      // kotak melebar sedikit supaya baris pas selebar kolom
      final ukuran = ((box.maxWidth - (kolom - 1) * _jarak) / kolom).clamp(_kotak, 64.0);
      final baris = jalan ? 5 : 6;
      final muat = kolom * baris;
      // jalan: mulai sedikit sebelum level sekarang
      final mulai = jalan ? math.max(from, current - 2) : from;
      final sel = levelMap(
        from: from,
        to: to,
        lastLevel: AppStore.lastLevel,
        rule: rule,
        key: 'p$from',
        acct: s.seqAcct,
        kinds: s.catalog,
        seq: s.seq,
        games: s.gameRules,
        start: mulai,
        count: muat,
      );
      final sisa = akhir - (sel.isEmpty ? mulai - 1 : sel.last.level);
      final adaLewat = sel.any((x) => x.kind == 'free');
      final adaGame = sel.any((x) => x.game != null || gameKinds.contains(x.kind));
      final adaBaru = sel.any((x) => !x.known);
      final kini = jalan ? sel.where((x) => x.level == current).firstOrNull : null;
      final cur = s.curTarget;
      final kodeKini = cur != null && cur['level'] == current
          ? (cur['code'] as num).toInt()
          : kini?.code;

      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _Label('Peta level',
            icon: Icons.grid_view_rounded,
            trailing: Text(to == 0 ? '$from sampai habis' : (from == akhir ? '$from' : '$from–$akhir'),
                style: t.labelMedium!.copyWith(
                    color: c.onSurfaceVariant,
                    fontFeatures: const [FontFeature.tabularFigures()]))),
        if (jalan) ...[
          _NowCard(level: current, code: kodeKini, cell: kini),
          const SizedBox(height: 12),
        ],
        Wrap(spacing: _jarak, runSpacing: _jarak, children: [
          for (final x in sel)
            _LevelSquare(
              cell: x,
              size: ukuran,
              // level sekarang: target yang benar2 dipakai bot
              code: jalan && x.level == current ? kodeKini : x.code,
              now: jalan && x.level == current,
              done: jalan && x.level < current,
              first: x.level == from && !jalan,
            ),
        ]),
        if (sisa > 0) ...[
          const SizedBox(height: 8),
          Text('+$sisa level lagi',
              style: t.labelMedium!.copyWith(color: c.onSurfaceVariant)),
        ],
        const SizedBox(height: 14),
        Wrap(spacing: 14, runSpacing: 6, children: [
          if (adaLewat) _Legend(icon: Icons.skip_next_rounded, text: 'dilewati'),
          if (adaGame) _Legend(icon: Icons.sports_esports_rounded, text: 'game'),
          if (adaBaru) const _Legend(hollow: true, text: 'belum pernah dibuka'),
        ]),
      ]);
    });
  }
}

/// Kartu "sekarang": level yang sedang dikerjakan & targetnya.
class _NowCard extends StatelessWidget {
  const _NowCard({required this.level, required this.code, required this.cell});
  final int level;
  final int? code;
  final LevelCell? cell;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final lewat = cell?.kind == 'free';
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 16, 12),
      decoration: BoxDecoration(
        color: c.primary.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: c.primary, width: 1.5),
      ),
      child: Row(children: [
        StatusDot(color: c.primary, pulse: true),
        const SizedBox(width: 12),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Sekarang', style: t.labelSmall!.copyWith(color: c.primary)),
          Text('Level $level',
              style: t.titleLarge!.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
        ]),
        const Spacer(),
        if (lewat)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.skip_next_rounded, size: 18, color: c.onSurfaceVariant),
            const SizedBox(width: 4),
            Text('tanpa bintang', style: t.labelMedium!.copyWith(color: c.onSurfaceVariant)),
          ])
        else if (code != null)
          StarRow(starsOfCode(code!), silver: silverOfCode(code!), size: 20),
      ]),
    );
  }
}

class _LevelSquare extends StatelessWidget {
  const _LevelSquare({
    required this.cell,
    required this.size,
    required this.code,
    this.now = false,
    this.done = false,
    this.first = false,
  });
  final LevelCell cell;
  final double size;
  final int? code;
  final bool now;
  final bool done;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final x = cell;
    final lewat = x.kind == 'free';
    final game = x.game != null || gameKinds.contains(x.kind);
    final pesan = [
      'Level ${x.level}',
      if (lewat)
        'dilewati, tanpa bintang'
      else if (code != null)
        'target ${codeLabel(code!)}${code! < platinumCode ? ' bintang' : ''}',
      if (x.game != null) 'aturan ${gameNames[x.game]!.toLowerCase()}',
      if (x.idx != null && !lewat) 'urutan ke-${x.idx! + 1}',
      if (!x.known) 'belum pernah dibuka',
    ].join(' · ');
    return Tip(
      message: pesan,
      child: AnimatedOpacity(
        duration: Motion.medium,
        opacity: done ? 0.4 : 1,
        child: AnimatedContainer(
          duration: Motion.short,
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: now
                ? c.primary.withValues(alpha: 0.16)
                : x.known
                    ? c.surfaceContainerHigh
                    : Colors.transparent,
            borderRadius: BorderRadius.circular(Radii.md),
            border: Border.all(
              color: now
                  ? c.primary
                  : first
                      ? c.primary.withValues(alpha: 0.5)
                      : x.known
                          ? c.outlineVariant
                          : c.outlineVariant.withValues(alpha: 0.7),
              width: now ? 2 : 1,
            ),
          ),
          child: Stack(children: [
            Positioned(
              left: 5,
              top: 3,
              child: Text('${x.level}',
                  style: t.labelSmall!.copyWith(
                      fontSize: 10,
                      color: now ? c.primary : c.onSurfaceVariant,
                      fontFeatures: const [FontFeature.tabularFigures()])),
            ),
            if (game && !done)
              Positioned(
                right: 4,
                top: 4,
                child: Icon(Icons.sports_esports_rounded,
                    size: 11, color: x.game != null ? c.tertiary : c.outline),
              ),
            if (done)
              Positioned(
                right: 4,
                top: 4,
                child: Icon(Icons.check_rounded, size: 11, color: c.primary),
              ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 7,
              child: Center(
                child: lewat
                    ? Icon(Icons.skip_next_rounded, size: 16, color: c.outline)
                    : code == null
                        ? const SizedBox.shrink()
                        : TargetBadge(code!, size: 13, dim: !x.known && !now),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({this.icon, this.hollow = false, required this.text});
  final IconData? icon;
  final bool hollow;
  final String text;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      if (hollow)
        Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(3),
            border: Border.all(color: c.outline),
          ),
        )
      else
        Icon(icon, size: 14, color: c.outline),
      const SizedBox(width: 5),
      Text(text, style: t.labelSmall!.copyWith(color: c.onSurfaceVariant)),
    ]);
  }
}

// ------------------------------------------------------------- game
class _GamesForm extends StatefulWidget {
  const _GamesForm();
  @override
  State<_GamesForm> createState() => _GamesFormState();
}

class _GamesFormState extends State<_GamesForm> {
  late final Map<String, StarRule> _r = {
    for (final k in gameKinds) k: StoreScope.read(context).gameRule(k),
  };

  static const _ikon = {
    'balloon': Icons.bubble_chart_rounded,
    'monster': Icons.pest_control_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final dirty = gameKinds.any((k) => !_r[k]!.sameAs(s.gameRule(k)));
    return _Frame(
      feel: _Feel.games,
      title: 'Aturan khusus game',
      badge: Tip(
        message: 'Hanya berlaku saat rencana jalan. Game lain diketik secepatnya.',
        child: _Pill('saat rencana jalan', color: c.onSurfaceVariant),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
        children: [
          for (final k in gameKinds) ...[
            Align(
              alignment: Alignment.topLeft,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 580),
                child: _gameCard(k, t, c),
              ),
            ),
            const SizedBox(height: 14),
          ],
        ],
      ),
      footer: [
        const Spacer(),
        TextButton(onPressed: () => s.openEdit(null), child: const Text('Batal')),
        const SizedBox(width: 6),
        Press(
          enabled: dirty,
          child: FilledButton(
            onPressed: dirty
                ? () async {
                    if (await s.saveGames(_r)) s.openEdit(null);
                  }
                : null,
            child: const Text('Simpan'),
          ),
        ),
      ],
    );
  }

  Widget _gameCard(String k, TextTheme t, ColorScheme c) {
    final r = _r[k]!;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      decoration: BoxDecoration(
        color: c.surfaceContainer,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: r.follow ? c.outlineVariant : c.primary.withValues(alpha: 0.45)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(_ikon[k], size: 18, color: r.follow ? c.onSurfaceVariant : c.primary),
          const SizedBox(width: 8),
          Text(gameNames[k]!, style: t.titleSmall),
        ]),
        const SizedBox(height: 12),
        RuleEditor(
          rule: r,
          allowFollow: true,
          onChanged: (n) => setState(() => _r[k] = n),
        ),
        if (r.variable) ...[
          const SizedBox(height: 12),
          Row(children: [
            Icon(Icons.east_rounded, size: 14, color: c.outline),
            const SizedBox(width: 6),
            Text('Berikutnya', style: t.labelSmall!.copyWith(color: c.onSurfaceVariant)),
          ]),
          const SizedBox(height: 6),
          SeqStrip(rule: r, seqKey: 'g:$k'),
        ],
      ]),
    );
  }
}
