// Uji mandiri macOS di CI (TB_MACTEST=<folder>, TB_MACTEST_URL=<halaman>):
// webview WKWebView + peniru CDP + Page asli, terhadap halaman uji lokal
// (ui/tool/mactest) yang punya iframe LINTAS ORIGIN spt lesson edclub.
// Hasil: <folder>/result.json + snapshot.png, lalu file 'selesai'.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../engine/page.dart';
import '../web/web_host.dart';
import 'native_backend.dart' show initScripts;
import 'view_bridge.dart';

String? macTestDir() {
  final d = Platform.environment['TB_MACTEST'];
  return d == null || d.isEmpty ? null : d;
}

/// Cek login Google di WKWebView (TB_GOOGLECHECK (folder), email dari file
/// TB_GOOGLE_EMAIL_FILE): buka edclub signin, klik 'Sign in with Google',
/// isi email (TANPA sandi), catat apakah Google menolak browser ini.
/// Tanpa potret (email akan terlihat); teks halaman disensor.
Future<void> runGoogleCheck(String dir) async {
  Directory(dir).createSync(recursive: true);
  final out = <String, dynamic>{};
  Future<void> tunggu(double s) =>
      Future<void>.delayed(Duration(milliseconds: (s * 1000).round()));
  var email = '';
  try {
    email = File(Platform.environment['TB_GOOGLE_EMAIL_FILE'] ?? '').readAsStringSync().trim();
  } catch (_) {}
  String sensor(Object? x) {
    var t = '$x';
    if (email.isNotEmpty) t = t.replaceAll(email, '<email>');
    return t.length > 600 ? t.substring(0, 600) : t;
  }

  try {
    await webHost.setRect(0, 0, 2400, 1400);
    final view = await webHost.create(
        folder: '${dir}_profil',
        url: 'https://www.edclub.com/signin',
        visible: true,
        // skrip app asli (popup Google jadi navigasi halaman, relay OAuth)
        scripts: initScripts);
    final page = Page(WebViewBridge(view));
    await page.attach();
    await tunggu(8);
    final r = await page.evaluate('() => { const b = [...document.querySelectorAll("a, button")]'
        '.find((e) => /google/i.test(e.innerText || "") && e.offsetWidth);'
        ' if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();'
        ' return [r.left + r.width / 2, r.top + r.height / 2]; }');
    out['tombol_google'] = r != null;
    if (r is List) {
      await tunggu(0.5);
      await page.mouse.click(r[0] as num, r[1] as num);
    }
    await tunggu(8);
    out['url_sesudah_klik'] = sensor((await view.info()).url);
    if (email.isNotEmpty) {
      await page.evaluate('() => { const i = document.querySelector("input[type=email]");'
          ' if (i) i.focus(); return !!i; }');
      await view.focus();
      await page.keyboard.type(email);
      await page.keyboard.press('Enter');
      await tunggu(9);
    }
    out['url_akhir'] = sensor((await view.info()).url);
    out['teks_akhir'] = sensor(await page.evaluate(
        '() => (document.body && document.body.innerText || "").replace(/\\s+/g, " ")'));
    out['ada_kolom_sandi'] = await page.evaluate(
        '() => !!document.querySelector("input[type=password]")');
  } catch (e) {
    out['error'] = sensor(e);
  }
  File('$dir/google.json').writeAsStringSync(const JsonEncoder.withIndent('  ').convert(out));
  File('$dir/selesai').writeAsStringSync('ok');
}

Future<void> runMacSelfTest(String dir) async {
  Directory(dir).createSync(recursive: true);
  final out = <String, dynamic>{};
  final log = StringBuffer();
  void catat(String s) {
    log.writeln('${DateTime.now().toIso8601String()} $s');
  }

  Future<void> tunggu(double s) =>
      Future<void>.delayed(Duration(milliseconds: (s * 1000).round()));

  try {
    final url = Platform.environment['TB_MACTEST_URL'] ?? 'http://127.0.0.1:8701/main.html';
    await webHost.setRect(0, 0, 2400, 1400);
    out['version'] = await webHost.version();
    final view = await webHost.create(
        folder: '${dir}_profil', url: url, visible: true);
    final page = Page(WebViewBridge(view));
    await page.attach();

    // tunggu iframe lintas origin terdaftar
    Frame? iframe;
    for (var i = 0; i < 100 && iframe == null; i++) {
      await tunggu(0.2);
      for (final f in page.frames) {
        if (!f.isMain && f.url.contains('frame.html')) iframe = f;
      }
    }
    out['url'] = page.url;
    out['frames'] = [for (final f in page.frames) f.url];
    out['iframe_found'] = iframe != null;
    catat('frames: ${out['frames']}');

    out['eval_main'] = await page.evaluate('() => document.title');
    if (iframe != null) {
      out['eval_iframe'] = await iframe.evaluate('() => location.origin');
    }

    // 1) ketik di input iframe lintas origin (jalur lesson edclub)
    if (iframe != null) {
      await iframe.evaluate('() => document.getElementById("ketik").focus()');
      await view.focus();
      await tunggu(0.3);
      for (final ch in 'Hello World'.split('')) {
        await page.keyboard.type(ch);
        await tunggu(0.03);
      }
      await page.keyboard.press('Backspace');
      await page.keyboard.press('Enter');
      await tunggu(0.5);
      out['iframe_typing'] = await iframe.evaluate('() => window.hasil');
      // ketik cepat lalu LANGSUNG baca: teks harus sudah lengkap (antrean
      // tombol WebKit tidak boleh disalip evaluasi)
      await iframe.evaluate('() => { const i = document.getElementById("ketik"); i.value = ""; i.focus(); }');
      await tunggu(0.2);
      const cepat = 'the quick brown fox jumps over the lazy dog';
      await page.keyboard.type(cepat);
      out['fast_text'] = await iframe.evaluate('() => document.getElementById("ketik").value');
    }

    // 2) klik mouse asli pada tombol halaman utama
    final r = await page.evaluate('() => { const b = document.getElementById("btn")'
        '.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; }');
    if (r is List) {
      await page.mouse.click(r[0] as num, r[1] as num);
      await tunggu(0.3);
    }
    // 3) klik di dalam iframe (posisi lewat frameOffset)
    if (iframe != null) {
      final off = await page.frameOffset(iframe);
      out['iframe_offset'] = [off.x, off.y];
      final b = await iframe.evaluate('() => { const b = document.getElementById("b2")'
          '.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; }');
      if (b is List) {
        await page.mouse.click(off.x + (b[0] as num), off.y + (b[1] as num));
        await tunggu(0.3);
      }
      out['iframe_after_click'] = await iframe.evaluate('() => window.hasil.clicks');
    }
    out['main_after_click'] = await page.evaluate('() => window.hasil');

    // 4) kuki (jalur sesi rt)
    await view.cdp('Network.setCookie', {
      'name': 'tbtes',
      'value': 'ok123',
      'domain': '127.0.0.1',
      'path': '/',
      'expires': DateTime.now().millisecondsSinceEpoch / 1000 + 3600,
    });
    final ck = await view.cdp('Network.getCookies', {
      'urls': ['http://127.0.0.1:8701/']
    });
    out['cookie'] = [
      for (final c in (ck['cookies'] as List? ?? const []))
        if (c is Map && c['name'] == 'tbtes') c['value']
    ];

    // 4b) jar kuki terpisah per akun (folder lain = WKWebsiteDataStore lain)
    final lain = await webHost.create(folder: '${dir}_profil_lain', url: 'about:blank');
    final ck2 = await lain.cdp('Network.getCookies', {
      'urls': ['http://127.0.0.1:8701/']
    });
    out['cookie_akun_lain'] = [
      for (final c in (ck2['cookies'] as List? ?? const []))
        if (c is Map && c['name'] == 'tbtes') c['value']
    ];
    await lain.dispose();

    // 5) reload: frame & konteks diumumkan ulang
    await page.reload(timeout: 20);
    await tunggu(1.5);
    out['after_reload_frames'] = [for (final f in page.frames) f.url];

    final shot = await view.cdp('Page.captureScreenshot');
    final data = '${shot['data'] ?? ''}';
    if (data.isNotEmpty) {
      File('$dir/snapshot.png').writeAsBytesSync(base64Decode(data));
    }
  } catch (e, st) {
    out['error'] = '$e';
    catat('$st');
  }
  File('$dir/result.json').writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert(out));
  File('$dir/log.txt').writeAsStringSync('$log');
  File('$dir/selesai').writeAsStringSync('ok');
}
