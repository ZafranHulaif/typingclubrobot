// Cloudflare Worker TypingBot - implementasi API.md (produksi).
//
// DESAIN TANPA KARTU KREDIT: tidak memakai R2. Binary exe disimpan
// sebagai potongan 20 MiB di KV (batas nilai KV 25 MiB; free tier 1 GB).
// Unggah: body satu permintaan (<100 MB, batas free plan) di-tee ke
// DigestStream (hash asli server) + loop potongan -> KV put per 20 MiB.
// Unduh: ReadableStream generator menarik potongan satu per satu
// (memori tetap kecil), Content-Length dari metadata.
//
// Setup (lihat server/DEPLOY.md): KV namespace MACHINES + META saja,
// secrets SIGN_PRIV (PKCS8 base64) + ADMIN_KEY, vars SIGN_PUB (hex)
// + BASE (URL publik).

const TOKEN_TTL = 30 * 86400;
const CHUNK = 20 * 1024 * 1024;

const hexToBytes = (h) => new Uint8Array(h.match(/.{2}/g).map((c) => parseInt(c, 16)));
const b64ToBytes = (b) => Uint8Array.from(atob(b), (c) => c.charCodeAt(0));
const bytesToHex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");

let env = null;

let signKeyCache = null;
async function signKey() {
  if (!signKeyCache) {
    signKeyCache = await crypto.subtle.importKey(
      "pkcs8", b64ToBytes(env.SIGN_PRIV), { name: "Ed25519" }, false, ["sign"]);
  }
  return signKeyCache;
}
let verKeyCache = null;
async function verKey() {
  if (!verKeyCache) {
    verKeyCache = await crypto.subtle.importKey(
      "raw", hexToBytes(env.SIGN_PUB), { name: "Ed25519" }, false, ["verify"]);
  }
  return verKeyCache;
}

async function makeToken(mc) {
  const exp = Math.floor(Date.now() / 1000) + TOKEN_TTL;
  const msg = new TextEncoder().encode(`v1|${mc}|${exp}`);
  const sig = await crypto.subtle.sign("Ed25519", await signKey(), msg);
  return { mc, exp, sig: bytesToHex(new Uint8Array(sig)) };
}

async function tokenOk(tok) {
  try {
    if (!tok || tok.exp < Math.floor(Date.now() / 1000)) return false;
    const msg = new TextEncoder().encode(`v1|${tok.mc}|${tok.exp}`);
    return await crypto.subtle.verify(
      "Ed25519", await verKey(), hexToBytes(tok.sig), msg);
  } catch (e) {
    return false;
  }
}

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8",
               "cache-control": "no-store" },
  });

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

function adminPage(machines, key) {
  const semua = Object.values(machines).sort((a, b) =>
    (b.last_seen || 0) - (a.last_seen || 0));
  const akunNama = (id) => {
    const a = machines[id];
    return a ? (a.account_name || a.nickname || id.slice(1)) : String(id).slice(1);
  };
  const grup = (m) => m.status === "pending" ? "tunggu"
    : (m.status === "denied" || m.status === "revoked") ? "cabut"
    : String(m.mc).startsWith("a") ? "akun" : "mesin";
  const kartu = (m) => {
    const akun = String(m.mc).startsWith("a");
    const st = m.status;
    let btn;
    if (st === "pending") btn = [["Setujui", "approve", "utama"], ["Tolak", "deny", "bahaya"]];
    else if (st === "approved") btn = [["Cabut", "revoke", "bahaya"], ["Hapus", "delete", "hantu"]];
    else btn = [["Setujui lagi", "approve", "utama"], ["Hapus", "delete", "hantu"]];
    const tombol = btn.map(([txt, act, gaya]) =>
      `<form method="post" action="/admin/action"${act === "delete" ? ' onsubmit="return confirm(\'Hapus ' + esc(m.nickname || m.mc).replace(/'/g, "") + '?\')"' : ""}>
<input type="hidden" name="key" value="${esc(key)}"><input type="hidden" name="mc" value="${esc(m.mc)}">
<input type="hidden" name="act" value="${act}"><button class="b ${gaya}">${txt}</button></form>`).join("");
    const nama = m.nickname || "?";
    const sub = akun
      ? `<span class="tag akun">edclub</span> ${esc(m.account_name || "-")} <span class="id">#${esc(String(m.mc).slice(1))}</span>`
      : `<span class="tag mesin">PC lama</span> <span class="id">${esc(m.mc)}</span>`;
    const catatan = [];
    if (akun && m.via) catatan.push("otomatis dari lisensi PC lama");
    if (!akun && m.claimed) catatan.push("sudah dipakai akun " + esc(akunNama(m.claimed)));
    if (!akun && st === "approved" && !m.claimed) catatan.push("jatah 1 akun belum dipakai");
    const cari = `${nama} ${m.account_name || ""} ${m.mc}`.toLowerCase();
    return `<div class="kartu" data-g="${grup(m)}" data-cari="${esc(cari)}">
<div class="ava ${akun ? "a" : "m"}">${esc(nama.trim().charAt(0).toUpperCase() || "?")}</div>
<div class="isi"><div class="nama">${esc(nama)}</div><div class="sub">${sub}</div>
<div class="meta">${m.app_version ? "v" + esc(m.app_version) + " &middot; " : ""}<span data-ts="${m.last_seen || 0}"></span>${catatan.length ? " &middot; " + catatan.join(" &middot; ") : ""}</div></div>
<div class="aksi">${tombol}</div></div>`;
  };
  const n = { tunggu: 0, akun: 0, mesin: 0, cabut: 0 };
  for (const m of semua) n[grup(m)]++;
  return `<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>TypingBot Admin</title><style>
:root{--bg:#0e0f12;--kartu:#17191e;--garis:#262931;--teks:#eceef2;--redup:#8d93a0;
--lime:#c6f135;--lime-teks:#14170a;--merah:#ff6b6b;--kuning:#f5c451;--biru:#7cb7ff}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--teks);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0}
.wrap{max-width:860px;margin:0 auto;padding:20px 16px 60px}
header{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.logo{width:30px;height:30px;border-radius:9px;background:var(--lime);color:var(--lime-teks);
display:grid;place-items:center;font-weight:800}
h1{font-size:18px;margin:0;flex:1}
.redup{color:var(--redup);font-size:12px}
.tabs{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;margin-bottom:10px}
.tab{flex:none;border:1px solid var(--garis);background:transparent;color:var(--redup);
border-radius:999px;padding:6px 12px;font:600 13px system-ui;cursor:pointer}
.tab b{color:var(--teks);margin-left:4px}
.tab.on{background:var(--teks);color:var(--bg);border-color:var(--teks)}.tab.on b{color:var(--bg)}
.tab.tunggu b{color:var(--kuning)}
.tab.tunggu.on{background:var(--kuning);border-color:var(--kuning);color:#1d1600}.tab.tunggu.on b{color:#1d1600}
input[type=search]{width:100%;background:var(--kartu);border:1px solid var(--garis);color:var(--teks);
border-radius:10px;padding:9px 12px;font:14px system-ui;margin-bottom:12px;outline:none}
input[type=search]:focus{border-color:var(--redup)}
.kartu{display:flex;gap:12px;align-items:center;background:var(--kartu);border:1px solid var(--garis);
border-radius:14px;padding:12px 14px;margin-bottom:8px}
.ava{flex:none;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-weight:700}
.ava.a{background:#c6f13522;color:var(--lime)}.ava.m{background:#7cb7ff1f;color:var(--biru)}
.isi{flex:1;min-width:0}
.nama{font-weight:650;font-size:15px}
.sub{font-size:13px;color:var(--teks);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.id{color:var(--redup);font-size:12px}
.tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;border-radius:5px;padding:1px 6px;margin-right:2px}
.tag.akun{background:#c6f13522;color:var(--lime)}.tag.mesin{background:#7cb7ff1f;color:var(--biru)}
.meta{color:var(--redup);font-size:12px;margin-top:2px}
.aksi{display:flex;gap:6px;flex:none}
.aksi form{margin:0}
.b{border:0;border-radius:8px;padding:7px 12px;font:600 13px system-ui;cursor:pointer}
.b.utama{background:var(--lime);color:var(--lime-teks)}
.b.bahaya{background:#ff6b6b1f;color:var(--merah)}
.b.hantu{background:transparent;color:var(--redup);border:1px solid var(--garis)}
.b:hover{filter:brightness(1.12)}
.kosong{color:var(--redup);text-align:center;padding:40px 0}
[hidden]{display:none !important}
@media (max-width:560px){.kartu{flex-wrap:wrap}.aksi{width:100%;justify-content:flex-end}}
</style></head><body><div class="wrap">
<header><div class="logo">T</div><h1>TypingBot Admin</h1><span class="redup" id="jam">diperbarui otomatis</span></header>
<div id="isi" data-n='${JSON.stringify(n)}'>
<div class="tabs">
<button class="tab tunggu" data-t="tunggu">Menunggu<b>${n.tunggu}</b></button>
<button class="tab" data-t="akun">Akun edclub<b>${n.akun}</b></button>
<button class="tab" data-t="mesin">PC lama (3.5)<b>${n.mesin}</b></button>
<button class="tab" data-t="cabut">Ditolak / dicabut<b>${n.cabut}</b></button>
</div>
<input type="search" id="q" placeholder="Cari nama, nama edclub, atau kode">
<div id="daftar">${semua.map(kartu).join("")}</div>
<div class="kosong" id="kosong" hidden>Tidak ada di sini.</div>
</div></div>
<script>
let tab = null;
try { tab = localStorage.getItem('tb_tab'); } catch (e) {}
function relatif(ts) {
  if (!ts) return 'belum pernah';
  const d = Math.max(0, Date.now() / 1000 - ts);
  if (d < 60) return 'baru saja';
  if (d < 3600) return Math.floor(d / 60) + ' menit lalu';
  if (d < 86400) return Math.floor(d / 3600) + ' jam lalu';
  return Math.floor(d / 86400) + ' hari lalu';
}
// tab awal (sekali saat halaman dibuka): ada yang menunggu = Menunggu,
// selain itu tab terakhir yang dipilih, atau tab pertama yang berisi
{
  const n = JSON.parse(document.getElementById('isi').dataset.n);
  if (n.tunggu) tab = 'tunggu';
  else if (!tab || !n[tab]) tab = n.akun ? 'akun' : n.mesin ? 'mesin' : 'tunggu';
}
function terap() {
  const q = (document.getElementById('q').value || '').toLowerCase().trim();
  let ada = 0;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.t === tab));
  document.querySelectorAll('.kartu').forEach(k => {
    const ok = (q ? k.dataset.cari.includes(q) : k.dataset.g === tab);
    k.hidden = !ok; if (ok) ada++;
  });
  document.getElementById('kosong').hidden = ada > 0;
  document.querySelectorAll('[data-ts]').forEach(e => e.textContent = 'terakhir ' + relatif(+e.dataset.ts));
}
function pasang() {
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
    tab = t.dataset.t; document.getElementById('q').value = '';
    try { localStorage.setItem('tb_tab', tab); } catch (e) {}
    terap();
  });
  document.getElementById('q').oninput = terap;
  terap();
}
pasang();
setInterval(async () => { try {
  if (document.activeElement && document.activeElement.id === 'q') return;
  const r = await fetch(location.href);
  const d = new DOMParser().parseFromString(await r.text(), 'text/html');
  const baru = d.getElementById('isi');
  if (baru) { document.getElementById('isi').replaceWith(baru); pasang(); }
} catch (e) {} }, 8000);
</script></body></html>`;
}

// Status tiap mesin kini SATU kunci KV per mesin (`machine:<mc>`).
// Dulu satu blob JSON utk semua mesin: tiap poll/aksi admin membaca-
// tulis ulang seluruh blob, dan KV itu eventually-consistent (baca
// basi ~60 dtk) -> tulisan balik dari data basi bisa MENGEMBALIKAN
// status lama (keluhan live: approve di HP, aplikasi tetap bilang
// pending/revoked). Kunci terpisah membatasi effect tulisan basi
// hanya ke mesin itu sendiri.
const machineKey = (mc) => `machine:${mc}`;

async function getMachine(mc) {
  const v = await env.MACHINES.get(machineKey(mc));
  if (v) {
    try { return JSON.parse(v); } catch (e) { return null; }
  }
  // migrasi sekali jalan dari blob lama (deploy sebelum 2.9.25)
  const legacy = await env.MACHINES.get("machines");
  if (!legacy) return null;
  let m = null;
  try { m = JSON.parse(legacy)[mc] || null; } catch (e) { return null; }
  if (m) await env.MACHINES.put(machineKey(mc), JSON.stringify(m));
  return m;
}

async function putMachine(m) {
  await env.MACHINES.put(machineKey(m.mc), JSON.stringify(m));
}

// kunci per-mesin dulu (data terbaru), blob lama hanya mengisi yang
// belum termigrasi, lalu dihapus begitu semuanya pindah
async function allMachines() {
  const out = {};
  const daftar = await env.MACHINES.list({ prefix: "machine:" });
  for (const k of daftar.keys) {
    const v = await env.MACHINES.get(k.name);
    if (!v) continue;
    try {
      const m = JSON.parse(v);
      if (m && (m.mc || k.name.length > 8)) out[m.mc || k.name.slice(8)] = m;
    } catch (e) {}
  }
  const legacy = await env.MACHINES.get("machines");
  if (legacy) {
    let habis = true;
    try {
      for (const [mc, m] of Object.entries(JSON.parse(legacy))) {
        if (!out[mc]) {
          out[mc] = m;
          await env.MACHINES.put(machineKey(mc), JSON.stringify(m));
        }
      }
    } catch (e) { habis = false; }
    if (habis) await env.MACHINES.delete("machines");
  }
  return out;
}

function chunkKey(ver, i) {
  return `exe:${ver}:${i}`;
}

async function handle(request, ctx) {
  const u = new URL(request.url);
  const q = u.searchParams;

  if (u.pathname === "/api/latest") {
    const rel = await env.META.get("release");
    return rel ? json(JSON.parse(rel)) : json({ error: "no_release_yet" }, 404);
  }

  // Laporan bug dari app (publik, dibatasi): POST /api/lapor
  // {versi, akun, isi} -> KV "laporan:<ts>" + indeks 30 terakhir.
  // Baca utk pemilik: GET /api/lapor-list (X-Admin-Key).
  if (u.pathname === "/api/lapor" && request.method === "POST") {
    let body;
    try { body = await request.json(); } catch (e) {
      return json({ error: "bad_json" }, 400);
    }
    // batas 20000 karakter: simpan kepala (versi/kategori/cerita) + EKOR
    // log. Dulu .slice(0, 20000) membuang baris log TERBARU (yang justru
    // dicari) begitu log 400 baris kepanjangan.
    let isi = String(body.isi || "");
    if (isi.length > 20000) {
      const li = isi.indexOf("=== LOG");
      const kepala = li >= 0 ? isi.slice(0, Math.min(li, 6000)) : "";
      const judul = "=== LOG (dipotong, bagian akhir) ===\n...\n";
      isi = kepala + judul + isi.slice(-(20000 - kepala.length - judul.length));
    }
    if (isi.length < 20) return json({ error: "kosong" }, 400);
    const ip = request.headers.get("CF-Connecting-IP") || "?";
    const rkey = `laporan-rl:${ip}`;
    let rl = { n: 0, t0: 0 };
    try { rl = JSON.parse(await env.MACHINES.get(rkey) || '{"n":0,"t0":0}'); }
    catch (e) {}
    const now = Math.floor(Date.now() / 1000);
    if (now - rl.t0 < 600 && rl.n >= 3)
      return json({ error: "rate_limited" }, 429);
    rl = (now - rl.t0 >= 600) ? { n: 1, t0: now }
                              : { n: rl.n + 1, t0: rl.t0 };
    await env.MACHINES.put(rkey, JSON.stringify(rl));
    const ts = Date.now();
    await env.MACHINES.put(`laporan:${ts}`, JSON.stringify({
      ts, ip,
      versi: String(body.versi || "?").slice(0, 40),
      akun: String(body.akun || "?").slice(0, 60),
      isi }));
    let idx = [];
    try { idx = JSON.parse(await env.MACHINES.get("laporan:idx") || "[]"); }
    catch (e) {}
    idx.unshift({ ts, versi: String(body.versi || "?").slice(0, 20),
                  akun: String(body.akun || "?").slice(0, 40) });
    await env.MACHINES.put("laporan:idx", JSON.stringify(idx.slice(0, 30)));
    // dorong realtime ke webhook pemilik (T3 thread) - gagal = diam:
    // simpan ke KV tetap sukses, notifikasi bukan bagian kontrak API
    if (env.LAPOR_HOOK) {
      try {
        console.log("[LAPOR-HOOK] menembak relay");
        ctx.waitUntil(fetch(env.LAPOR_HOOK, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-lapor-token": env.LAPOR_HOOK_TOKEN || "",
          },
          body: JSON.stringify({
            ts, versi: String(body.versi || "?").slice(0, 40),
            akun: String(body.akun || "?").slice(0, 60),
            // isi laporan ikut dikirim (thread pemilik langsung bisa
            // membaca tanpa admin key): kategori, cerita, ekor log
            ...laporBagian(isi),
          }),
        }).then((r) => console.log("[LAPOR-HOOK] relay balas",
              r.status))
          .catch((e) => console.log("[LAPOR-HOOK] relay gagal",
              String(e).slice(0, 120))));
      } catch (e) {
        console.log("[LAPOR-HOOK] exc", String(e).slice(0, 120));
      }
    } else {
      console.log("[LAPOR-HOOK] LAPOR_HOOK kosong");
    }
    return json({ ok: true, ts });
  }
  if (u.pathname === "/api/lapor-list") {
    if (request.headers.get("X-Admin-Key") !== env.ADMIN_KEY)
      return json({ error: "bad_admin_key" }, 403);
    let idx = [];
    try { idx = JSON.parse(await env.MACHINES.get("laporan:idx") || "[]"); }
    catch (e) {}
    const detail = [];
    for (const it of idx.slice(0, 10)) {
      const v = await env.MACHINES.get(`laporan:${it.ts}`);
      if (v) { try { detail.push(JSON.parse(v)); } catch (e) {} }
    }
    return json({ daftar: idx, detail });
  }

  if (u.pathname === "/api/license/request" && request.method === "POST") {
    const d = await request.json();
    const mc = String(d.mc || "").slice(0, 32);
    if (!mc) return json({ error: "mc_required" }, 400);
    const m = (await getMachine(mc)) ||
      { mc, status: "pending", first_seen: Math.floor(Date.now() / 1000) };
    if (m.status === "denied" || m.status === "revoked") {
      // mesin dicabut/ditolak minta lagi -> wajib disetujui ulang
      m.status = "pending";
    }
    m.nickname = String(d.nickname || "?").slice(0, 40) || m.nickname || "?";
    if (d.account_name) m.account_name = String(d.account_name).slice(0, 60);
    m.app_version = String(d.app_version || "").slice(0, 16);
    m.last_seen = Math.floor(Date.now() / 1000);
    // v4: lisensi per akun edclub, id = 'a' + user_id. Lisensi MESIN 3.5.x
    // yang masih sah & belum dipakai = akun pertamanya disetujui otomatis
    // (mesin dicatat 'claimed', akun berikutnya wajib disetujui manual).
    if (mc.startsWith("a") && m.status === "pending" && d.mtok &&
        !String(d.mtok.mc || "").startsWith("a") && await tokenOk(d.mtok)) {
      const mm = await getMachine(String(d.mtok.mc));
      if (mm && mm.status === "approved" && !mm.claimed) {
        mm.claimed = mc;
        await putMachine(mm);
        m.status = "approved";
        m.via = mm.mc;
      }
    }
    await putMachine(m);
    if (m.status === "approved") {
      return json({ status: "approved", token: await makeToken(mc) });
    }
    return json({ status: m.status });
  }

  if (u.pathname === "/api/license/status") {
    const mc = q.get("mc") || "";
    const m = await getMachine(mc);
    if (!m) return json({ status: "unknown" });
    // sengaja TANPA tulisan (dulu last_seen di-update di sini): poll
    // sering + tulis balik blob = jendela race yang bikin status
    // approve/revoked saling timpa. Terakhir terlihat cukup dari
    // POST /api/license/request.
    if (m.status !== "approved") return json({ status: m.status });
    return json({ status: "approved", token: await makeToken(mc) });
  }

  if (u.pathname === "/api/download") {
    let tok = null;
    try { tok = JSON.parse(atob(q.get("t") || "")); } catch (e) {}
    if (!(await tokenOk(tok))) return json({ error: "bad_token" }, 403);
    const raw = await env.META.get("release");
    if (!raw) return json({ error: "no_release_yet" }, 404);
    const rel = JSON.parse(raw);
    // REDIRECT ke GitHub release asset (CDN global, tahan banting).
    // Dulu: streaming 4 chunk KV dari POP user - POP lemah (Jakarta CGK
    // 10-11 Nov 2026) bikin 1102 + unduhan korup, dan updater 2.9.28
    // tak verifikasi hash -> bisa memasang exe korup = brick. Worker
    // kini nol kerja berat; updater lama (urllib) ikut 302 otomatis.
    // SYARAT: setiap rilis WAJIB melampirkan TypingBot.exe di gh release
    // v<versi> (publish.py mengeceknya).
    const gh = "https://github.com/ZafranHulaif/typingclubrobot/" +
               "releases/download/v" + rel.version + "/TypingBot.exe";
    return new Response(null, {
      status: 302,
      headers: { "location": gh, "cache-control": "no-store" },
    });
  }

  if (u.pathname === "/admin") {
    if (q.get("key") !== env.ADMIN_KEY) {
      return new Response("<h3>kunci admin salah</h3>", { status: 403 });
    }
    return new Response(adminPage(await allMachines(), q.get("key")), {
      headers: { "content-type": "text/html; charset=utf-8",
                 // WAJIB no-store: tanpa ini laptop bisa menyajikan salinan
                 // lama - aksi (revoke/approve) tampak tidak berefek padahal
                 // server sudah berubah, dan dua perangkat menampilkan
                 // status berbeda (keluhan live: HP benar, laptop basi).
                 "cache-control": "no-store, must-revalidate" },
    });
  }

  if (u.pathname === "/admin/action" && request.method === "POST") {
    const fd = await request.formData();
    const key = fd.get("key");
    if (key !== env.ADMIN_KEY) return json({ error: "bad_admin_key" }, 403);
    const mc = fd.get("mc");
    const act = fd.get("act");
    const peta = { approve: "approved", deny: "denied", revoke: "revoked", pending: "pending" };
    if (!peta[act] && act !== "delete") return json({ error: "bad_action" }, 400);
    if (act === "delete") {
      await env.MACHINES.delete(machineKey(mc));
    } else {
      const m = await getMachine(mc);
      if (!m) return json({ error: "unknown_mc" }, 404);
      m.status = peta[act];
      await putMachine(m);
    }
    // BASE kadang diisi tanpa https:// -> redirect rusak; pakai origin
    // permintaan sebagai jatuhnya. Respons manual (bukan Response.redirect)
    // supaya bisa menempelkan no-store: redirect yang ter-cache membuat
    // halaman admin setelah aksi tetap menampilkan daftar lama.
    const base = (env.BASE && env.BASE.includes("://")) ? env.BASE : u.origin;
    return new Response(null, { status: 302, headers: {
      location: `${base}/admin?key=${encodeURIComponent(key)}`,
      "cache-control": "no-store",
    } });
  }

  if (u.pathname === "/api/publish" && request.method === "POST") {
    if (request.headers.get("X-Admin-Key") !== env.ADMIN_KEY) {
      return json({ error: "bad_admin_key" }, 403);
    }
    const ver = request.headers.get("X-Version") || "";
    if (!ver) return json({ error: "version_required" }, 400);

    const lama = JSON.parse((await env.META.get("release")) || "null");
    const [buatHash, utkPotong] = request.body.tee();
    const diges = new crypto.DigestStream("SHA-256");
    const selesaiHash = buatHash.pipeTo(diges);

    const reader = utkPotong.getReader();
    let buf = new Uint8Array(CHUNK);
    let terisi = 0;
    let idx = 0;
    let total = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      let dari = 0;
      while (dari < value.length) {
        const ambil = Math.min(CHUNK - terisi, value.length - dari);
        buf.set(value.subarray(dari, dari + ambil), terisi);
        terisi += ambil;
        dari += ambil;
        if (terisi === CHUNK) {
          await env.META.put(chunkKey(ver, idx), buf.slice().buffer);
          idx += 1;
          terisi = 0;
        }
      }
    }
    if (terisi > 0) {
      await env.META.put(chunkKey(ver, idx), buf.slice(0, terisi).buffer);
      idx += 1;
    }
    await selesaiHash;
    if (total === 0 || idx === 0) return json({ error: "empty_body" }, 400);

    const rel = {
      version: ver,
      sha256: bytesToHex(new Uint8Array(await diges.digest)),
      size: total,
      chunks: idx,
      notes: request.headers.get("X-Notes") || "",
      released: new Date().toISOString(),
    };
    await env.META.put("release", JSON.stringify(rel));

    if (lama && lama.version && lama.version !== ver) {
      const nLama = lama.chunks || Math.max(1, Math.ceil((lama.size || 1) / CHUNK));
      for (let i = 0; i < nLama; i++) {
        await env.META.delete(chunkKey(lama.version, i));
      }
    }
    return json({ ok: true, sha256: rel.sha256, size: rel.size, chunks: idx });
  }

  return json({ error: "not_found" }, 404);
}

// Pecah isi laporan app ("kategori: ..", "=== CERITA USER ===",
// "=== LOG ... ===") utk webhook; log dipotong dari belakang.
function laporBagian(isi) {
  const kat = (isi.match(/^kategori: (.*)$/m) || [])[1] || "";
  const cer = (isi.match(/=== CERITA USER ===\n([\s\S]*?)\n\n=== LOG/) || [])[1] || "";
  const li = isi.indexOf("=== LOG");
  let log = li >= 0 ? isi.slice(isi.indexOf("\n", li) + 1) : "";
  if (log.length > 12000) log = "...\n" + log.slice(-12000);
  return { kategori: kat.slice(0, 80), cerita: cer.slice(0, 2000), log };
}

export default {
  async fetch(request, environment, ctx) {
    env = environment;
    try {
      return await handle(request, ctx);
    } catch (e) {
      return json({ error: String(e) }, 500);
    }
  },
};
