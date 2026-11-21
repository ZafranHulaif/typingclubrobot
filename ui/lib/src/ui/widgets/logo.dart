// Logo baru: keycap (tombol keyboard dilihat dari atas) + kursor miring
// + garis laju. Digambar kode -> tajam di semua ukuran & bisa beranimasi.
import 'package:material_ui/material_ui.dart';

import '../../theme/theme.dart';

class KeycapLogo extends StatefulWidget {
  const KeycapLogo({super.key, this.size = 32, this.blinking = false});
  final double size;

  /// kursor berkedip (bot sedang jalan)
  final bool blinking;

  @override
  State<KeycapLogo> createState() => _KeycapLogoState();
}

class _KeycapLogoState extends State<KeycapLogo>
    with SingleTickerProviderStateMixin {
  late final _c = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1100));

  @override
  void initState() {
    super.initState();
    if (widget.blinking) _c.repeat();
  }

  @override
  void didUpdateWidget(KeycapLogo old) {
    super.didUpdateWidget(old);
    if (widget.blinking && !_c.isAnimating) {
      _c.repeat();
    } else if (!widget.blinking && _c.isAnimating) {
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
      dimension: widget.size,
      child: AnimatedBuilder(
        animation: _c,
        builder: (_, _) {
          // kedip halus: tampil 60%, pudar cepat, muncul lagi
          final t = _c.value;
          final on = !widget.blinking
              ? 1.0
              : t < 0.55
                  ? 1.0
                  : t < 0.7
                      ? 1 - (t - 0.55) / 0.15
                      : t < 0.85
                          ? 0.0
                          : (t - 0.85) / 0.15;
          return CustomPaint(painter: _KeycapPainter(on));
        },
      ),
    );
  }
}

class _KeycapPainter extends CustomPainter {
  _KeycapPainter(this.cursor);
  final double cursor;

  @override
  void paint(Canvas canvas, Size size) {
    final k = size.width / 100;
    canvas.scale(k);
    // rok keycap (sisi bawah gelap)
    canvas.drawRRect(
        RRect.fromLTRBR(0, 0, 100, 100, const Radius.circular(26)),
        Paint()..color = const Color(0xFF6F8F1C));
    // muka atas
    final face = RRect.fromLTRBR(7, 4, 93, 84, const Radius.circular(20));
    canvas.drawRRect(
        face,
        Paint()
          ..shader = const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFDDF98A), Brand.volt, Color(0xFFADD93A)],
          ).createShader(face.outerRect));
    // garis laju
    final laju = Paint()
      ..color = Brand.ink.withValues(alpha: 0.5)
      ..strokeWidth = 6.5
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(const Offset(24, 30), const Offset(42, 30), laju);
    canvas.drawLine(const Offset(17, 44), const Offset(37, 44), laju);
    canvas.drawLine(const Offset(24, 58), const Offset(33, 58), laju);
    // kursor miring
    final path = Path()
      ..moveTo(57, 18)
      ..lineTo(70, 18)
      ..lineTo(58, 68)
      ..lineTo(45, 68)
      ..close();
    canvas.drawPath(
        path, Paint()..color = Brand.ink.withValues(alpha: cursor));
  }

  @override
  bool shouldRepaint(_KeycapPainter old) => old.cursor != cursor;
}

/// Logo + nama, buat header.
class Wordmark extends StatelessWidget {
  const Wordmark({super.key, this.blinking = false});
  final bool blinking;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      KeycapLogo(size: 26, blinking: blinking),
      const SizedBox(width: 10),
      Text('TypingBot', style: t.titleLarge),
    ]);
  }
}
