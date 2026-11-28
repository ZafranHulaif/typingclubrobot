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
          // terpilih: hover tetap terasa (lebih terang dari warna terpilih)
          hoverColor: selected ? c.surfaceContainerHighest : c.surfaceContainerHigh,
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
    return tooltip == null ? b : Tip(message: tooltip!, child: b);
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
/// Mode Manual: dial kecepatan + akurasi, perkiraan bintang level ini.
class SpeedPanel extends StatefulWidget {
  const SpeedPanel({super.key});
  @override
  State<SpeedPanel> createState() => _SpeedPanelState();
}

class _SpeedPanelState extends State<SpeedPanel> {
  int? _drag;
  int? _accDrag;

  static const _accMin = 85;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final tiers = s.tiers;
    var idx = tiers.indexOf(s.wpm);
    if (idx < 0) idx = tiers.length - 1;
    final i = _drag ?? idx;
    final acc = _accDrag ?? s.acc.clamp(_accMin, 100);
    final angka = t.displaySmall!
        .copyWith(fontFeatures: const [FontFeature.tabularFigures()]);
    final satuan = t.bodyMedium!.copyWith(color: c.onSurfaceVariant);
    final slider = SliderTheme.of(context).copyWith(
      trackHeight: 4,
      tickMarkShape: const RoundSliderTickMarkShape(tickMarkRadius: 1.5),
      activeTickMarkColor: c.onPrimary.withValues(alpha: 0.5),
      inactiveTickMarkColor: c.outline,
      showValueIndicator: ShowValueIndicator.never,
    );
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 16, 10, 12),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic, children: [
          Text('${tiers[i]}', style: angka),
          const SizedBox(width: 6),
          Text('wpm', style: satuan),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Text(s.speedName(tiers[i]),
                style: t.labelLarge!.copyWith(color: c.primary)),
          ),
        ]),
        SliderTheme(
          data: slider,
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
        const SizedBox(height: 4),
        Row(crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic, children: [
          Text('$acc', style: angka),
          const SizedBox(width: 4),
          Text('% akurasi', style: satuan),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Text(acc == 100 ? 'tanpa salah' : 'ada salah ketik',
                style: t.labelLarge!.copyWith(color: c.primary)),
          ),
        ]),
        SliderTheme(
          data: slider.copyWith(tickMarkShape: SliderTickMarkShape.noTickMark),
          child: Slider(
            value: acc.toDouble(),
            min: _accMin.toDouble(),
            max: 100,
            divisions: 100 - _accMin,
            onChanged: (v) {
              setState(() => _accDrag = v.round());
              s.call('speed.set', {'acc': v.round(), 'save': false});
            },
            onChangeEnd: (v) {
              s.call('speed.set', {'acc': v.round(), 'save': true});
              setState(() => _accDrag = null);
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(right: 8, top: 2),
          child: GuessLine(s),
        ),
      ]),
    );
  }
}

/// Satu baris perkiraan bintang mode Manual (panel kecepatan & kapsul).
class GuessLine extends StatelessWidget {
  const GuessLine(this.s, {super.key});
  final AppStore s;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final g = s.guess;
    final redup = t.bodySmall!.copyWith(color: c.onSurfaceVariant);
    final lvl = s.guessLevel > 0 ? 'Level ${s.guessLevel}' : 'Level ini';
    final note = s.guessNote;
    if (g == null) {
      return Text(
          note.isNotEmpty
              ? '$lvl: $note.'
              : 'Perkiraan bintang muncul saat bot membuka level.',
          style: redup);
    }
    final n = (g['stars'] as num?)?.toInt() ?? 0;
    final sv = g['silver'] == true;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text('$lvl  ≈ ', style: t.bodyMedium),
        StarRow(n, silver: sv, size: 15),
        const SizedBox(width: 6),
        Text(sv ? 'platinum' : '$n bintang',
            style: t.labelMedium!.copyWith(color: sv ? silverStar : c.onSurfaceVariant)),
      ]),
      if (note.isNotEmpty) ...[
        const SizedBox(height: 2),
        Text(note, style: redup),
      ],
      if (s.phase == 'running') ...[
        const SizedBox(height: 2),
        Text('Perubahan berlaku penuh mulai level berikutnya.', style: redup),
      ],
    ]);
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
                padding: const EdgeInsets.fromLTRB(14, 4, 6, 4),
                child: Row(children: [
                  Text('TypingBot ${s.app['version'] ?? ''}',
                      style: t.labelSmall!.copyWith(color: c.outline)),
                  const Spacer(),
                  const _UpdateCheck(),
                ]),
              ),
            ),
          ]),
        );
      },
    );
  }
}

/// "Cek pembaruan" di kaki menu akun: cek sekarang tanpa buka-tutup app.
/// Versi baru = tombol "Versi baru" muncul di kanan tombol akun.
class _UpdateCheck extends StatefulWidget {
  const _UpdateCheck();

  @override
  State<_UpdateCheck> createState() => _UpdateCheckState();
}

class _UpdateCheckState extends State<_UpdateCheck> {
  String _st = 'idle'; // idle / cek / terbaru / ada / gagal
  Timer? _balik;

  @override
  void dispose() {
    _balik?.cancel();
    super.dispose();
  }

  Future<void> _cek() async {
    if (_st == 'cek') return;
    _balik?.cancel();
    setState(() => _st = 'cek');
    final s = StoreScope.of(context);
    dynamic r;
    try {
      r = await s.bridge.request('update.check');
    } catch (_) {
      r = null;
    }
    if (!mounted) return;
    final ada = r is Map && r['available'] == true;
    setState(() => _st = r == null ? 'gagal' : ada ? 'ada' : 'terbaru');
    _balik = Timer(const Duration(seconds: 5), () {
      if (mounted) setState(() => _st = 'idle');
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final u = StoreScope.of(context).update;
    final (IconData? ikon, String teks, Color warna) = switch (_st) {
      'cek' => (null, 'Memeriksa...', c.onSurfaceVariant),
      'terbaru' => (Icons.check_rounded, 'Sudah versi terbaru', c.primary),
      'ada' => (Icons.arrow_circle_up_rounded, 'Versi ${u['version'] ?? 'baru'} tersedia', c.secondary),
      'gagal' => (Icons.wifi_off_rounded, 'Gagal, coba lagi', c.error),
      _ => (Icons.refresh_rounded, 'Cek pembaruan', c.onSurfaceVariant),
    };
    return TextButton(
      onPressed: _st == 'cek' ? null : _cek,
      style: TextButton.styleFrom(
        visualDensity: VisualDensity.compact,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        minimumSize: const Size(0, 28),
        foregroundColor: warna,
        disabledForegroundColor: warna,
      ),
      child: AnimatedSwitcher(
        duration: Motion.short,
        child: Row(key: ValueKey(_st), mainAxisSize: MainAxisSize.min, children: [
          if (ikon == null)
            SizedBox.square(
                dimension: 12, child: CircularProgressIndicator(strokeWidth: 1.6, color: warna))
          else
            Icon(ikon, size: 14, color: warna),
          const SizedBox(width: 6),
          Text(teks, style: t.labelSmall!.copyWith(color: warna)),
        ]),
      ),
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
/// Bisukan / nyalakan suara halaman edclub (enak saat bot jalan di
/// latar). Disimpan, jadi tetap bisu waktu app dibuka lagi.
class MuteButton extends StatelessWidget {
  const MuteButton({super.key});
  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final on = s.muted;
    return BarButton(
      key: const ValueKey('mute'),
      onTap: () => s.call('sound.set', {'muted': !on}),
      // latar terisi saat bisu = jelas suaranya sedang mati
      selected: on,
      tooltip: on ? 'Nyalakan suara' : 'Bisukan suara',
      child: AnimatedSwitcher(
        duration: Motion.short,
        child: Icon(
          on ? Icons.volume_off_rounded : Icons.volume_up_outlined,
          key: ValueKey(on),
        ),
      ),
    );
  }
}

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
        // catatan server biasanya satu kalimat tanpa '- ': tampilkan apa adanya
        final polos = '${u['notes'] ?? ''}'.trim();
        if (notes.isEmpty && polos.isNotEmpty) notes.add(polos.replaceAll('**', ''));
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Versi ${u['version']}', style: t.titleMedium),
            const SizedBox(height: 10),
            for (final n in notes)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(notes.length > 1 ? '· $n' : n, style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
              ),
            const SizedBox(height: 10),
            if ('${u['error'] ?? ''}'.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text('${u['error']}', style: t.bodySmall!.copyWith(color: c.error)),
              ),
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
