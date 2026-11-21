// Panel Rencana (kiri, menimpa halaman): bagian-bagian level berurutan,
// masing2 dgn target bintang. Kotak: rentang di atas, bintang di bawah. Kotak aktif terisi
// pelan2 dari bawah sesuai progres bagian itu.
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'widgets/common.dart';

class PlanPanel extends StatefulWidget {
  const PlanPanel({super.key});
  @override
  State<PlanPanel> createState() => _PlanPanelState();
}

class _PlanPanelState extends State<PlanPanel> {
  int? _edit; // indeks kotak yang sedang diubah
  Segment? _draft; // bagian baru (belum disimpan sampai "Buat")

  void _tambah(AppStore s) {
    final segs = s.segments;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    final mulai = segs.isEmpty
        ? (pos + 1).clamp(1, AppStore.lastLevel)
        : (segs.last.to == 0 ? segs.last.from + 10 : segs.last.to + 1);
    if (segs.isNotEmpty && segs.last.to == 0 || mulai > AppStore.lastLevel) {
      s.say(segs.isNotEmpty && segs.last.to == 0
          ? 'Bagian terakhir sudah sampai habis. Ubah dulu akhirnya ya.'
          : 'Rencana sudah sampai level terakhir (${AppStore.lastLevel}).');
      return;
    }
    setState(() {
      _edit = null;
      _draft = Segment(mulai, (mulai + 9).clamp(mulai, AppStore.lastLevel),
          segs.isEmpty ? 5 : segs.last.stars,
          silver: segs.isNotEmpty && segs.last.silver);
    });
  }

  Future<bool> _simpan(AppStore s, Segment sg, int? index) async {
    final segs = s.segments;
    if (index == null) {
      segs.add(sg);
    } else {
      segs[index] = sg;
    }
    return s.savePlan(segs);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final segs = s.segments;
    if (_edit != null && _edit! >= segs.length) _edit = null;
    if (_edit != null && s.locked(segs[_edit!])) _edit = null;

    Widget editor() => Padding(
          padding: const EdgeInsets.only(top: 8),
          child: _Editor(
            key: ValueKey(_draft != null ? 'baru' : _edit),
            initial: _draft ?? segs[_edit!],
            isNew: _draft != null,
            onSave: (sg) async {
              if (await _simpan(s, sg, _draft != null ? null : _edit)) {
                setState(() {
                  _draft = null;
                  _edit = null;
                });
              }
            },
            onDelete: _draft != null
                ? null
                : () async {
                    final l = s.segments..removeAt(_edit!);
                    if (await s.savePlan(l)) setState(() => _edit = null);
                  },
            onCancel: () => setState(() {
              _draft = null;
              _edit = null;
            }),
          ),
        );

    return LayoutBuilder(builder: (_, box) {
      const gap = 8.0;
      final w = (box.maxWidth - 20 - gap) / 2;
      final h = w * 0.86;
      // kotak2 + Tambah, dua per baris; editor muncul tepat di bawah
      // baris kotak yang dipilih (tak perlu gulir ke bawah)
      final kotak = <Widget>[
        for (final (i, sg) in segs.indexed)
          SizedBox(
            width: w,
            height: h,
            child: _Tile(
              seg: sg,
              state: s.activeSegment == null || !s.planRunning
                  ? _TileState.idle
                  : i < s.activeSegment!
                      ? _TileState.done
                      : i == s.activeSegment!
                          ? _TileState.active
                          : _TileState.idle,
              progress: s.planRunning && i == s.activeSegment && sg.to != 0
                  ? s.doneInActive / (sg.to - sg.from + 1)
                  : 0,
              selected: _edit == i,
              locked: s.locked(sg),
              onTap: () {
                if (s.locked(sg)) {
                  s.say('Bagian ini sedang dikerjakan. Stop dulu untuk mengubahnya.');
                  return;
                }
                setState(() {
                  _draft = null;
                  _edit = _edit == i ? null : i;
                });
              },
            ),
          ),
        SizedBox(
            width: w,
            height: h,
            child: _AddTile(selected: _draft != null, onTap: () => _tambah(s))),
      ];
      final editAt = _draft != null ? segs.length : _edit; // indeks kotak
      final rows = <Widget>[];
      for (var r = 0; r * 2 < kotak.length; r++) {
        final isi = kotak.sublist(r * 2, (r * 2 + 2).clamp(0, kotak.length));
        rows.add(Padding(
          padding: EdgeInsets.only(top: r == 0 ? 0 : gap),
          child: Row(children: [
            isi[0],
            if (isi.length > 1) ...[const SizedBox(width: gap), isi[1]],
          ]),
        ));
        if (editAt != null && editAt ~/ 2 == r) rows.add(editor());
      }

      return ListView(
        padding: const EdgeInsets.fromLTRB(10, 0, 10, 16),
        children: [
          Row(children: [
            Expanded(
              child: Text('Rencana',
                  style: t.titleSmall!.copyWith(color: c.onSurface)),
            ),
            Press(
              enabled: segs.isNotEmpty && !s.busy && s.licensed,
              child: FilledButton.icon(
                onPressed: segs.isNotEmpty && !s.busy && s.licensed
                    ? s.startPlan
                    : null,
                icon: const Icon(Icons.play_arrow_rounded, size: 18),
                label: Text(s.planRunning ? 'Sedang jalan' : 'Mulai rencana'),
              ),
            ),
          ]),
          const SizedBox(height: 8),
          Text(
              segs.isEmpty
                  ? 'Tanpa rencana: tekan Mulai di atas, lalu buka level di '
                      'halaman. Bot lanjut dari level itu. Tambah bagian untuk '
                      'mengatur level dan bintangnya sendiri.'
                  : 'Mulai di atas = dari level yang kamu buka. '
                      'Mulai rencana = ikuti bagian-bagian ini.',
              style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
          const SizedBox(height: 12),
          AnimatedSize(
            duration: Motion.medium,
            curve: Motion.out,
            alignment: Alignment.topCenter,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows),
          ),
        ],
      );
    });
  }
}

enum _TileState { idle, active, done }

class _Tile extends StatefulWidget {
  const _Tile({
    required this.seg,
    required this.state,
    required this.progress,
    required this.selected,
    required this.onTap,
    this.locked = false,
  });
  final bool locked;
  final Segment seg;
  final _TileState state;
  final double progress;
  final bool selected;
  final VoidCallback? onTap;

  @override
  State<_Tile> createState() => _TileState2();
}

class _TileState2 extends State<_Tile> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final sg = widget.seg;
    final active = widget.state == _TileState.active;
    final done = widget.state == _TileState.done;
    final border = active || widget.selected
        ? c.primary
        : _hover && widget.onTap != null
            ? c.outline
            : c.outlineVariant;
    final n = sg.to == 0 ? null : sg.to - sg.from + 1;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      cursor: widget.onTap == null ? MouseCursor.defer : SystemMouseCursors.click,
      child: Press(
        enabled: widget.onTap != null,
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: Motion.short,
            curve: Motion.out,
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(
              color: c.surfaceContainer,
              borderRadius: BorderRadius.circular(Radii.lg),
              border: Border.all(color: border),
            ),
            child: Stack(children: [
              // isi progres dari bawah (bagian aktif)
              Positioned.fill(
                child: Align(
                  alignment: Alignment.bottomCenter,
                  child: TweenAnimationBuilder<double>(
                    tween: Tween(end: active ? widget.progress.clamp(0.0, 1.0) : 0),
                    duration: Motion.drawer,
                    curve: Motion.out,
                    builder: (_, v, _) => FractionallySizedBox(
                      heightFactor: v,
                      widthFactor: 1,
                      child: ColoredBox(color: c.primary.withValues(alpha: 0.1)),
                    ),
                  ),
                ),
              ),
              AnimatedOpacity(
                duration: Motion.medium,
                opacity: done ? 0.45 : 1,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 10, 10, 12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(
                        child: Text(sg.label,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: t.titleMedium!.copyWith(
                                fontFeatures: const [FontFeature.tabularFigures()])),
                      ),
                      if (done) Icon(Icons.check_rounded, size: 16, color: c.primary),
                      if (active)
                        StatusDot(color: c.primary, pulse: true)
                      else if (widget.locked && !done)
                        Icon(Icons.lock_outline_rounded, size: 14, color: c.onSurfaceVariant),
                    ]),
                    Text(n == null ? 'sampai habis' : '$n level',
                        style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
                    const Spacer(),
                    StarRow(sg.stars, silver: sg.silver, size: 15),
                  ]),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _AddTile extends StatelessWidget {
  const _AddTile({required this.onTap, this.selected = false});
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Press(
      child: Material(
        color: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.lg),
          side: BorderSide(color: selected ? c.primary : c.outlineVariant),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.lg),
          hoverColor: c.surfaceContainer,
          onTap: onTap,
          child: Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.add_rounded, color: c.onSurfaceVariant),
              const SizedBox(height: 4),
              Text('Tambah', style: t.labelMedium!.copyWith(color: c.onSurfaceVariant)),
            ]),
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------- editor
class _Editor extends StatefulWidget {
  const _Editor({
    super.key,
    required this.initial,
    required this.isNew,
    required this.onSave,
    required this.onCancel,
    this.onDelete,
  });
  final Segment initial;
  final bool isNew;
  final Future<void> Function(Segment) onSave;
  final VoidCallback onCancel;
  final VoidCallback? onDelete;
  @override
  State<_Editor> createState() => _EditorState();
}

class _EditorState extends State<_Editor> {
  late Segment _sg;
  final _a = TextEditingController();
  final _b = TextEditingController();

  @override
  void initState() {
    super.initState();
    _sg = widget.initial.copy();
    _a.text = '${_sg.from}';
    _b.text = _sg.to == 0 ? '' : '${_sg.to}';
  }

  @override
  void dispose() {
    _a.dispose();
    _b.dispose();
    super.dispose();
  }

  Future<void> _simpan(AppStore s) async {
    final a = int.tryParse(_a.text.trim());
    final b = _b.text.trim().isEmpty ? 0 : int.tryParse(_b.text.trim());
    if (a == null || b == null) {
      s.say('Isi level dengan angka ya.', error: true);
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
    _sg
      ..from = a
      ..to = b;
    await widget.onSave(_sg);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    InputDecoration dec(String label, [String? hint]) => InputDecoration(
          labelText: label,
          hintText: hint,
          isDense: true,
        );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: c.surfaceContainer,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: c.primary.withValues(alpha: 0.5)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (widget.isNew)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text('Bagian baru',
                style: t.labelLarge!.copyWith(color: c.onSurface)),
          ),
        Row(children: [
          Expanded(
            child: TextField(
              controller: _a,
              autofocus: widget.isNew,
              style: t.bodyMedium,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: dec('Dari'),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _b,
              style: t.bodyMedium,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              onSubmitted: (_) => _simpan(s),
              decoration: dec('Sampai', 'habis'),
            ),
          ),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          StarPicker(
            stars: _sg.stars,
            silver: _sg.silver,
            onChanged: (st, sv) => setState(() {
              _sg.stars = st;
              _sg.silver = sv;
            }),
          ),
          const Spacer(),
          if (widget.onDelete != null)
            TextButton(
              style: TextButton.styleFrom(foregroundColor: c.error),
              onPressed: widget.onDelete,
              child: const Text('Hapus'),
            )
          else
            TextButton(onPressed: widget.onCancel, child: const Text('Batal')),
          const SizedBox(width: 4),
          Press(
            child: FilledButton(
              onPressed: () => _simpan(s),
              child: Text(widget.isNew ? 'Buat' : 'Simpan'),
            ),
          ),
        ]),
      ]),
    );
  }
}


// ------------------------------------------------------------- pemilih bintang
/// Chip tenang: angka berwarna bintang + ikon. Hover = sorot, klik = daftar
/// baris bintang (angka di kiri). Perak = baris teratas.
class StarPicker extends StatelessWidget {
  const StarPicker(
      {super.key, required this.stars, required this.silver, required this.onChanged});
  final int stars;
  final bool silver;
  final void Function(int stars, bool silver) onChanged;

  static const _opsi = [(5, true), (5, false), (4, false), (3, false), (2, false), (1, false)];

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    Color warna(bool sv) => sv ? silverStar : c.tertiary;
    return Popover(
      alignRight: false,
      width: 196,
      trigger: (_, toggle, open) => Material(
        color: open ? c.surfaceContainerHighest : Colors.transparent,
        borderRadius: BorderRadius.circular(Radii.sm),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.sm),
          hoverColor: c.surfaceContainerHighest,
          onTap: toggle,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text('$stars',
                  style: t.titleMedium!.copyWith(color: warna(silver))),
              const SizedBox(width: 3),
              Icon(Icons.star_rounded, size: 18, color: warna(silver)),
            ]),
          ),
        ),
      ),
      content: (_, close) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final (st, sv) in _opsi)
            InkWell(
              hoverColor: c.surfaceContainerHighest,
              onTap: () {
                onChanged(st, sv);
                close();
              },
              child: Container(
                color: st == stars && sv == silver
                    ? c.surfaceContainerHighest
                    : null,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(children: [
                  SizedBox(
                    width: 18,
                    child: Text('$st',
                        style: t.titleSmall!.copyWith(color: warna(sv))),
                  ),
                  StarRow(st, silver: sv, size: 16),
                  const Spacer(),
                  if (sv)
                    Text('perak',
                        style: t.labelSmall!.copyWith(color: silverStar)),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
