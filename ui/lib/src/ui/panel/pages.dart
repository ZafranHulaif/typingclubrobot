// Halaman panel selain beranda: rentang, akun, lapor, pengaturan, update.
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../state/store.dart';
import '../../theme/theme.dart';
import '../widgets/common.dart';

// ================================================================ rentang
class RangePage extends StatefulWidget {
  const RangePage({super.key});
  @override
  State<RangePage> createState() => _RangePageState();
}

class _RangePageState extends State<RangePage> {
  late String _mode;
  final _a = TextEditingController();
  final _b = TextEditingController();
  String? _err;

  @override
  void initState() {
    super.initState();
    final s = StoreScope.read(context);
    final ch = s.rangeChoice;
    _mode = '${ch['mode'] ?? 'lanjut'}';
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;
    _a.text = '${ch['start'] ?? (pos + 1)}';
    final b = ch['end'];
    _b.text = (b == null || b == 0) ? '' : '$b';
  }

  @override
  void dispose() {
    _a.dispose();
    _b.dispose();
    super.dispose();
  }

  Map<String, dynamic>? _hasil(AppStore s) {
    if (_mode != 'custom') return {'mode': _mode};
    final total = (s.range['total'] as num?)?.toInt() ?? 0;
    final a = int.tryParse(_a.text.trim());
    final b = _b.text.trim().isEmpty ? 0 : int.tryParse(_b.text.trim());
    if (a == null || a < 1) {
      setState(() => _err = 'Level awal harus angka 1 atau lebih.');
      return null;
    }
    if (b == null || (b != 0 && b < a)) {
      setState(() => _err = 'Level akhir harus sama atau setelah level awal.');
      return null;
    }
    if (total > 0 && a > total) {
      setState(() => _err = 'Akun ini cuma punya $total level.');
      return null;
    }
    setState(() => _err = null);
    return {'mode': 'custom', 'start': a, 'end': b};
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final ask = s.rangeAsk;
    final pos = (s.range['position'] as num?)?.toInt() ?? 0;

    Widget opsi(String mode, IconData icon, String title, String sub) {
      final sel = _mode == mode;
      return Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: SurfaceCard(
          onTap: () => setState(() {
            _mode = mode;
            _err = null;
          }),
          color: sel ? c.primaryContainer.withValues(alpha: 0.5) : null,
          borderColor: sel ? c.primary.withValues(alpha: 0.6) : null,
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            Icon(icon, color: sel ? c.primary : c.onSurfaceVariant),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: t.titleSmall),
                const SizedBox(height: 2),
                Text(sub, style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
              ]),
            ),
            AnimatedScale(
              scale: sel ? 1 : 0,
              duration: Motion.short,
              curve: Motion.standard,
              child: Icon(Icons.check_circle_rounded, color: c.primary, size: 20),
            ),
          ]),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 8, 16, 24),
      children: [
        PanelHeader('Level yang dikerjakan',
            subtitle: ask != null
                ? 'Bot menunggu pilihanmu sebelum mulai.'
                : 'Dipakai setiap kamu menekan Mulai.',
            onBack: ask != null
                ? () => s.answer(ask, {'mode': 'cancel'})
                : null),
        Padding(
          padding: const EdgeInsets.only(left: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            opsi('lanjut', Icons.fast_forward_rounded, 'Lanjutkan',
                pos > 0 ? 'Mulai dari level ${pos + 1}, sampai habis.' : 'Dari posisi terakhir akun.'),
            opsi('custom', Icons.tune_rounded, 'Pilih level',
                'Tentukan level awal dan akhir sendiri.'),
            AnimatedSize(
              duration: Motion.medium,
              curve: Motion.standard,
              alignment: Alignment.topCenter,
              child: _mode != 'custom'
                  ? const SizedBox(width: double.infinity)
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(4, 4, 4, 14),
                      child: Row(children: [
                        Expanded(
                          child: TextField(
                            controller: _a,
                            keyboardType: TextInputType.number,
                            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                            decoration: const InputDecoration(labelText: 'Dari level'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: TextField(
                            controller: _b,
                            keyboardType: TextInputType.number,
                            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                            decoration: const InputDecoration(
                                labelText: 'Sampai level', hintText: 'Habis'),
                          ),
                        ),
                      ]),
                    ),
            ),
            opsi('halaman', Icons.ads_click_rounded, 'Pilih di halaman',
                'Klik sendiri level yang mau dikerjakan di edclub.'),
            AnimatedSize(
              duration: Motion.short,
              child: _err == null
                  ? const SizedBox(width: double.infinity)
                  : Padding(
                      padding: const EdgeInsets.fromLTRB(4, 2, 4, 10),
                      child: Text(_err!, style: t.bodySmall!.copyWith(color: c.error)),
                    ),
            ),
            const SizedBox(height: 8),
            Row(children: [
              if (ask == null)
                Expanded(
                  child: OutlinedButton(
                    onPressed: () {
                      final r = _hasil(s);
                      if (r == null) return;
                      s.setRange(r);
                      s.go(PanelPage.home);
                    },
                    child: const Text('Simpan'),
                  ),
                ),
              if (ask == null) const SizedBox(width: 10),
              Expanded(
                child: FilledButton.icon(
                  onPressed: () {
                    final r = _hasil(s);
                    if (r == null) return;
                    s.setRange(r);
                    s.go(PanelPage.home);
                    if (ask != null) {
                      s.answer(ask, r);
                    } else {
                      s.start();
                    }
                  },
                  icon: const Icon(Icons.play_arrow_rounded),
                  label: const Text('Mulai'),
                ),
              ),
            ]),
          ]),
        ),
      ],
    );
  }
}

// ================================================================ akun
class AccountsPage extends StatefulWidget {
  const AccountsPage({super.key});
  @override
  State<AccountsPage> createState() => _AccountsPageState();
}

class _AccountsPageState extends State<AccountsPage> {
  String? _hapus; // nama yang sedang dikonfirmasi hapus
  String? _pindah;

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final aktif = '${s.account['active'] ?? ''}';
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 8, 16, 24),
      children: [
        const PanelHeader('Akun',
            subtitle: 'Tiap akun punya login sendiri. Pindah kapan saja.'),
        if (s.busy)
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
            child: Text('Hentikan bot dulu untuk pindah akun.',
                style: t.bodySmall!.copyWith(color: c.tertiary)),
          ),
        for (final a in s.accounts) ...[
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 10),
            child: SurfaceCard(
              padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
              color: a['name'] == aktif ? c.surfaceContainerHigh : null,
              borderColor: a['name'] == aktif ? c.primary.withValues(alpha: 0.5) : null,
              onTap: a['name'] == aktif || s.busy || _pindah != null
                  ? null
                  : () async {
                      setState(() => _pindah = '${a['name']}');
                      await s.call('acct.switch', {'name': a['name']});
                      if (mounted) setState(() => _pindah = null);
                    },
              child: AnimatedSize(
                duration: Motion.medium,
                curve: Motion.standard,
                alignment: Alignment.topCenter,
                child: Column(children: [
                  Row(children: [
                    _Avatar('${a['name']}', active: a['name'] == aktif),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${a['name']}', style: t.titleSmall),
                        if ((a['email'] ?? '') != '')
                          Text('${a['email']}',
                              style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
                      ]),
                    ),
                    if (_pindah == a['name'])
                      const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox.square(
                            dimension: 16,
                            child: CircularProgressIndicator(strokeWidth: 2)),
                      )
                    else if (a['name'] == aktif)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        child: Text('Aktif', style: t.labelMedium!.copyWith(color: c.primary)),
                      )
                    else
                      IconButton(
                        tooltip: 'Hapus akun',
                        onPressed: s.busy ? null : () => setState(() => _hapus = '${a['name']}'),
                        icon: const Icon(Icons.delete_outline_rounded, size: 20),
                      ),
                  ]),
                  if (_hapus == a['name'])
                    Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Row(children: [
                        Expanded(
                          child: Text('Hapus login akun ini dari aplikasi?',
                              style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
                        ),
                        TextButton(
                            onPressed: () => setState(() => _hapus = null),
                            child: const Text('Batal')),
                        TextButton(
                          style: TextButton.styleFrom(foregroundColor: c.error),
                          onPressed: () {
                            s.call('acct.remove', {'name': a['name']});
                            setState(() => _hapus = null);
                          },
                          child: const Text('Hapus'),
                        ),
                      ]),
                    ),
                ]),
              ),
            ),
          ),
        ],
        Padding(
          padding: const EdgeInsets.only(left: 4, top: 6),
          child: Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: s.busy ? null : () => s.call('acct.add'),
                icon: const Icon(Icons.person_add_alt_rounded, size: 20),
                label: const Text('Tambah akun'),
              ),
            ),
            const SizedBox(width: 10),
            TextButton(
              onPressed: s.busy ? null : () => s.call('acct.logout'),
              child: const Text('Keluar'),
            ),
          ]),
        ),
      ],
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar(this.name, {this.active = false});
  final String name;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    return Container(
      width: 36,
      height: 36,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: active ? c.primary : c.secondaryContainer,
      ),
      child: Text(name.isEmpty ? '?' : name[0].toUpperCase(),
          style: t.titleSmall!.copyWith(
              color: active ? c.onPrimary : c.onSecondaryContainer)),
    );
  }
}

// ================================================================ lapor
class ReportPage extends StatefulWidget {
  const ReportPage({super.key});
  @override
  State<ReportPage> createState() => _ReportPageState();
}

class _ReportPageState extends State<ReportPage> {
  static const _kat = ['Bot macet', 'Salah ketik', 'Login', 'Tampilan', 'Lainnya'];
  String _pilih = 'Bot macet';
  final _teks = TextEditingController();
  bool _kirim = false;
  bool _terkirim = false;

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
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 8, 16, 24),
      children: [
        const PanelHeader('Laporkan masalah',
            subtitle: 'Laporan langsung sampai ke pembuat, lengkap dengan catatan bot.'),
        Padding(
          padding: const EdgeInsets.only(left: 4),
          child: AnimatedSwitcher(
            duration: Motion.medium,
            child: _terkirim
                ? Column(key: const ValueKey('ok'), children: [
                    const SizedBox(height: 24),
                    Icon(Icons.check_circle_rounded, size: 48, color: c.primary),
                    const SizedBox(height: 12),
                    Text('Terkirim, makasih!', style: t.titleLarge),
                    const SizedBox(height: 6),
                    Text('Masalahnya akan dicek secepatnya.',
                        style: t.bodyMedium!.copyWith(color: c.onSurfaceVariant)),
                    const SizedBox(height: 20),
                    OutlinedButton(
                        onPressed: () => s.go(PanelPage.home),
                        child: const Text('Kembali')),
                  ])
                : Column(
                    key: const ValueKey('form'),
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Eyebrow('Jenis masalah'),
                      Wrap(spacing: 8, runSpacing: 8, children: [
                        for (final k in _kat)
                          ChoiceChip(
                            label: Text(k),
                            selected: _pilih == k,
                            onSelected: (_) => setState(() => _pilih = k),
                          ),
                      ]),
                      const SizedBox(height: 20),
                      TextField(
                        controller: _teks,
                        minLines: 4,
                        maxLines: 8,
                        decoration: const InputDecoration(
                          labelText: 'Ceritakan yang terjadi',
                          hintText: 'Misal: bot berhenti di level 120 setelah layar putih',
                          alignLabelWithHint: true,
                        ),
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: _kirim
                              ? null
                              : () async {
                                  setState(() => _kirim = true);
                                  final r = await s.call('report.send',
                                      {'category': _pilih, 'text': _teks.text});
                                  if (!mounted) return;
                                  setState(() {
                                    _kirim = false;
                                    _terkirim = r != null;
                                  });
                                },
                          icon: _kirim
                              ? const SizedBox.square(
                                  dimension: 16,
                                  child: CircularProgressIndicator(strokeWidth: 2))
                              : const Icon(Icons.send_rounded, size: 18),
                          label: Text(_kirim ? 'Mengirim...' : 'Kirim laporan'),
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ],
    );
  }
}

// ================================================================ pengaturan
class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  int _ketuk = 0;
  DateTime _awal = DateTime(0);
  bool _dev = false;

  void _ketukVersi() {
    final now = DateTime.now();
    if (now.difference(_awal) > const Duration(seconds: 3)) {
      _awal = now;
      _ketuk = 0;
    }
    if (++_ketuk >= 5) setState(() => _dev = true);
  }

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;

    Widget baris(IconData icon, String title, String? sub,
        {Widget? trailing, VoidCallback? onTap}) {
      return ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        leading: Icon(icon, color: c.onSurfaceVariant),
        title: Text(title, style: t.titleSmall),
        subtitle: sub == null
            ? null
            : Text(sub, style: t.bodySmall!.copyWith(color: c.onSurfaceVariant)),
        trailing: trailing,
        onTap: onTap,
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 8, 16, 24),
      children: [
        const PanelHeader('Pengaturan'),
        const Padding(padding: EdgeInsets.only(left: 4), child: Eyebrow('Kontrol')),
        baris(Icons.keyboard_rounded, 'Tombol cepat',
            'F9 jeda, F10 ganti kecepatan, F11 stop',
            trailing: Switch(
              value: s.hotkeysOn,
              onChanged: (v) => s.call('hotkeys.set', {'on': v}),
            ),
            onTap: () => s.call('hotkeys.set', {'on': !s.hotkeysOn})),
        baris(Icons.healing_rounded, 'Pulihkan pelajaran',
            'Muat ulang level yang macet', onTap: () async {
          if (await s.call('bot.recover') != null) s.showToast('Memulihkan pelajaran...');
        }),
        baris(Icons.map_rounded, 'Petakan semua level',
            'Baca ulang daftar level akun ini', onTap: () => s.call('levels.build_map')),
        const SizedBox(height: 12),
        const Padding(padding: EdgeInsets.only(left: 4), child: Eyebrow('Bantuan')),
        baris(Icons.bug_report_outlined, 'Laporkan masalah', null,
            onTap: () => s.go(PanelPage.report)),
        baris(Icons.system_update_alt_rounded, 'Cek pembaruan', null, onTap: () async {
          final r = await s.call('update.check');
          if (r is Map && r['available'] == true) {
            s.go(PanelPage.update);
          } else if (r != null) {
            s.showToast('Kamu sudah pakai versi terbaru.');
          }
        }),
        baris(Icons.description_outlined, 'Buka catatan bot', 'bot.log',
            onTap: () => s.call('dev.open', {'what': 'log'})),
        baris(Icons.folder_open_rounded, 'Buka folder data', null,
            onTap: () => s.call('dev.open', {'what': 'data'})),
        AnimatedSize(
          duration: Motion.medium,
          curve: Motion.standard,
          child: !_dev
              ? const SizedBox(width: double.infinity)
              : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const SizedBox(height: 12),
                  const Padding(padding: EdgeInsets.only(left: 4), child: Eyebrow('Developer')),
                  baris(Icons.restart_alt_rounded, 'Reset pengaturan', null,
                      onTap: () => s.call('dev.reset_settings')),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 4, 0, 0),
                    child: Wrap(spacing: 8, runSpacing: 8, children: [
                      for (final w in ['login', 'locked', 'next', 'force_close', 'error', 'license', 'boot'])
                        ActionChip(
                          label: Text(w),
                          onPressed: () => s.call('dev.simulate', {'what': w}),
                        ),
                    ]),
                  ),
                ]),
        ),
        const SizedBox(height: 20),
        Center(
          child: GestureDetector(
            onTap: _ketukVersi,
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Text('TypingBot ${s.app['version'] ?? ''}',
                  style: t.labelSmall!.copyWith(color: c.outline)),
            ),
          ),
        ),
      ],
    );
  }
}

// ================================================================ update
class UpdatePage extends StatelessWidget {
  const UpdatePage({super.key});

  @override
  Widget build(BuildContext context) {
    final s = StoreScope.of(context);
    final t = Theme.of(context).textTheme;
    final c = Theme.of(context).colorScheme;
    final u = s.update;
    final phase = '${u['phase'] ?? 'idle'}';
    final prog = (u['progress'] as num?)?.toDouble() ?? 0;
    final mb = ((u['size'] as num?) ?? 0) / 1e6;
    final notes = '${u['notes'] ?? ''}'
        .split('\n')
        .where((l) => l.trim().isNotEmpty && !l.startsWith('#'))
        .map((l) => l.replaceAll('**', '').replaceFirst(RegExp(r'^- '), ''))
        .toList();
    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 8, 16, 24),
      children: [
        PanelHeader('Versi ${u['version'] ?? ''} siap',
            subtitle: 'Kamu pakai ${s.app['version'] ?? ''}. Ukuran unduhan ${mb.toStringAsFixed(0)} MB.'),
        Padding(
          padding: const EdgeInsets.only(left: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (notes.isNotEmpty)
              SurfaceCard(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final n in notes)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Padding(
                          padding: const EdgeInsets.only(top: 6, right: 10),
                          child: Icon(Icons.circle, size: 6, color: c.primary),
                        ),
                        Expanded(child: Text(n, style: t.bodyMedium)),
                      ]),
                    ),
                ]),
              ),
            const SizedBox(height: 20),
            AnimatedSwitcher(
              duration: Motion.medium,
              child: switch (phase) {
                'downloading' => Column(key: const ValueKey('dl'), children: [
                    SmoothProgress(value: prog, height: 8),
                    const SizedBox(height: 10),
                    Row(children: [
                      Text('Mengunduh ${(prog * 100).round()}%', style: t.bodySmall),
                      const Spacer(),
                      TextButton(
                          onPressed: () => s.call('update.cancel'),
                          child: const Text('Batal')),
                    ]),
                  ]),
                'ready' => FilledButton.icon(
                    key: const ValueKey('ready'),
                    onPressed: () => s.call('update.install'),
                    icon: const Icon(Icons.restart_alt_rounded),
                    label: const Text('Pasang dan mulai ulang'),
                  ),
                _ => FilledButton.icon(
                    key: const ValueKey('idle'),
                    onPressed: () => s.call('update.download'),
                    icon: const Icon(Icons.download_rounded),
                    label: const Text('Unduh pembaruan'),
                  ),
              },
            ),
          ]),
        ),
      ],
    );
  }
}
