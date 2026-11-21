// Panel Rencana (kiri): bagian-bagian level berurutan, masing2 dgn target
// bintang. Kotak: rentang di atas, bintang di bawah. Kotak aktif terisi
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

  Future<void> _tambah(AppStore s) async {
    final segs = s.segments;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    if (segs.isNotEmpty && segs.last.to == 0) {
      // bagian terakhir "sampai habis": potong dulu jadi 10 level
      segs.last.to = segs.last.from + 9;
    }
    final mulai = segs.isEmpty ? pos + 1 : segs.last.to + 1;
    segs.add(Segment(mulai, mulai + 9, segs.isEmpty ? 5 : segs.last.stars));
    if (await s.savePlan(segs)) setState(() => _edit = segs.length - 1);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final segs = s.segments;
    if (_edit != null && _edit! >= segs.length) _edit = null;
    if (_edit != null && s.locked(segs[_edit!])) _edit = null;

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 0, 8, 16),
      children: [
        if (segs.isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(2, 0, 8, 14),
            child: Text(
                'Tanpa rencana, bot lanjut dari level terakhir sampai habis. '
                'Tambah bagian untuk mengatur level dan bintangnya.',
                style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
          ),
        LayoutBuilder(builder: (_, box) {
          const gap = 8.0;
          final w = (box.maxWidth - gap) / 2;
          return Wrap(spacing: gap, runSpacing: gap, children: [
            for (final (i, sg) in segs.indexed)
              SizedBox(
                width: w,
                height: w * 0.86,
                child: _Tile(
                  seg: sg,
                  state: s.activeSegment == null
                      ? _TileState.idle
                      : i < s.activeSegment!
                          ? _TileState.done
                          : i == s.activeSegment!
                              ? _TileState.active
                              : _TileState.idle,
                  progress: i == s.activeSegment && sg.to != 0
                      ? s.doneInActive / (sg.to - sg.from + 1)
                      : 0,
                  selected: _edit == i,
                  locked: s.locked(sg),
                  onTap: () {
                    if (s.locked(sg)) {
                      s.say('Bagian ini sedang dikerjakan. Stop dulu untuk mengubahnya.');
                      return;
                    }
                    setState(() => _edit = _edit == i ? null : i);
                  },
                ),
              ),
            SizedBox(width: w, height: w * 0.86, child: _AddTile(onTap: () => _tambah(s))),
          ]);
        }),
        AnimatedSize(
          duration: Motion.medium,
          curve: Motion.out,
          alignment: Alignment.topCenter,
          child: _edit == null
              ? const SizedBox(width: double.infinity)
              : Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: _Editor(
                    key: ValueKey(_edit),
                    index: _edit!,
                    onDone: () => setState(() => _edit = null),
                  ),
                ),
        ),
      ],
    );
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
  const _AddTile({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Press(
      child: Material(
        color: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.lg),
          side: BorderSide(color: c.outlineVariant),
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
  const _Editor({super.key, required this.index, required this.onDone});
  final int index;
  final VoidCallback onDone;
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
    _sg = StoreScope.read(context).segments[widget.index].copy();
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
    final segs = s.segments;
    final a = int.tryParse(_a.text.trim());
    final b = _b.text.trim().isEmpty ? 0 : int.tryParse(_b.text.trim());
    if (a == null || b == null) {
      s.say('Isi level dengan angka ya.', error: true);
      return;
    }
    _sg
      ..from = a
      ..to = b;
    segs[widget.index] = _sg;
    if (await s.savePlan(segs)) widget.onDone();
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
        border: Border.all(color: c.outlineVariant),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: TextField(
              controller: _a,
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
          TextButton(
            style: TextButton.styleFrom(foregroundColor: c.error),
            onPressed: () async {
              final segs = s.segments..removeAt(widget.index);
              if (await s.savePlan(segs)) widget.onDone();
            },
            child: const Text('Hapus'),
          ),
          const SizedBox(width: 4),
          Press(
            child: FilledButton(
              onPressed: () => _simpan(s),
              child: const Text('Selesai'),
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
