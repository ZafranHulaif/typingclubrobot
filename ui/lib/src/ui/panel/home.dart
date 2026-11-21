// Halaman utama panel: ask aktif, status, kontrol, kecepatan, rentang, log.
import 'package:material_ui/material_ui.dart';

import '../../bridge/bridge.dart';
import '../../state/store.dart';
import '../../theme/theme.dart';
import '../widgets/common.dart';
import 'license.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final lic = s.license['state'];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
      children: [
        for (final a in s.asks) ...[
          _AskCard(ask: a),
          const SizedBox(height: 12),
        ],
        if (lic != null && lic != 'ok') ...[
          const LicenseCard(),
          const SizedBox(height: 12),
        ],
        const _StatusCard(),
        const SizedBox(height: 12),
        const _Controls(),
        const SizedBox(height: 24),
        const _SpeedCard(),
        const SizedBox(height: 24),
        const _RangeCard(),
        if (s.results.isNotEmpty) ...[
          const SizedBox(height: 24),
          const _Results(),
        ],
        const SizedBox(height: 24),
        const _ActivityLog(),
      ],
    );
  }
}

// ------------------------------------------------------------ status
class _StatusCard extends StatelessWidget {
  const _StatusCard();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final look = phaseLook(context, s);
    final prog = (s.level['progress'] as num?)?.toDouble() ?? 0;
    final err = '${s.bot['error'] ?? ''}';
    return SurfaceCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // label status sudah ada di bar atas: di sini cuma hitungan sesi
        if ((s.stats['levels_done'] ?? 0) != 0) ...[
          Text('${s.stats['levels_done']} level selesai sesi ini',
              style: t.labelSmall!.copyWith(color: look.color)),
          const SizedBox(height: 8),
        ],
        AnimatedSwitcher(
          duration: Motion.medium,
          switchInCurve: Motion.decelerate,
          transitionBuilder: (child, a) => FadeTransition(
            opacity: a,
            child: SlideTransition(
              position: Tween(begin: const Offset(0, 0.15), end: Offset.zero)
                  .animate(a),
              child: child,
            ),
          ),
          layoutBuilder: (cur, prev) => Stack(
              alignment: Alignment.topLeft, children: [...prev, ?cur]),
          child: Text(
            '${s.activity['headline'] ?? 'Siap'}',
            key: ValueKey(s.activity['headline']),
            style: t.displaySmall,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          err.isNotEmpty && s.phase == 'error'
              ? err
              : '${s.activity['sub'] ?? ''}',
          style: t.bodyMedium!.copyWith(
              color: s.phase == 'error' ? c.error : c.onSurfaceVariant),
        ),
        AnimatedSize(
          duration: Motion.medium,
          curve: Motion.standard,
          child: s.busy
              ? Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: SmoothProgress(
                      value: s.phase == 'starting' ? null : prog,
                      color: s.phase == 'paused' ? c.tertiary : c.primary),
                )
              : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------ kontrol
class _Controls extends StatelessWidget {
  const _Controls();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final c = Theme.of(context).colorScheme;
    final lisensiOk = s.license['state'] == null || s.license['state'] == 'ok';
    final stopBtn = OutlinedButton.icon(
      onPressed: s.phase == 'stopping' ? null : () => s.call('bot.stop'),
      style: OutlinedButton.styleFrom(
        foregroundColor: c.error,
        side: BorderSide(color: c.error.withValues(alpha: 0.4)),
        minimumSize: const Size(0, 52),
      ),
      icon: const Icon(Icons.stop_rounded),
      label: const Text('Stop'),
    );
    final Widget row = switch (s.phase) {
      'starting' => Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: null,
              style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
              icon: const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2)),
              label: const Text('Menyiapkan...'),
            ),
          ),
          const SizedBox(width: 10),
          stopBtn,
        ]),
      'running' => Row(children: [
          Expanded(
            child: FilledButton.tonalIcon(
              onPressed: () => s.call('bot.pause'),
              style: FilledButton.styleFrom(
                minimumSize: const Size(0, 52),
                backgroundColor: c.tertiaryContainer,
                foregroundColor: c.onTertiaryContainer,
              ),
              icon: const Icon(Icons.pause_rounded),
              label: const Text('Jeda'),
            ),
          ),
          const SizedBox(width: 10),
          stopBtn,
        ]),
      'paused' => Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: () => s.call('bot.resume'),
              style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
              icon: const Icon(Icons.play_arrow_rounded),
              label: const Text('Lanjut'),
            ),
          ),
          const SizedBox(width: 10),
          stopBtn,
        ]),
      'stopping' => Row(children: [
          Expanded(
            child: OutlinedButton(
              onPressed: null,
              style: OutlinedButton.styleFrom(minimumSize: const Size(0, 52)),
              child: const Text('Menghentikan...'),
            ),
          ),
        ]),
      _ => Row(children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: s.online && lisensiOk ? s.start : null,
              style: FilledButton.styleFrom(minimumSize: const Size(0, 52)),
              icon: const Icon(Icons.play_arrow_rounded, size: 22),
              label: const Text('Mulai'),
            ),
          ),
        ]),
    };
    return AnimatedSwitcher(
      duration: Motion.short,
      child: KeyedSubtree(key: ValueKey(s.phase), child: row),
    );
  }
}

// ------------------------------------------------------------ kecepatan
class _SpeedCard extends StatefulWidget {
  const _SpeedCard();
  @override
  State<_SpeedCard> createState() => _SpeedCardState();
}

class _SpeedCardState extends State<_SpeedCard> {
  int? _drag; // indeks tier saat digeser (optimistis)

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final tiers = s.tiers;
    var idx = tiers.indexOf(s.wpm);
    if (idx < 0) {
      idx = tiers.indexWhere((w) => w >= s.wpm);
      if (idx < 0) idx = tiers.length - 1;
    }
    final i = _drag ?? idx;
    final w = tiers[i];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Eyebrow('Kecepatan',
          trailing: Text(s.hotkeysOn ? 'F10 ganti cepat' : '',
              style: t.labelSmall!.copyWith(color: c.onSurfaceVariant))),
      SurfaceCard(
        padding: const EdgeInsets.fromLTRB(18, 14, 10, 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: [
            TweenAnimationBuilder<double>(
              tween: Tween(end: w.toDouble()),
              duration: Motion.medium,
              curve: Motion.standard,
              builder: (_, v, _) => Text('${v.round()}',
                  style: t.displayMedium!.copyWith(
                      fontFeatures: const [FontFeature.tabularFigures()])),
            ),
            const SizedBox(width: 6),
            Text('wpm',
                style: t.titleMedium!.copyWith(color: c.onSurfaceVariant)),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(s.speedName(w),
                  style: t.labelLarge!.copyWith(color: c.primary)),
            ),
          ]),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              tickMarkShape: const RoundSliderTickMarkShape(tickMarkRadius: 1.5),
              activeTickMarkColor: c.onPrimary.withValues(alpha: 0.5),
              inactiveTickMarkColor: c.outline,
              showValueIndicator: ShowValueIndicator.never,
            ),
            child: Slider(
              value: i.toDouble(),
              min: 0,
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
      ),
    ]);
  }
}

// ------------------------------------------------------------ rentang
String rangeSummary(AppStore s) {
  if (s.busy) {
    // saat jalan: tampilkan rentang yg BENAR2 dipakai engine
    final a = s.range['start'], b = s.range['end'];
    return (b == null || b == 0) ? 'Dari level $a sampai habis' : 'Level $a sampai $b';
  }
  final ch = s.rangeChoice;
  final pos = (s.range['position'] as num?)?.toInt() ?? 0;
  switch (ch['mode']) {
    case 'custom':
      final a = ch['start'], b = ch['end'];
      return (b == null || b == 0) ? 'Dari level $a sampai habis' : 'Level $a sampai $b';
    case 'halaman':
      return 'Pilih sendiri di halaman edclub';
    default:
      return pos > 0
          ? 'Lanjut dari level ${pos + 1}'
          : 'Lanjut dari posisi terakhir';
  }
}

class _RangeCard extends StatelessWidget {
  const _RangeCard();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final total = (s.range['total'] as num?)?.toInt() ?? 0;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Eyebrow('Level yang dikerjakan'),
      SurfaceCard(
        onTap: s.busy ? null : () => s.go(PanelPage.range),
        child: Row(children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: c.secondaryContainer,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(Icons.route_rounded, color: c.onSecondaryContainer),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(rangeSummary(s), style: t.titleSmall),
              const SizedBox(height: 2),
              Text(
                total > 0
                    ? 'Progres akun: $pos dari $total level'
                    : 'Progres akun belum terbaca',
                style: t.bodySmall!.copyWith(color: c.onSurfaceVariant),
              ),
            ]),
          ),
          if (!s.busy)
            Icon(Icons.chevron_right_rounded, color: c.onSurfaceVariant),
        ]),
      ),
    ]);
  }
}

// ------------------------------------------------------------ hasil
class _Results extends StatelessWidget {
  const _Results();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final list = s.results.take(5).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Eyebrow('Baru selesai'),
      SurfaceCard(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        child: Column(children: [
          for (final r in list)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                SizedBox(
                  width: 56,
                  child: Text('L${r.level}',
                      style: t.titleSmall!.copyWith(
                          fontFeatures: const [FontFeature.tabularFigures()])),
                ),
                StarRow(r.stars),
                const Spacer(),
                Text('${r.wpm} wpm',
                    style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
              ]),
            ),
        ]),
      ),
    ]);
  }
}

// ------------------------------------------------------------ log
class _ActivityLog extends StatelessWidget {
  const _ActivityLog();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final list = s.logs.take(8).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Eyebrow('Aktivitas'),
      if (list.isEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
          child: Text('Belum ada aktivitas. Catatan bot muncul di sini.',
              style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
        ),
      for (final (i, l) in list.indexed)
        AnimatedOpacity(
          duration: Motion.medium,
          opacity: 1 - i * 0.09,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                '${l.time.hour.toString().padLeft(2, '0')}:'
                '${l.time.minute.toString().padLeft(2, '0')}',
                style: t.bodySmall!.copyWith(
                    color: c.outline,
                    fontFeatures: const [FontFeature.tabularFigures()]),
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(l.text, style: t.bodySmall)),
            ]),
          ),
        ),
    ]);
  }
}

// ------------------------------------------------------------ ask
class _AskCard extends StatelessWidget {
  const _AskCard({required this.ask});
  final SidecarAsk ask;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final p = ask.params;
    final (IconData icon, String title, String body, List<(String, Object?, bool)> actions) =
        switch (ask.method) {
      'login.needed' => (
          Icons.login_rounded,
          'Login dulu ya',
          'Sesi edclub kamu habis. Pilih cara login, halaman login terbuka di sebelah kiri.',
          [
            ('Akun sekolah', {'kind': 'sekolah'}, false),
            ('Login biasa', {'kind': 'individu'}, true),
          ]
        ),
      'level.locked' => (
          Icons.lock_rounded,
          'Level ${p['level']} masih terkunci',
          'Level ini belum bisa dibuka. Lewati ke level berikutnya yang terbuka?',
          [
            ('Berhenti', {'skip': false}, false),
            ('Lewati', {'skip': true}, true),
          ]
        ),
      'level.next' => (
          Icons.hourglass_bottom_rounded,
          'Masih menunggu?',
          'Level ${p['level']} belum maju selama 2 menit. Mau tetap menunggu?',
          [
            ('Berhenti', {'wait': false}, false),
            ('Tunggu lagi', {'wait': true}, true),
          ]
        ),
      'browser.force_close' => (
          Icons.warning_amber_rounded,
          '${p['name']} sedang terbuka',
          'Browser perlu ditutup dulu supaya bot bisa memakainya. Tutup sekarang?',
          [
            ('Jangan', {'ok': false}, false),
            ('Tutup', {'ok': true}, true),
          ]
        ),
      _ => (
          Icons.help_outline_rounded,
          'Bot butuh jawaban',
          ask.method,
          [('Oke', <String, dynamic>{}, true)]
        ),
    };
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Motion.long,
      curve: Motion.decelerate,
      builder: (_, v, child) => Opacity(
        opacity: v,
        child: Transform.translate(offset: Offset(0, 12 * (1 - v)), child: child),
      ),
      child: SurfaceCard(
        color: c.tertiaryContainer.withValues(alpha: 0.55),
        borderColor: c.tertiary.withValues(alpha: 0.35),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(icon, color: c.tertiary, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(title, style: t.titleMedium)),
          ]),
          const SizedBox(height: 8),
          Text(body, style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
          const SizedBox(height: 14),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            for (final (label, r, primary) in actions) ...[
              const SizedBox(width: 8),
              primary
                  ? FilledButton(
                      onPressed: () {
                        if (ask.method == 'login.needed') {
                          s.call('login.open', r as Map<String, dynamic>);
                        }
                        s.answer(ask, r);
                      },
                      child: Text(label))
                  : TextButton(
                      onPressed: () {
                        if (ask.method == 'login.needed') {
                          s.call('login.open', r as Map<String, dynamic>);
                        }
                        s.answer(ask, r);
                      },
                      child: Text(label)),
            ],
          ]),
        ]),
      ),
    );
  }
}
