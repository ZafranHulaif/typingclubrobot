// Aktivasi lisensi: tampil di beranda selama lisensi belum ok.
import 'package:material_ui/material_ui.dart';

import '../../state/store.dart';
import '../widgets/common.dart';

class LicenseCard extends StatefulWidget {
  const LicenseCard({super.key});
  @override
  State<LicenseCard> createState() => _LicenseCardState();
}

class _LicenseCardState extends State<LicenseCard> {
  final _nick = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _nick.dispose();
    super.dispose();
  }

  Future<void> _kirim(AppStore s) async {
    setState(() => _sending = true);
    await s.call('license.request', {'nickname': _nick.text});
    if (mounted) setState(() => _sending = false);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final st = s.license['state'];
    final pending = st == 'pending';
    final revoked = st == 'revoked';
    if (_nick.text.isEmpty && (s.license['nickname'] ?? '') != '') {
      _nick.text = '${s.license['nickname']}';
    }
    return SurfaceCard(
      color: c.secondaryContainer.withValues(alpha: 0.45),
      borderColor: c.secondary.withValues(alpha: 0.3),
      padding: const EdgeInsets.all(18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.key_rounded, color: c.secondary, size: 20),
          const SizedBox(width: 10),
          Text(
              pending
                  ? 'Menunggu persetujuan'
                  : revoked
                      ? 'Akses dicabut'
                      : 'Aktifkan TypingBot',
              style: t.titleMedium),
        ]),
        const SizedBox(height: 8),
        Text(
          pending
              ? 'Permintaanmu sudah terkirim. Begitu pemilik menyetujui, bot langsung bisa dipakai.'
              : revoked
                  ? 'Akses perangkat ini dicabut. Hubungi pemilik kalau menurutmu ini keliru.'
                  : 'Tulis nama panggilanmu, lalu pemilik akan menyetujui perangkat ini.',
          style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant),
        ),
        const SizedBox(height: 14),
        if (pending)
          const SmoothProgress(value: null, height: 4)
        else if (!revoked) ...[
          TextField(
            controller: _nick,
            enabled: !_sending,
            textInputAction: TextInputAction.send,
            onSubmitted: (_) => _kirim(s),
            decoration: const InputDecoration(labelText: 'Nama panggilan'),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton(
              onPressed: _sending ? null : () => _kirim(s),
              child: Text(_sending ? 'Mengirim...' : 'Kirim permintaan'),
            ),
          ),
        ],
      ]),
    );
  }
}
