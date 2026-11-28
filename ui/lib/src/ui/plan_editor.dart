// Lembar editor rencana: terbuka di samping panel Rencana (menimpa
// halaman), cukup lebar untuk pola, acak & aturan khusus game.
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
    final c = Theme.of(context).colorScheme;
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
              child: Container(
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  color: c.surface,
                  borderRadius: BorderRadius.circular(Radii.lg),
                  border: Border.all(color: c.outlineVariant),
                ),
                child: e.games ? const _GamesForm() : _SegmentForm(edit: e),
              ),
            ),
    );
  }
}

/// Kerangka lembar: judul + isi bergulir + tombol bawah.
class _Frame extends StatelessWidget {
  const _Frame({
    required this.title,
    required this.subtitle,
    required this.children,
    required this.onSave,
    required this.saveLabel,
    this.onDelete,
  });
  final String title;
  final String subtitle;
  final List<Widget> children;
  final VoidCallback onSave;
  final String saveLabel;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Shortcuts(
      shortcuts: const {SingleActivator(LogicalKeyboardKey.escape): DismissIntent()},
      child: Actions(
        actions: {
          DismissIntent: CallbackAction<DismissIntent>(onInvoke: (_) => s.openEdit(null)),
        },
        child: FocusScope(
          autofocus: true,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 14, 10, 12),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(title, style: t.titleMedium),
                    const SizedBox(height: 2),
                    Text(subtitle, style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
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
            Divider(height: 1, color: c.outlineVariant),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
                children: children,
              ),
            ),
            Divider(height: 1, color: c.outlineVariant),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
              child: Row(children: [
                if (onDelete != null)
                  _ConfirmButton(onConfirm: onDelete!),
                const Spacer(),
                TextButton(onPressed: () => s.openEdit(null), child: const Text('Batal')),
                const SizedBox(width: 6),
                Press(child: FilledButton(onPressed: onSave, child: Text(saveLabel))),
              ]),
            ),
          ]),
        ),
      ),
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
      label: Text(_armed ? 'Yakin hapus?' : 'Hapus bagian'),
    );
  }
}

/// Judul bagian kecil di dalam lembar.
class _Label extends StatelessWidget {
  const _Label(this.text, {this.icon});
  final String text;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(children: [
        if (icon != null) ...[
          Icon(icon, size: 16, color: c.primary),
          const SizedBox(width: 6),
        ],
        Text(text, style: t.labelLarge!.copyWith(color: c.onSurface)),
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
    // hanya bagian pertama yg harus mulai di level terbuka; sisanya
    // terbuka sendiri selagi bot jalan
    if (_isFirst && s.unlocked > 0 && a > s.unlocked) {
      s.say('Level $a belum terbuka. Level terbuka terakhir: ${s.unlocked}.', error: true);
      return;
    }
    _sg
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
    final saved = e.index != null && e.index! < s.segments.length
        ? s.segments[e.index!]
        : null;
    Widget angka(TextEditingController ctl, String label, {String? hint, bool fokus = false}) =>
        SizedBox(
          width: 120,
          child: TextField(
            controller: ctl,
            autofocus: fokus,
            style: t.bodyMedium!.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            onSubmitted: (_) => _simpan(s),
            decoration: InputDecoration(labelText: label, hintText: hint, isDense: true),
          ),
        );
    return _Frame(
      title: e.isNew ? 'Bagian baru' : 'Ubah bagian ${saved?.label ?? ''}',
      subtitle: 'Rentang level dan target bintangnya.',
      saveLabel: e.isNew ? 'Buat' : 'Simpan',
      onSave: () => _simpan(s),
      onDelete: e.isNew ? null : () => _hapus(s),
      children: [
        const _Label('Level', icon: Icons.format_list_numbered_rounded),
        Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
          angka(_a, 'Dari', fokus: e.isNew),
          Text('–', style: t.bodyLarge!.copyWith(color: c.onSurfaceVariant)),
          angka(_b, 'Sampai', hint: 'habis'),
        ]),
        const SizedBox(height: 6),
        Text('Kosongkan "Sampai" untuk terus sampai level terakhir.',
            style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
        const SizedBox(height: 24),
        const _Label('Target bintang', icon: Icons.star_rounded),
        RuleEditor(
          rule: _sg.rule,
          // kunci urutan ikut 'Dari' yang tersimpan (diubah = urutan baru)
          seqKey: saved?.seqKey ?? _sg.seqKey,
          saved: saved?.rule,
          previewNoun: 'level berbintang',
          onChanged: (r) => setState(() => _sg.rule = r),
        ),
        if (s.anyGameRule) ...[
          const SizedBox(height: 14),
          Row(children: [
            Icon(Icons.sports_esports_rounded, size: 16, color: c.onSurfaceVariant),
            const SizedBox(width: 6),
            Expanded(
              child: Text('Game balon/monster ikut aturan khusus game, bukan target bagian ini.',
                  style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
            ),
          ]),
        ],
      ],
    );
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

  static const _ket = {
    'balloon': 'Huruf di balon yang jatuh (Balloon Valley).',
    'monster': 'Monster yang maju ke arahmu (Monster Attack).',
  };

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return _Frame(
      title: 'Aturan khusus game',
      subtitle: 'Berlaku di semua mode: tanpa rencana, rencana, dan Manual.',
      saveLabel: 'Simpan',
      onSave: () async {
        if (await s.saveGames(_r)) s.openEdit(null);
      },
      children: [
        for (final k in gameKinds) ...[
          _Label(gameNames[k]!, icon: _ikon[k]),
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_ket[k]!, style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
          ),
          RuleEditor(
            rule: _r[k]!,
            allowFollow: true,
            seqKey: 'g:$k',
            saved: s.gameRule(k),
            previewNoun: gameNames[k]!.toLowerCase(),
            onChanged: (r) => setState(() => _r[k] = r),
          ),
          const SizedBox(height: 28),
        ],
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.info_outline_rounded, size: 16, color: c.onSurfaceVariant),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
                'Game lain belum bisa diatur bintangnya, jadi tetap diketik secepatnya.',
                style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
          ),
        ]),
      ],
    );
  }
}
