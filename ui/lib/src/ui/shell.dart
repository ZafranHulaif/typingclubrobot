// Kerangka jendela: bar atas + area web + panel kanan (semua alur di panel,
// tidak ada yang menimpa area web - jendela WebView2 itu native).
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'panel/home.dart';
import 'panel/pages.dart';
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
        duration: Motion.long,
        child: !s.everOnline
            ? const _Connecting(key: ValueKey('conn'))
            : LayoutBuilder(
                key: const ValueKey('app'),
                builder: (context, box) {
                  final wide = box.maxWidth >= 820;
                  final panelW = box.maxWidth >= 1180 ? 400.0 : 352.0;
                  return Column(children: [
                    const _TopBar(),
                    Expanded(
                      child: wide
                          ? Row(children: [
                              const Expanded(
                                child: Padding(
                                  padding: EdgeInsets.fromLTRB(16, 0, 8, 16),
                                  child: WebArea(),
                                ),
                              ),
                              SizedBox(width: panelW, child: const _Panel()),
                            ])
                          : Column(children: [
                              SizedBox(
                                height: box.maxHeight * 0.4,
                                child: const Padding(
                                  padding: EdgeInsets.fromLTRB(12, 0, 12, 8),
                                  child: WebArea(),
                                ),
                              ),
                              const Expanded(child: _Panel()),
                            ]),
                    ),
                  ]);
                },
              ),
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
        const KeycapLogo(size: 72, blinking: true),
        const SizedBox(height: 24),
        Text('TypingBot', style: t.headlineMedium),
        const SizedBox(height: 6),
        Text('Menyiapkan mesin bot...',
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
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final look = phaseLook(context, s);
    final lvl = (s.level['num'] as num?)?.toInt() ?? 0;
    final aktif = '${s.account['active'] ?? ''}';
    return SizedBox(
      height: 64,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [
          Wordmark(blinking: s.phase == 'running'),
          const SizedBox(width: 20),
          // pil status
          AnimatedContainer(
            duration: Motion.medium,
            padding: const EdgeInsets.fromLTRB(8, 6, 12, 6),
            decoration: BoxDecoration(
              color: look.color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(99),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              StatusDot(color: look.color, pulse: s.phase == 'running'),
              const SizedBox(width: 6),
              Text(
                s.busy && lvl > 0 ? '${look.label}  ·  Level $lvl' : look.label,
                style: t.labelMedium!.copyWith(color: look.color),
              ),
            ]),
          ),
          if (!s.online) ...[
            const SizedBox(width: 10),
            Text('Menyambung ulang...',
                style: t.labelSmall!.copyWith(color: c.onSurfaceVariant)),
          ],
          const Spacer(),
          AnimatedSwitcher(
            duration: Motion.medium,
            transitionBuilder: (ch, a) => ScaleTransition(scale: a, child: FadeTransition(opacity: a, child: ch)),
            child: s.update['available'] == true
                ? Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilledButton.tonalIcon(
                      onPressed: () => s.go(PanelPage.update),
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(0, 36),
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        backgroundColor: c.secondaryContainer,
                        foregroundColor: c.onSecondaryContainer,
                      ),
                      icon: const Icon(Icons.arrow_circle_up_rounded, size: 18),
                      label: Text('Versi ${s.update['version']}'),
                    ),
                  )
                : const SizedBox.shrink(),
          ),
          // chip akun
          Material(
            color: s.page == PanelPage.accounts ? c.surfaceContainerHigh : Colors.transparent,
            borderRadius: BorderRadius.circular(99),
            child: InkWell(
              borderRadius: BorderRadius.circular(99),
              onTap: () => s.go(s.page == PanelPage.accounts ? PanelPage.home : PanelPage.accounts),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(6, 6, 12, 6),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  CircleAvatar(
                    radius: 13,
                    backgroundColor: s.bot['needs_login'] == true ? c.tertiary : c.primary,
                    foregroundColor: c.onPrimary,
                    child: Text(aktif.isEmpty ? '?' : aktif[0].toUpperCase(),
                        style: t.labelMedium!.copyWith(color: c.onPrimary)),
                  ),
                  const SizedBox(width: 8),
                  Text(aktif.isEmpty ? 'Akun' : aktif, style: t.labelLarge),
                  const SizedBox(width: 2),
                  Icon(Icons.expand_more_rounded, size: 18, color: c.onSurfaceVariant),
                ]),
              ),
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Laporkan masalah',
            isSelected: s.page == PanelPage.report,
            onPressed: () => s.go(s.page == PanelPage.report ? PanelPage.home : PanelPage.report),
            icon: const Icon(Icons.bug_report_outlined),
          ),
          IconButton(
            tooltip: 'Pengaturan',
            isSelected: s.page == PanelPage.settings,
            onPressed: () => s.go(s.page == PanelPage.settings ? PanelPage.home : PanelPage.settings),
            icon: const Icon(Icons.tune_rounded),
          ),
        ]),
      ),
    );
  }
}

// ------------------------------------------------------------- panel
class _Panel extends StatelessWidget {
  const _Panel();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final Widget page = switch (s.page) {
      PanelPage.home => const HomePage(),
      PanelPage.range => const RangePage(),
      PanelPage.accounts => const AccountsPage(),
      PanelPage.report => const ReportPage(),
      PanelPage.settings => const SettingsPage(),
      PanelPage.update => const UpdatePage(),
      PanelPage.license => const HomePage(),
    };
    final kembali = s.page == PanelPage.home;
    return Stack(children: [
      AnimatedSwitcher(
        duration: Motion.medium,
        switchInCurve: Motion.decelerate,
        switchOutCurve: Motion.accelerate,
        transitionBuilder: (child, a) {
          // shared-axis X: halaman baru geser dari kanan, beranda dari kiri
          final masuk = child.key == ValueKey(s.page);
          final dx = (kembali ? -1 : 1) * (masuk ? 0.06 : -0.06);
          return FadeTransition(
            opacity: a,
            child: SlideTransition(
              position: Tween(begin: Offset(dx, 0), end: Offset.zero).animate(a),
              child: child,
            ),
          );
        },
        layoutBuilder: (cur, prev) => Stack(
            alignment: Alignment.topCenter, children: [...prev, ?cur]),
        child: KeyedSubtree(key: ValueKey(s.page), child: page),
      ),
      const Positioned(left: 16, right: 16, bottom: 16, child: _ToastHost()),
    ]);
  }
}

class _ToastHost extends StatelessWidget {
  const _ToastHost();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final toast = s.toast;
    return AnimatedSwitcher(
      duration: Motion.medium,
      switchInCurve: Motion.decelerate,
      switchOutCurve: Motion.accelerate,
      transitionBuilder: (child, a) => FadeTransition(
        opacity: a,
        child: SlideTransition(
          position: Tween(begin: const Offset(0, 0.4), end: Offset.zero).animate(a),
          child: child,
        ),
      ),
      child: toast == null
          ? const SizedBox.shrink()
          : Material(
              key: ValueKey(toast.id),
              color: c.inverseSurface,
              elevation: 6,
              borderRadius: BorderRadius.circular(14),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Row(children: [
                  Icon(toast.error ? Icons.error_outline_rounded : Icons.check_circle_outline_rounded,
                      size: 18, color: toast.error ? const Color(0xFFC0392B) : const Color(0xFF4F6A12)),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(toast.text,
                        style: t.bodyMedium!.copyWith(color: c.onInverseSurface)),
                  ),
                ]),
              ),
            ),
    );
  }
}
