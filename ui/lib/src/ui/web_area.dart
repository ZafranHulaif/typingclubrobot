// Area halaman edclub.
// Windows (embedded): kotak kosong; posisinya dikirim ke runner C++ yang
//   menaruh jendela WebView2 milik sidecar persis di sini.
// Preview (web/mock): pratinjau pelajaran palsu yang mengikuti progres.
// Cover (boot/ganti akun/OAuth) digambar Flutter di area yang sama
// selagi sidecar menyembunyikan jendela WebView2.
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../state/store.dart';
import '../theme/theme.dart';
import 'widgets/common.dart';
import 'widgets/logo.dart';

const _host = MethodChannel('typingbot/web_host');

class WebArea extends StatefulWidget {
  const WebArea({super.key});
  @override
  State<WebArea> createState() => _WebAreaState();
}

class _WebAreaState extends State<WebArea> {
  final _key = GlobalKey();
  Rect? _last;
  int _hwnd = 0;

  void _report(AppStore s) {
    if (!s.embedded) return;
    final hwnd = (s.snap['web'] as Map?)?['hwnd'] as int? ?? 0;
    if (hwnd != _hwnd) {
      _hwnd = hwnd;
      _host.invokeMethod('attach', {'hwnd': hwnd});
    }
    final box = _key.currentContext?.findRenderObject() as RenderBox?;
    if (box == null || !box.hasSize) return;
    final dpr = View.of(context).devicePixelRatio;
    final o = box.localToGlobal(Offset.zero);
    final r = Rect.fromLTWH(
        (o.dx * dpr).roundToDouble(),
        (o.dy * dpr).roundToDouble(),
        (box.size.width * dpr).roundToDouble(),
        (box.size.height * dpr).roundToDouble());
    if (r == _last) return;
    _last = r;
    _host.invokeMethod('setRect',
        {'x': r.left, 'y': r.top, 'w': r.width, 'h': r.height});
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final c = Theme.of(context).colorScheme;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _report(s);
    });
    final cover = s.cover['visible'] == true;
    return Container(
      key: _key,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: c.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: c.outlineVariant),
      ),
      child: Stack(fit: StackFit.expand, children: [
        if (!s.embedded) const _Preview(),
        AnimatedSwitcher(
          duration: Motion.drawer,
          switchInCurve: Motion.out,
          switchOutCurve: Motion.out,
          child: cover ? const _Cover(key: ValueKey('cover')) : const SizedBox.shrink(),
        ),
      ]),
    );
  }
}

class _Cover extends StatelessWidget {
  const _Cover({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final p = (s.cover['progress'] as num?)?.toDouble();
    return ColoredBox(
      color: c.surfaceContainerLowest,
      child: Center(
        child: SizedBox(
          width: 260,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const KeycapLogo(size: 56, blinking: true),
            const SizedBox(height: 20),
            Text('${s.cover['text'] ?? 'Sebentar...'}',
                textAlign: TextAlign.center, style: t.titleMedium),
            const SizedBox(height: 16),
            SmoothProgress(value: p, height: 4),
          ]),
        ),
      ),
    );
  }
}

// --------------------------------------------------------------- pratinjau
const _teks = [
  'the quick brown fox jumps over the lazy dog while the bot keeps a steady rhythm',
  'practice makes progress and every lesson brings a little more speed and calm',
  'jaded zombies acted quaintly but kept driving their oxen forward in the fog',
  'a typing tutor rewards accuracy first and speed second so keep both in mind',
];

/// Pengganti halaman edclub di preview (Linux/web). Terang seperti aslinya.
class _Preview extends StatelessWidget {
  const _Preview();

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    const bg = Color(0xFFF7F5F2), ink = Color(0xFF2B2F36), dim = Color(0xFFB9B4AC);
    final lvl = s.levelNum;
    final prog = s.busy ? ((s.level['progress'] as num?)?.toDouble() ?? 0) : 0.0;
    final teks = _teks[lvl % _teks.length];
    final n = (teks.length * prog).round();
    final gaya = t.headlineSmall!.copyWith(
        fontFamily: 'Inter', height: 1.7, letterSpacing: 0.3,
        fontVariations: const [FontVariation('wght', 450)]);
    return ColoredBox(
      color: bg,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Padding(
            padding: const EdgeInsets.all(40),
            child: Text.rich(TextSpan(style: gaya, children: [
              TextSpan(text: teks.substring(0, n), style: const TextStyle(color: ink)),
              WidgetSpan(
                alignment: PlaceholderAlignment.middle,
                child: Container(width: 2, height: 26, color: const Color(0xFF3B82F6)),
              ),
              TextSpan(text: teks.substring(n), style: const TextStyle(color: dim)),
            ])),
          ),
        ),
      ),
    );
  }
}
