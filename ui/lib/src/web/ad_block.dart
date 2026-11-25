// Blokir iklan di halaman edclub (v4 saja).
//
// Halaman lesson memuat lelang iklan penuh (Playwire/intergient + prebid:
// PubMatic, Rubicon, Criteo, Index, OpenX, Amazon) dan video iklan di
// pojok. Akibatnya: CPU/GPU WebView berat di laptop lemah, iframe iklan
// menumpuk (56 -> 254 frame dalam 5 menit), dan video iklan dikira video
// lesson sehingga bot sibuk 'melompati' iklan dan game tak tersentuh
// (uji live mac 4.0.8, level 94).
//
// Yang TIDAK diblokir: login Google/Clever/Microsoft, Cloudflare, Didomi
// (banner persetujuan, ditangani mesin), video lesson edclub
// (corevideo.edclub.app), analytics ringan.

/// Domain iklan (termasuk semua subdomainnya).
const adHosts = <String>[
  // pengelola iklan edclub
  'intergient.com', 'playwire.com',
  // Google iklan (bukan login / fonts / gstatic)
  'doubleclick.net', 'googlesyndication.com', 'googleadservices.com',
  'adservice.google.com', 'imasdk.googleapis.com',
  // bursa & lelang (prebid)
  'amazon-adsystem.com', 'pubmatic.com', 'rubiconproject.com',
  'criteo.com', 'criteo.net', 'casalemedia.com', 'indexww.com', 'openx.net',
  'adnxs.com', '3lift.com', 'sharethrough.com', 'smartadserver.com',
  'adsrvr.org', 'teads.tv', 'yieldmo.com', 'media.net', 'lijit.com',
  'sonobi.com', '33across.com', 'gumgum.com', 'bidswitch.net',
  'contextweb.com', 'districtm.io', 'onetag-sys.com', 'seedtag.com',
  'minutemedia-prebid.com', 'kargo.com', 'improvedigital.com',
  // sinkron id & verifikasi iklan
  'id5-sync.com', 'liadm.com', 'rlcdn.com', 'adsafeprotected.com',
  'doubleverify.com', 'moatads.com', 'crwdcntrl.net', 'tapad.com',
  // iklan konten
  'taboola.com', 'outbrain.com',
];

/// Pola CDP `Network.setBlockedURLs` (Windows / WebView2).
List<String> adBlockPatterns([List<String> hosts = adHosts]) => [
      for (final h in hosts) ...['*://$h/*', '*://*.$h/*'],
    ];
