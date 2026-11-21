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
    if (s.busy) _edit = null;

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
                  onTap: s.busy ? null : () => setState(() => _edit = _edit == i ? null : i),
                ),
              ),
            if (!s.busy)
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
  });
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
                      if (active) StatusDot(color: c.primary, pulse: true),
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
        const SizedBox(height: 14),
        Row(children: [
          StarRow(_sg.stars,
              size: 24,
              silver: _sg.silver,
              onTap: (n) => setState(() {
                    _sg.stars = n;
                    if (n < 5) _sg.silver = false;
                  })),
          const Spacer(),
          Tooltip(
            message: 'Bintang perak: nilai tertinggi',
            child: FilterChip(
              visualDensity: VisualDensity.compact,
              showCheckmark: false,
              label: const Text('Perak'),
              selected: _sg.silver,
              onSelected: _sg.stars == 5
                  ? (v) => setState(() => _sg.silver = v)
                  : null,
            ),
          ),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          TextButton(
            style: TextButton.styleFrom(foregroundColor: c.error),
            onPressed: () async {
              final segs = s.segments..removeAt(widget.index);
              if (await s.savePlan(segs)) widget.onDone();
            },
            child: const Text('Hapus'),
          ),
          const Spacer(),
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
