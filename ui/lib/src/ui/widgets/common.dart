import 'package:material_ui/material_ui.dart';

import '../../state/store.dart';
import '../../theme/theme.dart';

/// Status inti: apakah bot sedang mengetik? (satu-satunya tempat status)
({Color color, String label, bool live}) phaseLook(
    BuildContext context, AppStore s) {
  final c = Theme.of(context).colorScheme;
  if (!s.online) {
    return (color: c.onSurfaceVariant, label: 'Menyambung ulang', live: false);
  }
  if (s.bot['needs_login'] == true) {
    return (color: c.tertiary, label: 'Perlu login', live: false);
  }
  if (!s.licensed) {
    return (color: c.tertiary, label: 'Belum aktif', live: false);
  }
  return switch (s.phase) {
    'starting' => (color: c.primary, label: 'Menyiapkan', live: true),
    'running' => (color: c.primary, label: 'Mengetik', live: true),
    'paused' => (color: c.tertiary, label: 'Berhenti sebentar', live: false),
    'stopping' => (color: c.onSurfaceVariant, label: 'Menghentikan', live: false),
    'done' => (color: c.secondary, label: 'Rencana selesai', live: false),
    'error' => (color: c.error, label: 'Macet', live: false),
    _ => (color: c.onSurfaceVariant, label: 'Siap', live: false),
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
      vsync: this, duration: const Duration(milliseconds: 1400));

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
      dimension: 14,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) {
          final t = Motion.out.transform(_c.value);
          return Stack(alignment: Alignment.center, children: [
            if (widget.pulse)
              Container(
                width: 7 + 7 * t,
                height: 7 + 7 * t,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: widget.color.withValues(alpha: 0.4 * (1 - t)),
                ),
              ),
            AnimatedContainer(
              duration: Motion.short,
              width: 7,
              height: 7,
              decoration:
                  BoxDecoration(shape: BoxShape.circle, color: widget.color),
            ),
          ]);
        },
      ),
    );
  }
}

/// Umpan balik tekan: mengecil ke 0.97 (terasa "didengar").
class Press extends StatefulWidget {
  const Press({super.key, required this.child, this.enabled = true});
  final Widget child;
  final bool enabled;
  @override
  State<Press> createState() => _PressState();
}

class _PressState extends State<Press> {
  bool _down = false;
  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) {
        if (widget.enabled) setState(() => _down = true);
      },
      onPointerUp: (_) => setState(() => _down = false),
      onPointerCancel: (_) => setState(() => _down = false),
      child: AnimatedScale(
        scale: _down ? 0.97 : 1,
        duration: Motion.press,
        curve: Motion.out,
        child: widget.child,
      ),
    );
  }
}

/// Progress linier tipis dgn nilai beranimasi.
class SmoothProgress extends StatelessWidget {
  const SmoothProgress(
      {super.key, required this.value, this.color, this.height = 3});
  final double? value;
  final Color? color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    if (value == null) {
      return LinearProgressIndicator(
        minHeight: height,
        color: color ?? c.primary,
        backgroundColor: c.surfaceContainerHighest,
      );
    }
    return TweenAnimationBuilder<double>(
      tween: Tween(end: value!.clamp(0, 1)),
      duration: Motion.medium,
      curve: Motion.out,
      builder: (_, v, _) => SizedBox(
        height: height,
        child: Stack(children: [
          Container(color: c.surfaceContainerHighest),
          FractionallySizedBox(
              widthFactor: v, child: Container(color: color ?? c.primary)),
        ]),
      ),
    );
  }
}

const silverStar = Color(0xFFDCE3EE);

/// Bintang 1-5. silver = bintang perak (nilai tertinggi edclub).
class StarRow extends StatelessWidget {
  const StarRow(this.stars,
      {super.key, this.size = 14, this.silver = false, this.onTap});
  final int stars;
  final double size;
  final bool silver;

  /// klik bintang ke-n (1..5) -> pemilih bintang
  final ValueChanged<int>? onTap;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final on = silver ? silverStar : c.tertiary;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < 5; i++)
          GestureDetector(
            onTap: onTap == null ? null : () => onTap!(i + 1),
            child: MouseRegion(
              cursor: onTap == null ? MouseCursor.defer : SystemMouseCursors.click,
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: onTap == null ? 0 : 1),
                child: AnimatedSwitcher(
                  duration: Motion.short,
                  switchInCurve: Motion.out,
                  transitionBuilder: (ch, a) => ScaleTransition(
                      scale: Tween(begin: 0.8, end: 1.0).animate(a),
                      child: FadeTransition(opacity: a, child: ch)),
                  child: Icon(
                    i < stars ? Icons.star_rounded : Icons.star_outline_rounded,
                    key: ValueKey('$i${i < stars}$silver'),
                    size: size,
                    color: i < stars ? on : c.outline,
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// Popup kecil yang tumbuh dari tombol pemicunya (origin-aware).
/// Saat terbuka, halaman web native disembunyikan (lihat AppStore.occlude).
class Popover extends StatefulWidget {
  const Popover({
    super.key,
    required this.trigger,
    required this.content,
    this.width = 280,
    this.alignRight = true,
  });

  /// trigger(context, toggle, isOpen)
  final Widget Function(BuildContext, VoidCallback, bool) trigger;

  /// content(context, close)
  final Widget Function(BuildContext, VoidCallback) content;
  final double width;
  final bool alignRight;

  @override
  State<Popover> createState() => _PopoverState();
}

class _PopoverState extends State<Popover> with SingleTickerProviderStateMixin {
  final _ctl = OverlayPortalController();
  final _key = GlobalKey();
  late final _anim =
      AnimationController(vsync: this, duration: Motion.short, reverseDuration: const Duration(milliseconds: 120));
  final _group = Object();

  bool get _open => _ctl.isShowing;

  void _toggle() => _open ? _close() : _show();

  void _show() {
    StoreScope.read(context).occlude(true);
    _ctl.show();
    _anim.forward(from: 0);
    setState(() {});
  }

  Future<void> _close() async {
    if (!_open) return;
    await _anim.reverse();
    if (!mounted) return;
    _ctl.hide();
    StoreScope.read(context).occlude(false);
    setState(() {});
  }

  @override
  void dispose() {
    if (_open) StoreScope.read(context).occlude(false);
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return TapRegion(
      groupId: _group,
      child: OverlayPortal(
        controller: _ctl,
        overlayChildBuilder: (ctx) {
          // posisi pemicu di layar; popup di bawahnya, atau di atas kalau
          // tidak muat, dan selalu dijepit di dalam jendela
          final box = _key.currentContext?.findRenderObject() as RenderBox?;
          if (box == null || !box.hasSize) return const SizedBox.shrink();
          final r = box.localToGlobal(Offset.zero) & box.size;
          return CustomSingleChildLayout(
            delegate: _PopLayout(r, widget.alignRight, (up) => _up = up),
            child: TapRegion(
              groupId: _group,
              onTapOutside: (_) => _close(),
              child: AnimatedBuilder(
                animation: _anim,
                builder: (_, child) {
                  final t = Motion.out.transform(_anim.value);
                  final al = Alignment(widget.alignRight ? 1 : -1, _up ? 1 : -1);
                  return Opacity(
                    opacity: _anim.value,
                    child: Transform.scale(
                        scale: 0.96 + 0.04 * t, alignment: al, child: child),
                  );
                },
                child: Material(
                  color: c.surfaceContainerHigh,
                  elevation: 8,
                  shadowColor: Colors.black,
                  clipBehavior: Clip.antiAlias,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(Radii.lg),
                    side: BorderSide(color: c.outlineVariant),
                  ),
                  child: SizedBox(
                    width: widget.width,
                    child: SingleChildScrollView(
                        child: widget.content(ctx, _close)),
                  ),
                ),
              ),
            ),
          );
        },
        child: KeyedSubtree(
            key: _key, child: widget.trigger(context, _toggle, _open)),
      ),
    );
  }

  bool _up = false;
}

/// Taruh popup relatif ke pemicu: bawah dulu, balik ke atas kalau tak
/// muat, jepit ke tepi jendela (margin 8). Tinggi maks = layar - 16.
class _PopLayout extends SingleChildLayoutDelegate {
  _PopLayout(this.anchor, this.alignRight, this.onFlip);
  final Rect anchor;
  final bool alignRight;
  final ValueChanged<bool> onFlip;
  static const _m = 8.0, _gap = 6.0;

  @override
  BoxConstraints getConstraintsForChild(BoxConstraints c) =>
      BoxConstraints.loose(Size(c.maxWidth - 2 * _m, c.maxHeight - 2 * _m));

  @override
  Offset getPositionForChild(Size size, Size child) {
    var x = alignRight ? anchor.right - child.width : anchor.left;
    x = x.clamp(_m, size.width - _m - child.width);
    final bawah = anchor.bottom + _gap;
    final atas = anchor.top - _gap - child.height;
    final muatBawah = bawah + child.height <= size.height - _m;
    final up = !muatBawah && atas >= _m;
    onFlip(up);
    var y = up ? atas : bawah;
    y = y.clamp(_m, (size.height - _m - child.height).clamp(_m, double.infinity));
    return Offset(x, y);
  }

  @override
  bool shouldRelayout(_PopLayout old) =>
      old.anchor != anchor || old.alignRight != alignRight;
}
