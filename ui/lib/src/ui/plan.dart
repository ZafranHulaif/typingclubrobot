// Panel Rencana (kiri, menimpa halaman): bagian-bagian level berurutan,
// masing2 dgn target bintang. Kotak: rentang di atas, bintang di bawah. Kotak aktif terisi
// pelan2 dari bawah sesuai progres bagian itu.
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'rule_editor.dart';
import 'widgets/common.dart';

class PlanPanel extends StatefulWidget {
  const PlanPanel({super.key});
  @override
  State<PlanPanel> createState() => _PlanPanelState();
}

class _PlanPanelState extends State<PlanPanel> {
  /// Indeks bagian pertama yang tidak tersambung ke sebelumnya (ada celah
  /// atau sebelumnya 'sampai habis'). Bagian dari sini tidak akan jalan.
  static int putus(List<Segment> segs) {
    for (var i = 1; i < segs.length; i++) {
      if (segs[i - 1].to == 0 || segs[i].from > segs[i - 1].to + 1) return i;
    }
    return segs.length;
  }

  void _isiCelah(AppStore s, List<Segment> segs, int i) {
    final prev = segs[i - 1];
    s.openEdit(PlanEdit.draft(
        Segment.withRule(prev.to + 1, segs[i].from - 1, prev.rule.copy()),
        gap: i));
  }

  void _tambah(AppStore s) {
    final segs = s.segments;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    // akun baru: mulai dari level terbuka terakhir (bukan posisi akun lain)
    final mulai = segs.isEmpty
        ? (s.unlocked > 0 ? s.unlocked : (pos + 1)).clamp(1, AppStore.lastLevel)
        : (segs.last.to == 0 ? segs.last.from + 10 : segs.last.to + 1);
    if (segs.isNotEmpty && segs.last.to == 0 || mulai > AppStore.lastLevel) {
      s.say(segs.isNotEmpty && segs.last.to == 0
          ? 'Bagian terakhir sudah sampai habis. Ubah dulu akhirnya ya.'
          : 'Rencana sudah sampai level terakhir (${AppStore.lastLevel}).');
      return;
    }
    s.openEdit(PlanEdit.draft(Segment.withRule(
        mulai,
        (mulai + 9).clamp(mulai, AppStore.lastLevel),
        segs.isEmpty ? StarRule.fixed(platinumCode) : segs.last.rule.copy())));
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final segs = s.segments;
    final ed = s.edit;
    // bagian yang sedang diubah jadi terkunci (bot jalan): tutup lembarnya
    if (ed != null && ed.index != null &&
        (ed.index! >= segs.length || s.locked(segs[ed.index!]))) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (s.edit == ed) s.openEdit(null);
      });
    }
    final editIdx = ed?.index;
    final draftGap = ed != null && ed.isNew ? ed.gap : null;
    final draftAdd = ed != null && ed.isNew && ed.gap == null;

    return LayoutBuilder(builder: (_, box) {
      const gap = 8.0;
      final w = (box.maxWidth - 20 - gap) / 2;
      final h = w * 0.86;
      // kotak2 + Tambah, dua per baris; editor muncul tepat di bawah
      // baris kotak yang dipilih (tak perlu gulir ke bawah)
      final putusDi = putus(segs);
      final kotak = <Widget>[];
      for (final (i, sg) in segs.indexed) {
        // celah sebelum bagian ini: kotak 'Tambah' pengisi
        if (i > 0 && segs[i - 1].to != 0 && sg.from > segs[i - 1].to + 1) {
          kotak.add(SizedBox(
            width: w,
            height: h,
            child: _GapTile(
              from: segs[i - 1].to + 1,
              to: sg.from - 1,
              selected: draftGap == i,
              onTap: () => _isiCelah(s, segs, i),
            ),
          ));
        }
        kotak.add(
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
              selected: editIdx == i,
              locked: s.locked(sg),
              muted: i >= putusDi,
              cur: s.planRunning && i == s.activeSegment ? s.curTarget : null,
              onTap: () {
                if (s.locked(sg)) {
                  s.say('Bagian ini sedang dikerjakan. Stop dulu untuk mengubahnya.');
                  return;
                }
                s.openEdit(editIdx == i ? null : PlanEdit.segment(i, sg));
              },
            ),
          ),
        );
      }
      kotak.add(SizedBox(
          width: w,
          height: h,
          child: _AddTile(selected: draftAdd, onTap: () => _tambah(s))));
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
          const SizedBox(height: 12),
          if (putusDi < segs.length)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                  'Bagian abu-abu tidak akan jalan karena tidak tersambung. '
                  'Isi celahnya dulu.',
                  style: t.bodySmall!.copyWith(color: c.tertiary)),
            ),
          AnimatedSize(
            duration: Motion.medium,
            curve: Motion.out,
            alignment: Alignment.topCenter,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows),
          ),
          const SizedBox(height: 16),
          _GamesCard(
            selected: ed?.games == true,
            onTap: () => s.openEdit(ed?.games == true ? null : PlanEdit.games()),
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
    this.muted = false,
    this.cur,
  });
  final bool locked;
  /// target level yang sedang dikerjakan (bagian aktif, pola/acak)
  final Map<String, dynamic>? cur;
  /// tidak tersambung ke bagian sebelumnya: tidak akan jalan
  final bool muted;
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
                opacity: done || widget.muted ? 0.45 : 1,
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
                    Text(
                        widget.muted
                            ? 'tidak tersambung'
                            : n == null
                                ? 'sampai habis'
                                : '$n level',
                        style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
                    const Spacer(),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: RuleSummary(sg.rule, size: 15),
                    ),
                    if (active && sg.rule.variable && widget.cur != null) ...[
                      const SizedBox(height: 4),
                      Row(children: [
                        Text('sekarang ', style: t.labelSmall!.copyWith(color: c.onSurfaceVariant)),
                        TargetBadge((widget.cur!['code'] as num).toInt(), size: 12),
                      ]),
                    ],
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

/// Celah di antara dua bagian: ketuk untuk menambah bagian pengisinya.
class _GapTile extends StatelessWidget {
  const _GapTile(
      {required this.from, required this.to, required this.onTap, this.selected = false});
  final int from;
  final int to;
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Press(
      child: Material(
        color: c.tertiary.withValues(alpha: 0.06),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.lg),
          side: BorderSide(color: selected ? c.primary : c.tertiary.withValues(alpha: 0.6)),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.lg),
          hoverColor: c.tertiary.withValues(alpha: 0.1),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 10, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$from-$to',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: t.titleMedium!.copyWith(
                      color: c.tertiary,
                      fontFeatures: const [FontFeature.tabularFigures()])),
              Text('belum ada', style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
              const Spacer(),
              Row(children: [
                Icon(Icons.add_rounded, size: 16, color: c.tertiary),
                const SizedBox(width: 4),
                Text('Tambah', style: t.labelMedium!.copyWith(color: c.tertiary)),
              ]),
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

/// Kartu "Aturan khusus game" di bawah kotak2 bagian.
class _GamesCard extends StatelessWidget {
  const _GamesCard({required this.onTap, this.selected = false});
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final redup = t.bodySmall!.copyWith(color: c.onSurfaceVariant);
    return Press(
      child: Material(
        color: c.surfaceContainer,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Radii.lg),
          side: BorderSide(color: selected ? c.primary : c.outlineVariant),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.lg),
          hoverColor: c.surfaceContainerHigh,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
            child: Row(children: [
              Icon(Icons.sports_esports_rounded, size: 20,
                  color: s.anyGameRule ? c.primary : c.onSurfaceVariant),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Aturan khusus game', style: t.labelLarge),
                  const SizedBox(height: 4),
                  for (final k in gameKinds)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Row(children: [
                        SizedBox(
                            width: 58,
                            child: Text(gameNames[k]!.replaceFirst('Game ', ''), style: redup)),
                        Flexible(
                          child: FittedBox(
                            fit: BoxFit.scaleDown,
                            alignment: Alignment.centerLeft,
                            child: RuleSummary(s.gameRule(k), size: 12),
                          ),
                        ),
                      ]),
                    ),
                ]),
              ),
              Icon(Icons.chevron_right_rounded, color: c.onSurfaceVariant),
            ]),
          ),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------- pemilih bintang
/// Chip tenang: angka berwarna bintang + ikon. Hover = sorot, klik = daftar
/// baris bintang (angka di kiri). Perak = baris teratas.
class StarPicker extends StatelessWidget {
  const StarPicker(
      {super.key,
      required this.stars,
      required this.silver,
      required this.onChanged,
      this.onManual,
      this.size = 13});
  final int stars;
  /// ukuran bintang di tombol (editor rencana lebih sempit)
  final double size;
  final bool silver;
  final void Function(int stars, bool silver) onChanged;

  /// pindah ke mode Manual (kapsul saja; editor rencana selalu bintang)
  final VoidCallback? onManual;

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
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 6),
            // sama dgn kapsul saat rencana jalan: deretan bintang berwarna
            child: StarRow(stars, silver: silver, size: size),
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
                    Text('platinum',
                        style: t.labelSmall!.copyWith(color: silverStar)),
                ]),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 4),
            child: Text(
                'Kecepatan & akurasi diatur otomatis.',
                style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
          ),
          if (onManual != null) ...[
            Divider(height: 12, color: c.outlineVariant),
            InkWell(
              hoverColor: c.surfaceContainerHighest,
              onTap: () {
                close();
                onManual!();
              },
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                child: Row(children: [
                  Icon(Icons.bolt_rounded, size: 18, color: c.primary),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text('Atur kecepatan & akurasi sendiri',
                        style: t.labelLarge!.copyWith(color: c.primary)),
                  ),
                ]),
              ),
            ),
          ],
        ]),
      ),
    );
  }
}
