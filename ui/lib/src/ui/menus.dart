import 'dart:async';

// Popup dari bar atas: kecepatan, akun (+ pengaturan jarang), lapor, update.
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'widgets/common.dart';

/// Tombol kecil datar untuk bar atas.
class BarButton extends StatelessWidget {
  const BarButton({
    super.key,
    required this.onTap,
    required this.child,
    this.selected = false,
    this.tooltip,
  });
  final VoidCallback? onTap;
  final Widget child;
  final bool selected;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final b = Press(
      child: Material(
        color: selected ? c.surfaceContainerHigh : Colors.transparent,
        borderRadius: BorderRadius.circular(Radii.md),
        child: InkWell(
          borderRadius: BorderRadius.circular(Radii.md),
          hoverColor: c.surfaceContainerHigh,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: IconTheme.merge(
                data: IconThemeData(size: 18, color: c.onSurfaceVariant),
                child: child),
          ),
        ),
      ),
    );
    return tooltip == null ? b : Tooltip(message: tooltip, child: b);
  }
}

class _MenuItem extends StatelessWidget {
  const _MenuItem(this.icon, this.label, this.onTap, {this.color});
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      hoverColor: c.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        child: Row(children: [
          Icon(icon, size: 18, color: color ?? c.onSurfaceVariant),
          const SizedBox(width: 12),
          Text(label, style: t.bodyMedium!.copyWith(color: color)),
        ]),
      ),
    );
  }
}

/// Item berbahaya: ketuk sekali = minta konfirmasi (3 dtk), ketuk lagi = jalan.
class _ConfirmItem extends StatefulWidget {
  const _ConfirmItem(
      {required this.icon, required this.label, required this.confirm, required this.onConfirm});
  final IconData icon;
  final String label;
  final String confirm;
  final VoidCallback? onConfirm;
  @override
  State<_ConfirmItem> createState() => _ConfirmItemState();
}

class _ConfirmItemState extends State<_ConfirmItem> {
  bool _armed = false;
  Timer? _t;

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return _MenuItem(
      widget.icon,
      _armed ? widget.confirm : widget.label,
      widget.onConfirm == null
          ? null
          : () {
              if (_armed) {
                _t?.cancel();
                widget.onConfirm!();
                return;
              }
              setState(() => _armed = true);
              _t = Timer(const Duration(seconds: 3), () {
                if (mounted) setState(() => _armed = false);
              });
            },
      color: c.error,
    );
  }
}

// ================================================================ kecepatan
class SpeedButton extends StatelessWidget {
  const SpeedButton({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final kunci = s.autoStars > 0;
    final label = !kunci
        ? '${s.wpm} wpm'
        : s.autoWpm > 0
            ? '${s.autoWpm} wpm'
            : 'Otomatis';
    return Popover(
      alignRight: false,
      width: 300,
      trigger: (_, toggle, open) => BarButton(
        onTap: toggle,
        selected: open,
        tooltip: kunci ? 'Kecepatan diatur otomatis' : 'Kecepatan mengetik',
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(kunci ? Icons.lock_rounded : Icons.bolt_rounded,
              size: kunci ? 16 : null),
          const SizedBox(width: 6),
          Text(label,
              style: t.labelLarge!.copyWith(
                  color: c.onSurface,
                  fontFeatures: const [FontFeature.tabularFigures()])),
        ]),
      ),
      content: (_, close) => kunci ? _SpeedLocked(s.autoStars) : const _SpeedPanel(),
    );
  }
}

/// Target bintang selain 5 perak: kecepatan tidak bisa diubah.
class _SpeedLocked extends StatelessWidget {
  const _SpeedLocked(this.stars);
  final int stars;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.lock_rounded, size: 18, color: c.primary),
          const SizedBox(width: 8),
          Text('Kecepatan otomatis', style: t.titleSmall),
        ]),
        const SizedBox(height: 10),
        Text('Target $stars bintang. Kecepatan menyesuaikan tiap level, '
            'dan sebagian salah ketik memang disengaja supaya bintangnya pas.',
            style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
        const SizedBox(height: 8),
        Text('Pilih 5 perak untuk mengatur kecepatan sendiri.',
            style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
      ]),
    );
  }
}

class _SpeedPanel extends StatefulWidget {
  const _SpeedPanel();
  @override
  State<_SpeedPanel> createState() => _SpeedPanelState();
}

class _SpeedPanelState extends State<_SpeedPanel> {
  int? _drag;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final tiers = s.tiers;
    var idx = tiers.indexOf(s.wpm);
    if (idx < 0) idx = tiers.length - 1;
    final i = _drag ?? idx;
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 10, 8),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic, children: [
          Text('${tiers[i]}',
              style: t.displaySmall!
                  .copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
          const SizedBox(width: 6),
          Text('wpm', style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Text(s.speedName(tiers[i]),
                style: t.labelLarge!.copyWith(color: c.primary)),
          ),
        ]),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            trackHeight: 4,
            tickMarkShape: const RoundSliderTickMarkShape(tickMarkRadius: 1.5),
            activeTickMarkColor: c.onPrimary.withValues(alpha: 0.5),
            inactiveTickMarkColor: c.outline,
            showValueIndicator: ShowValueIndicator.never,
          ),
          child: Slider(
            value: i.toDouble(),
            max: (tiers.length - 1).toDouble(),
            divisions: tiers.length - 1,
            onChanged: (v) {
              setState(() => _drag = v.round());
              s.call('speed.set', {'wpm': tiers[v.round()], 'save': false});
            },
            onChangeEnd: (v) {
              s.call('speed.set', {'wpm': tiers[v.round()], 'save': true});
              setState(() => _drag = null);
            },
          ),
        ),
      ]),
    );
  }
}

// ================================================================ akun
class AccountButton extends StatefulWidget {
  const AccountButton({super.key});
  @override
  State<AccountButton> createState() => _AccountButtonState();
}

class _AccountButtonState extends State<AccountButton> {
  int _taps = 0;
  DateTime _first = DateTime(0);
  bool _dev = false;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final aktif = '${s.account['active'] ?? ''}';
    final pending = s.account['pending'] == true;
    final label = pending
        ? 'Akun baru'
        : '${s.account['active_label'] ?? ''}'.isNotEmpty
            ? '${s.account['active_label']}'
            : aktif;
    return Popover(
      width: 268,
      trigger: (_, toggle, open) => BarButton(
        onTap: toggle,
        selected: open,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          _Avatar(label, size: 22, warn: s.bot['needs_login'] == true),
          const SizedBox(width: 8),
          Text(label.isEmpty ? 'Akun' : label,
              style: t.labelLarge!.copyWith(color: c.onSurface)),
          const SizedBox(width: 2),
          const Icon(Icons.expand_more_rounded),
        ]),
      ),
      content: (ctx, close) {
        Future<void> run(String m, [Map<String, dynamic>? p, String? ok]) async {
          close();
          final r = await s.call(m, p);
          if (r != null && ok != null) s.say(ok);
        }

        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            for (final a in s.accounts)
              InkWell(
                hoverColor: c.surfaceContainerHighest,
                onTap: a['name'] == aktif
                    ? null
                    : () => run('acct.switch', {'name': a['name']}),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  child: Row(children: [
                    _Avatar('${a['label'] ?? a['name']}', size: 28, active: a['name'] == aktif),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(a['name'] == aktif && pending
                                ? 'Akun baru (belum login)'
                                : '${a['label'] ?? a['name']}',
                            style: t.titleSmall),
                        if ((a['email'] ?? '') != '')
                          Text('${a['email']}',
                              overflow: TextOverflow.ellipsis,
                              style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
                      ]),
                    ),
                    if (a['name'] == aktif)
                      Icon(Icons.check_rounded, size: 18, color: c.primary),
                  ]),
                ),
              ),
            _MenuItem(Icons.add_rounded, 'Tambah akun',
                s.busy ? null : () => run('acct.add')),
            const Divider(height: 13),
            _MenuItem(Icons.logout_rounded, 'Keluar dari akun',
                s.busy ? null : () => run('acct.logout'),
                color: c.error),
            if (aktif.isNotEmpty)
              _ConfirmItem(
                icon: Icons.delete_outline_rounded,
                label: 'Hapus akun ini',
                confirm: 'Ketuk lagi untuk menghapus',
                onConfirm: s.busy
                    ? null
                    : () => run('acct.delete', {'name': aktif}, 'Akun dihapus dari TypingBot.'),
              ),
            if (_dev) ...[
              const Divider(height: 13),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 4, 14, 8),
                child: Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final w in ['login', 'locked', 'next', 'force_close', 'error', 'license', 'boot'])
                    ActionChip(
                      visualDensity: VisualDensity.compact,
                      label: Text(w),
                      onPressed: () => run('dev.simulate', {'what': w}),
                    ),
                ]),
              ),
            ],
            // versi: ketuk 5x dlm 3 dtk = menu developer
            GestureDetector(
              onTap: () {
                final now = DateTime.now();
                if (now.difference(_first) > const Duration(seconds: 3)) {
                  _first = now;
                  _taps = 0;
                }
                if (++_taps >= 5) setState(() => _dev = true);
              },
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 8, 14, 6),
                child: Text('TypingBot ${s.app['version'] ?? ''}',
                    style: t.labelSmall!.copyWith(color: c.outline)),
              ),
            ),
          ]),
        );
      },
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar(this.name, {this.size = 24, this.active = true, this.warn = false});
  final String name;
  final double size;
  final bool active;
  final bool warn;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final bg = warn ? c.tertiary : active ? c.primary : c.surfaceContainerHighest;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(shape: BoxShape.circle, color: bg),
      child: Text(name.isEmpty ? '?' : name[0].toUpperCase(),
          style: t.labelMedium!.copyWith(
              fontSize: size * 0.48,
              color: active || warn ? c.onPrimary : c.onSurface)),
    );
  }
}

// ================================================================ lapor
class ReportButton extends StatelessWidget {
  const ReportButton({super.key});
  @override
  Widget build(BuildContext context) {
    return Popover(
      width: 320,
      trigger: (_, toggle, open) => BarButton(
        onTap: toggle,
        selected: open,
        tooltip: 'Laporkan masalah',
        child: const Icon(Icons.bug_report_outlined),
      ),
      content: (_, close) => _ReportForm(close: close),
    );
  }
}

class _ReportForm extends StatefulWidget {
  const _ReportForm({required this.close});
  final VoidCallback close;
  @override
  State<_ReportForm> createState() => _ReportFormState();
}

class _ReportFormState extends State<_ReportForm> {
  static const _kat = ['Bot macet', 'Salah ketik', 'Login', 'Lainnya'];
  String _pilih = _kat.first;
  final _teks = TextEditingController();
  bool _kirim = false;

  @override
  void dispose() {
    _teks.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Laporkan masalah', style: t.titleMedium),
        const SizedBox(height: 12),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final k in _kat)
            ChoiceChip(
              visualDensity: VisualDensity.compact,
              showCheckmark: false,
              label: Text(k),
              selected: _pilih == k,
              onSelected: (_) => setState(() => _pilih = k),
            ),
        ]),
        const SizedBox(height: 12),
        TextField(
          controller: _teks,
          autofocus: true,
          minLines: 3,
          maxLines: 6,
          style: t.bodyMedium,
          decoration: const InputDecoration(hintText: 'Apa yang terjadi?'),
        ),
        const SizedBox(height: 6),
        Text('Catatan bot ikut terkirim.',
            style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerRight,
          child: Press(
            child: FilledButton(
              onPressed: _kirim
                  ? null
                  : () async {
                      setState(() => _kirim = true);
                      final r = await s.call('report.send',
                          {'category': _pilih, 'text': _teks.text});
                      if (!mounted) return;
                      setState(() => _kirim = false);
                      if (r != null) {
                        widget.close();
                        s.say('Laporan terkirim, makasih!');
                      }
                    },
              child: Text(_kirim ? 'Mengirim...' : 'Kirim'),
            ),
          ),
        ),
      ]),
    );
  }
}

// ================================================================ update
class UpdateButton extends StatelessWidget {
  const UpdateButton({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Popover(
      width: 320,
      trigger: (_, toggle, open) => BarButton(
        onTap: toggle,
        selected: open,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.arrow_circle_up_rounded, color: c.secondary),
          const SizedBox(width: 6),
          Text('Versi baru', style: t.labelLarge!.copyWith(color: c.secondary)),
        ]),
      ),
      content: (_, close) {
        final u = StoreScope.of(context).update;
        final phase = '${u['phase'] ?? 'idle'}';
        final prog = (u['progress'] as num?)?.toDouble() ?? 0;
        final notes = '${u['notes'] ?? ''}'
            .split('\n')
            .where((l) => l.trim().startsWith('- '))
            .map((l) => l.replaceAll('**', '').substring(2))
            .toList();
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Versi ${u['version']}', style: t.titleMedium),
            const SizedBox(height: 10),
            for (final n in notes)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('· $n', style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
              ),
            const SizedBox(height: 10),
            if (phase == 'downloading') ...[
              SmoothProgress(value: prog),
              const SizedBox(height: 8),
              Row(children: [
                Text('${(prog * 100).round()}%', style: t.bodySmall),
                const Spacer(),
                TextButton(onPressed: () => s.call('update.cancel'), child: const Text('Batal')),
              ]),
            ] else
              Align(
                alignment: Alignment.centerRight,
                child: Press(
                  child: FilledButton(
                    onPressed: () => s.call(phase == 'ready' ? 'update.install' : 'update.download'),
                    child: Text(phase == 'ready' ? 'Pasang & mulai ulang' : 'Unduh'),
                  ),
                ),
              ),
          ]),
        );
      },
    );
  }
}
