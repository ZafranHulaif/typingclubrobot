import 'package:material_ui/material_ui.dart';

import '../../state/store.dart';
import '../../theme/theme.dart';

/// Warna + teks status dari fase bot.
({Color color, String label}) phaseLook(BuildContext context, AppStore s) {
  final c = Theme.of(context).colorScheme;
  if (!s.online) return (color: c.onSurfaceVariant, label: 'Terputus');
  if (s.bot['needs_login'] == true) {
    return (color: c.tertiary, label: 'Perlu login');
  }
  if (s.license['state'] != null && s.license['state'] != 'ok') {
    return (color: c.tertiary, label: 'Perlu aktivasi');
  }
  return switch (s.phase) {
    'starting' => (color: c.primary, label: 'Menyiapkan'),
    'running' => (color: c.primary, label: 'Berjalan'),
    'paused' => (color: c.tertiary, label: 'Dijeda'),
    'stopping' => (color: c.onSurfaceVariant, label: 'Menghentikan'),
    'done' => (color: c.secondary, label: 'Selesai'),
    'error' => (color: c.error, label: 'Ada masalah'),
    _ => (color: c.onSurfaceVariant, label: 'Siap'),
  };
}

class StatusDot extends StatefulWidget {
  const StatusDot({super.key, required this.color, this.pulse = false});
  final Color color;
  final bool pulse;

  @override
  State<StatusDot> createState() => _StatusDotState();
}

class _StatusDotState extends State<StatusDot>
    with SingleTickerProviderStateMixin {
  late final _c = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1600));

  @override
  void initState() {
    super.initState();
    if (widget.pulse) _c.repeat();
  }

  @override
  void didUpdateWidget(StatusDot old) {
    super.didUpdateWidget(old);
    if (widget.pulse && !_c.isAnimating) _c.repeat();
    if (!widget.pulse && _c.isAnimating) {
      _c.stop();
      _c.value = 0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: 16,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) {
          final t = Curves.easeOut.transform(_c.value);
          return Stack(alignment: Alignment.center, children: [
            if (widget.pulse)
              Container(
                width: 8 + 8 * t,
                height: 8 + 8 * t,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: widget.color.withValues(alpha: 0.35 * (1 - t)),
                ),
              ),
            AnimatedContainer(
              duration: Motion.medium,
              width: 8,
              height: 8,
              decoration:
                  BoxDecoration(shape: BoxShape.circle, color: widget.color),
            ),
          ]);
        },
      ),
    );
  }
}

/// Kartu permukaan standar panel.
class SurfaceCard extends StatelessWidget {
  const SurfaceCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.onTap,
    this.color,
    this.borderColor,
  });
  final Widget child;
  final EdgeInsets padding;
  final VoidCallback? onTap;
  final Color? color;
  final Color? borderColor;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final r = BorderRadius.circular(18);
    return AnimatedContainer(
      duration: Motion.medium,
      curve: Motion.standard,
      decoration: BoxDecoration(
        color: color ?? c.surfaceContainer,
        borderRadius: r,
        border: Border.all(color: borderColor ?? c.outlineVariant),
      ),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: r,
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

/// Label kecil di atas grup (hirarki: label > hint).
class Eyebrow extends StatelessWidget {
  const Eyebrow(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
      child: Row(children: [
        Text(text.toUpperCase(),
            style: t.labelSmall!.copyWith(color: c.onSurfaceVariant)),
        const Spacer(),
        ?trailing,
      ]),
    );
  }
}

/// Header halaman panel (tombol kembali + judul).
class PanelHeader extends StatelessWidget {
  const PanelHeader(this.title, {super.key, this.subtitle, this.onBack});
  final String title;
  final String? subtitle;
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 4, 16),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        IconButton(
          tooltip: 'Kembali',
          onPressed: onBack ??
              () => StoreScope.read(context).go(PanelPage.home),
          icon: const Icon(Icons.arrow_back_rounded),
        ),
        const SizedBox(width: 4),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: t.headlineSmall),
              if (subtitle != null) ...[
                const SizedBox(height: 4),
                Text(subtitle!,
                    style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
              ],
            ]),
          ),
        ),
      ]),
    );
  }
}

/// Progress linier membulat dgn animasi nilai.
class SmoothProgress extends StatelessWidget {
  const SmoothProgress(
      {super.key, required this.value, this.color, this.height = 6});
  final double? value;
  final Color? color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    if (value == null) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(height),
        child: LinearProgressIndicator(
          minHeight: height,
          color: color ?? c.primary,
          backgroundColor: c.surfaceContainerHighest,
        ),
      );
    }
    return TweenAnimationBuilder<double>(
      tween: Tween(end: value!.clamp(0, 1)),
      duration: Motion.medium,
      curve: Motion.standard,
      builder: (_, v, _) => ClipRRect(
        borderRadius: BorderRadius.circular(height),
        child: SizedBox(
          height: height,
          child: Stack(children: [
            Container(color: c.surfaceContainerHighest),
            FractionallySizedBox(
              widthFactor: v,
              child: Container(
                decoration: BoxDecoration(
                  color: color ?? c.primary,
                  borderRadius: BorderRadius.circular(height),
                ),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Bintang kecil (1-5).
class StarRow extends StatelessWidget {
  const StarRow(this.stars, {super.key, this.size = 14});
  final int stars;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < 5; i++)
          Icon(i < stars ? Icons.star_rounded : Icons.star_outline_rounded,
              size: size,
              color: i < stars ? c.tertiary : c.outline),
      ],
    );
  }
}
