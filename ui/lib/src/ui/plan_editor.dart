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
  late final AppStore _store;

  @override
  void initState() {
    super.initState();
    // peta level ikut angka yang sedang diketik
    _a.addListener(_ulang);
    _b.addListener(_ulang);
    // Mulai rencana menyimpan lembar ini dulu
    _store = StoreScope.read(context)..saveDraft = _simpanDraft;
  }

  void _ulang() => setState(() {});

  @override
  void dispose() {
    if (_store.saveDraft == _simpanDraft) _store.saveDraft = null;
    _a.dispose();
    _b.dispose();
    super.dispose();
  }

  Future<bool> _simpanDraft() async {
    final saved = _saved(_store);
    if (saved != null && _store.locked(saved)) return true;
    if (!_dirty(saved)) return true;
    final ok = await _simpan(_store);
    if (ok) _store.say('Perubahan disimpan dulu.');
    return ok;
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

  Future<bool> _simpan(AppStore s) async {
    final a = _from;
    final b = _to;
    if (a == null) {
      s.say('Isi level awal dengan angka ya.', error: true);
      return false;
    }
    if (b == null) {
      s.say('Isi sampai level berapa, atau centang "Sampai habis".', error: true);
      return false;
    }
    if (a < 1 || a > AppStore.lastLevel || b > AppStore.lastLevel) {
      s.say('Level 1 sampai ${AppStore.lastLevel} ya.', error: true);
      return false;
    }
    if (b != 0 && b < a) {
      s.say('Level akhir harus sesudah level awal.', error: true);
      return false;
    }
    // hanya bagian pertama yg harus mulai di level terbuka; sisanya
    // terbuka sendiri selagi bot jalan
    if (_isFirst && s.unlocked > 0 && a > s.unlocked) {
      s.say('Level $a belum terbuka. Level terbuka terakhir: ${s.unlocked}.', error: true);
      return false;
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
      if (i >= segs.length) return false;
      segs[i] = _sg;
    }
    // bagian pengisi celah masuk di tengah: urutkan
    segs.sort((x, y) => x.from.compareTo(y.from));
    if (!await s.savePlan(segs)) return false;
    s.openEdit(null);
    return true;
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
/// Warna peta: selesai = hijau, dilewati = ungu muda + ikon jenisnya,
/// premium = merah muda + gembok.
const _hijau = Color(0xFF5BD68A);
const _premium = Color(0xFFFF8FB1);

/// Tampilan tiap jenis level yang dilewati (ikon, warna, nama).
({IconData icon, Color color, String name}) _lookOf(String kind, ColorScheme c) => switch (kind) {
      'video' => (icon: Icons.play_circle_outline_rounded, color: c.secondary, name: 'video'),
      'tutorial' => (icon: Icons.school_outlined, color: c.secondary, name: 'tutorial'),
      'test' => (icon: Icons.quiz_outlined, color: c.secondary, name: 'tes'),
      'hold' => (icon: Icons.keyboard_outlined, color: c.secondary, name: 'tahan tombol'),
      'game' => (icon: Icons.sports_esports_outlined, color: c.secondary, name: 'game lain'),
      'premium' => (icon: Icons.lock_rounded, color: _premium, name: 'premium'),
      _ => (icon: Icons.skip_next_rounded, color: c.secondary, name: 'dilewati'),
    };

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
        done: s.done,
        start: mulai,
        count: muat,
      );
      final sisa = akhir - (sel.isEmpty ? mulai - 1 : sel.last.level);
      final kini = jalan ? sel.where((x) => x.level == current).firstOrNull : null;
      final cur = s.curTarget;
      final kodeKini = cur != null && cur['level'] == current
          ? (cur['code'] as num).toInt()
          : kini?.code;
      // keterangan: hanya yang muncul di peta
      final jenisLewat = <String>{
        for (final x in sel)
          if (x.skip) _lookOf(x.kind, c).name,
      };
      final adaSelesai = sel.any((x) => x.done);
      final adaGame = sel.any((x) => x.game != null || gameKinds.contains(x.kind));
      final adaBaru = sel.any((x) => !x.known && !x.done);

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
              first: x.level == from && !jalan,
            ),
        ]),
        if (sisa > 0) ...[
          const SizedBox(height: 8),
          Text('+$sisa level lagi',
              style: t.labelMedium!.copyWith(color: c.onSurfaceVariant)),
        ],
        const SizedBox(height: 14),
        Wrap(spacing: 14, runSpacing: 8, children: [
          if (adaSelesai) const _Legend(icon: Icons.check_rounded, color: _hijau, text: 'selesai'),
          for (final k in const ['video', 'tutorial', 'test', 'hold', 'game', 'free', 'premium'])
            if (jenisLewat.contains(_lookOf(k, c).name))
              _Legend(icon: _lookOf(k, c).icon, color: _lookOf(k, c).color, text: _lookOf(k, c).name),
          if (adaGame) _Legend(icon: Icons.sports_esports_rounded, color: c.tertiary, text: 'game balon/monster'),
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
    final x = cell;
    final lewat = x != null && x.skip;
    final look = lewat ? _lookOf(x.kind, c) : null;
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
        if (look != null)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(look.icon, size: 18, color: look.color),
            const SizedBox(width: 6),
            Text('${look.name}, tanpa bintang', style: t.labelMedium!.copyWith(color: look.color)),
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
    this.first = false,
  });
  final LevelCell cell;
  final double size;
  final int? code;
  final bool now;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final x = cell;
    // 'premium' yang ternyata selesai = level biasa (modal Pro kebetulan)
    final lewat = x.skip && !(x.done && x.kind == 'premium');
    final look = lewat ? _lookOf(x.kind, c) : null;
    final selesai = x.done && !now;
    final game = x.game != null || gameKinds.contains(x.kind);
    String bintang(int k) => k >= platinumCode ? 'platinum' : '$k bintang';
    final pesan = [
      'Level ${x.level}',
      if (look != null)
        x.kind == 'premium' ? 'premium (terkunci Pro), dilewati' : '${look.name}, dilewati tanpa bintang'
      else if (selesai)
        code == null ? 'selesai' : 'selesai: ${bintang(code!)}'
      else if (code != null)
        'target ${bintang(code!)}',
      if (selesai && !lewat && x.planned != null && x.planned != code)
        'kalau diulang: target ${bintang(x.planned!)}',
      if (x.game != null) 'aturan ${gameNames[x.game]!.toLowerCase()}',
      if (!x.known && !x.done) 'belum pernah dibuka, jenisnya belum diketahui',
    ].join(' · ');

    // warna kotak
    final Color latar;
    final Color garis;
    if (now) {
      latar = c.primary.withValues(alpha: 0.16);
      garis = c.primary;
    } else if (selesai) {
      latar = _hijau.withValues(alpha: 0.12);
      garis = _hijau.withValues(alpha: 0.55);
    } else if (look != null) {
      latar = look.color.withValues(alpha: 0.1);
      garis = look.color.withValues(alpha: 0.4);
    } else if (x.known) {
      latar = c.surfaceContainerHigh;
      garis = first ? c.primary.withValues(alpha: 0.5) : c.outlineVariant;
    } else {
      latar = Colors.transparent;
      garis = first ? c.primary.withValues(alpha: 0.5) : c.outlineVariant.withValues(alpha: 0.8);
    }

    // ikon kecil pojok kanan atas
    final Widget? pojok = selesai
        ? const Icon(Icons.check_rounded, size: 12, color: _hijau)
        : game
            ? Icon(Icons.sports_esports_rounded,
                size: 11, color: x.game != null ? c.tertiary : c.outline)
            : null;

    return Tip(
      message: pesan,
      child: AnimatedContainer(
        duration: Motion.short,
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: latar,
          borderRadius: BorderRadius.circular(Radii.md),
          border: Border.all(color: garis, width: now ? 2 : 1),
        ),
        child: Stack(children: [
          Positioned(
            left: 5,
            top: 3,
            child: Text('${x.level}',
                style: t.labelSmall!.copyWith(
                    fontSize: 10,
                    color: now
                        ? c.primary
                        : selesai
                            ? _hijau
                            : look?.color.withValues(alpha: 0.9) ?? c.onSurfaceVariant,
                    fontFeatures: const [FontFeature.tabularFigures()])),
          ),
          if (pojok != null) Positioned(right: 4, top: 4, child: pojok),
          Positioned(
            left: 0,
            right: 0,
            bottom: 7,
            child: Center(
              child: look != null
                  ? Icon(look.icon, size: 17, color: look.color)
                  : code == null
                      ? const SizedBox.shrink()
                      : TargetBadge(code!, size: 13, dim: !x.known && !now && !x.done),
            ),
          ),
        ]),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({this.icon, this.color, this.hollow = false, required this.text});
  final IconData? icon;
  final Color? color;
  final bool hollow;
  final String text;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final w = color ?? c.outline;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(
          color: hollow ? null : w.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(4),
          border: Border.all(color: hollow ? c.outline : w.withValues(alpha: 0.5)),
        ),
        child: hollow ? null : Icon(icon, size: 12, color: w),
      ),
      const SizedBox(width: 6),
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
  late final AppStore _store;

  @override
  void initState() {
    super.initState();
    _store = StoreScope.read(context)..saveDraft = _simpanDraft;
  }

  @override
  void dispose() {
    if (_store.saveDraft == _simpanDraft) _store.saveDraft = null;
    super.dispose();
  }

  bool get _dirty => gameKinds.any((k) => !_r[k]!.sameAs(_store.gameRule(k)));

  Future<bool> _simpanDraft() async {
    if (!_dirty) return true;
    if (!await _store.saveGames(_r)) return false;
    _store.openEdit(null);
    return true;
  }

  static const _ikon = {
    'balloon': Icons.bubble_chart_rounded,
    'monster': Icons.pest_control_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final dirty = _dirty;
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
