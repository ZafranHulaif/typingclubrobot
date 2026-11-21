// Kerangka: bar atas (kontrol langsung) + banner (kalau perlu) +
// panel Rencana kiri (bisa dilipat) + halaman edclub.
// Tidak ada yang menimpa halaman: WebView2 di Windows itu jendela native.
import 'package:material_ui/material_ui.dart';

import '../bridge/bridge.dart';
import '../state/store.dart';
import '../theme/theme.dart';
import 'menus.dart';
import 'plan.dart';
import 'web_area.dart';
import 'widgets/common.dart';
import 'widgets/logo.dart';

class Shell extends StatelessWidget {
  const Shell({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    return Scaffold(
      body: AnimatedSwitcher(
        duration: Motion.drawer,
        child: !s.everOnline
            ? const _Connecting(key: ValueKey('conn'))
            : Column(key: const ValueKey('app'), children: [
                const _TopBar(),
                const _Banners(),
                Expanded(
                  child: Row(children: [
                    AnimatedContainer(
                      duration: Motion.drawer,
                      curve: Motion.drawerCurve,
                      width: s.planOpen ? 272 : 0,
                      child: ClipRect(
                        child: OverflowBox(
                          alignment: Alignment.topLeft,
                          minWidth: 272,
                          maxWidth: 272,
                          child: const PlanPanel(),
                        ),
                      ),
                    ),
                    const Expanded(
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(4, 0, 12, 12),
                        child: WebArea(),
                      ),
                    ),
                  ]),
                ),
              ]),
      ),
    );
  }
}

class _Connecting extends StatelessWidget {
  const _Connecting({super.key});
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const KeycapLogo(size: 56, blinking: true),
        const SizedBox(height: 18),
        Text('Menyiapkan bot...',
            style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
      ]),
    );
  }
}

// ------------------------------------------------------------- bar atas
class _TopBar extends StatelessWidget {
  const _TopBar();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    return SizedBox(
      height: 60,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: KeycapLogo(size: 22, blinking: s.phase == 'running'),
          ),
          const SizedBox(width: 6),
          BarButton(
            selected: s.planOpen,
            onTap: s.togglePlan,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text('Rencana',
                  style: Theme.of(context).textTheme.labelLarge!.copyWith(
                      color: Theme.of(context).colorScheme.onSurface)),
              const SizedBox(width: 2),
              AnimatedRotation(
                turns: s.planOpen ? 0.5 : 0,
                duration: Motion.short,
                curve: Motion.out,
                child: const Icon(Icons.chevron_right_rounded),
              ),
            ]),
          ),
          const SizedBox(width: 8),
          const _Capsule(),
          const SizedBox(width: 6),
          const SpeedButton(),
          const Spacer(),
          const ReportButton(),
          const SizedBox(width: 2),
          const AccountButton(),
          AnimatedSize(
            duration: Motion.medium,
            curve: Motion.out,
            child: s.update['available'] == true
                ? const Padding(
                    padding: EdgeInsets.only(left: 4), child: UpdateButton())
                : const SizedBox.shrink(),
          ),
        ]),
      ),
    );
  }
}

/// Satu tombol: Mulai <-> Stop (berubah bentuk, bukan dua tombol).
class _RunButton extends StatelessWidget {
  const _RunButton();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final stopping = s.phase == 'stopping';
    final run = s.busy;
    final enabled = s.online && s.licensed && !stopping;
    final bg = !enabled
        ? c.surfaceContainerHigh
        : run
            ? c.errorContainer
            : c.primary;
    final fg = !enabled
        ? c.onSurfaceVariant
        : run
            ? c.onErrorContainer
            : c.onPrimary;
    final Widget isi = stopping
        ? Row(key: const ValueKey('stopping'), mainAxisSize: MainAxisSize.min, children: [
            SizedBox.square(
                dimension: 14,
                child: CircularProgressIndicator(strokeWidth: 2, color: fg)),
            const SizedBox(width: 8),
            Text('Berhenti...', style: t.labelLarge!.copyWith(color: fg)),
          ])
        : Row(key: ValueKey(run), mainAxisSize: MainAxisSize.min, children: [
            Icon(run ? Icons.stop_rounded : Icons.play_arrow_rounded, size: 20, color: fg),
            const SizedBox(width: 6),
            Text(run ? 'Stop' : 'Mulai', style: t.labelLarge!.copyWith(color: fg)),
          ]);
    return Press(
      enabled: enabled,
      child: AnimatedContainer(
        duration: Motion.short,
        curve: Motion.out,
        height: 32,
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(Radii.md),
        ),
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            borderRadius: BorderRadius.circular(Radii.md),
            onTap: enabled ? s.toggleRun : null,
            child: AnimatedSize(
              duration: Motion.short,
              curve: Motion.out,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 0, 16, 0),
                child: Center(
                  child: AnimatedSwitcher(
                    duration: Motion.short,
                    switchInCurve: Motion.out,
                    transitionBuilder: (ch, a) => FadeTransition(
                      opacity: a,
                      child: ScaleTransition(
                          scale: Tween(begin: 0.9, end: 1.0).animate(a), child: ch),
                    ),
                    child: isi,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Kapsul kontrol: tombol Mulai/Stop + status + level + bintang dalam
/// SATU wadah, dgn garis progres level di tepi bawah (seperti pemutar musik).
class _Capsule extends StatelessWidget {
  const _Capsule();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final look = phaseLook(context, s);
    final segs = s.segments;
    final ai = s.activeSegment;
    final seg = ai != null && ai < segs.length ? segs[ai] : null;
    final prog = s.phase == 'running'
        ? ((s.level['progress'] as num?)?.toDouble() ?? 0)
        : 0.0;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    final mulaiDari = segs.isNotEmpty ? segs.first.from : pos + 1;
    final redup = t.bodyMedium!.copyWith(
        color: c.onSurfaceVariant,
        fontFeatures: const [FontFeature.tabularFigures()]);

    final Widget kata = s.flash != null
        ? Text(s.flash!,
            key: ValueKey('f${s.flash}'),
            overflow: TextOverflow.ellipsis,
            style: t.bodyMedium!
                .copyWith(color: s.flashError ? c.error : c.onSurface))
        : Row(key: ValueKey('st${look.label}'), mainAxisSize: MainAxisSize.min, children: [
            StatusDot(color: look.color, pulse: look.live),
            const SizedBox(width: 6),
            Text(look.label, style: t.titleSmall!.copyWith(color: look.color)),
            if (s.busy && s.levelNum > 0) ...[
              Text('  ·  ', style: redup),
              Text('Level ${s.levelNum}', style: redup),
            ] else if (!s.busy && s.licensed && s.online && mulaiDari > 0) ...[
              Text('  ·  ', style: redup),
              Text('mulai dari level $mulaiDari', style: redup),
            ],
            if (seg != null) ...[
              const SizedBox(width: 10),
              StarRow(seg.stars, silver: seg.silver, size: 13),
            ],
          ]);

    return Container(
      height: 40,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: c.surfaceContainer,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: c.outlineVariant),
      ),
      child: Stack(children: [
        Row(mainAxisSize: MainAxisSize.min, children: [
          const Padding(padding: EdgeInsets.all(3), child: _RunButton()),
          const SizedBox(width: 10),
          AnimatedSize(
            duration: Motion.short,
            curve: Motion.out,
            alignment: Alignment.centerLeft,
            child: AnimatedSwitcher(
              duration: Motion.short,
              switchInCurve: Motion.out,
              layoutBuilder: (cur, prev) => Stack(
                  alignment: Alignment.centerLeft, children: [...prev, ?cur]),
              child: kata,
            ),
          ),
          const SizedBox(width: 14),
        ]),
        // garis progres level, menyatukan tombol & status
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: AnimatedOpacity(
            duration: Motion.short,
            opacity: s.phase == 'running' ? 1 : 0,
            child: SmoothProgress(value: prog, height: 2,
                color: c.primary.withValues(alpha: 0.8)),
          ),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------- banner
class _Banners extends StatelessWidget {
  const _Banners();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final items = <Widget>[
      if (!s.licensed) const _LicenseBanner(key: ValueKey('lic')),
      for (final a in s.asks) _AskBanner(key: ValueKey(a.id), ask: a),
    ];
    return AnimatedSize(
      duration: Motion.medium,
      curve: Motion.out,
      alignment: Alignment.topCenter,
      child: Column(children: items),
    );
  }
}

class _BannerShell extends StatelessWidget {
  const _BannerShell({required this.icon, required this.text, required this.actions, this.color});
  final IconData icon;
  final String text;
  final List<Widget> actions;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final col = color ?? c.tertiary;
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
      decoration: BoxDecoration(
        color: col.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(Radii.md),
        border: Border.all(color: col.withValues(alpha: 0.25)),
      ),
      child: Row(children: [
        Icon(icon, size: 18, color: col),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: t.bodyMedium)),
        ...actions,
      ]),
    );
  }
}

class _AskBanner extends StatelessWidget {
  const _AskBanner({super.key, required this.ask});
  final SidecarAsk ask;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final p = ask.params;
    final (IconData icon, String text, List<(String, Object?, bool)> acts) =
        switch (ask.method) {
      'login.needed' => (
          Icons.login_rounded,
          'Sesi edclub habis. Login dulu di halaman sebelah.',
          [('Akun sekolah', {'kind': 'sekolah'}, false), ('Login', {'kind': 'individu'}, true)]
        ),
      'level.locked' => (
          Icons.lock_outline_rounded,
          'Level ${p['level']} masih terkunci. Lewati ke level berikutnya?',
          [('Berhenti', {'skip': false}, false), ('Lewati', {'skip': true}, true)]
        ),
      'level.next' => (
          Icons.hourglass_bottom_rounded,
          'Level ${p['level']} belum maju 2 menit. Tetap tunggu?',
          [('Berhenti', {'wait': false}, false), ('Tunggu', {'wait': true}, true)]
        ),
      'browser.force_close' => (
          Icons.warning_amber_rounded,
          '${p['name']} perlu ditutup supaya bot bisa jalan.',
          [('Jangan', {'ok': false}, false), ('Tutup', {'ok': true}, true)]
        ),
      _ => (Icons.help_outline_rounded, ask.method, [('Oke', <String, dynamic>{}, true)]),
    };
    void jawab(Object? r) {
      if (ask.method == 'login.needed') s.call('login.open', r as Map<String, dynamic>);
      s.answer(ask, r);
    }

    return _BannerShell(icon: icon, text: text, actions: [
      for (final (label, r, primary) in acts)
        Padding(
          padding: const EdgeInsets.only(left: 6),
          child: primary
              ? Press(child: FilledButton(onPressed: () => jawab(r), child: Text(label)))
              : TextButton(onPressed: () => jawab(r), child: Text(label)),
        ),
    ]);
  }
}

class _LicenseBanner extends StatefulWidget {
  const _LicenseBanner({super.key});
  @override
  State<_LicenseBanner> createState() => _LicenseBannerState();
}

class _LicenseBannerState extends State<_LicenseBanner> {
  final _nick = TextEditingController();
  bool _kirim = false;

  @override
  void dispose() {
    _nick.dispose();
    super.dispose();
  }

  Future<void> _go(AppStore s) async {
    setState(() => _kirim = true);
    await s.call('license.request', {'nickname': _nick.text});
    if (mounted) setState(() => _kirim = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final st = s.license['state'];
    if (st == 'pending') {
      return _BannerShell(
        icon: Icons.key_rounded,
        color: c.secondary,
        text: 'Permintaan terkirim. Bot aktif begitu pemilik menyetujui.',
        actions: const [
          Padding(
            padding: EdgeInsets.all(10),
            child: SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2)),
          ),
        ],
      );
    }
    if (st == 'revoked') {
      return _BannerShell(
        icon: Icons.block_rounded,
        color: c.error,
        text: 'Akses perangkat ini dicabut. Hubungi pemilik kalau ini keliru.',
        actions: const [],
      );
    }
    return _BannerShell(
      icon: Icons.key_rounded,
      color: c.secondary,
      text: 'Aktifkan TypingBot: tulis nama panggilanmu.',
      actions: [
        SizedBox(
          width: 180,
          child: TextField(
            controller: _nick,
            style: t.bodyMedium,
            onSubmitted: (_) => _go(s),
            decoration: const InputDecoration(hintText: 'Nama panggilan', isDense: true),
          ),
        ),
        const SizedBox(width: 8),
        Press(
          child: FilledButton(
            onPressed: _kirim ? null : () => _go(s),
            child: Text(_kirim ? 'Mengirim...' : 'Kirim'),
          ),
        ),
      ],
    );
  }
}
