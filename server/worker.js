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
    headers: { "content-type": "application/json; charset=utf-8" },
  });

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

function adminPage(machines, key) {
  const baris = (m) => {
    const st = m.status;
    let btn;
    if (st === "pending") {
      btn = [["Setujui", "approve", "#238636"], ["Tolak", "deny", "#b62324"]];
    } else if (st === "approved") {
      btn = [["Cabut akses", "revoke", "#b62324"], ["Hapus", "delete", "#444a56"]];
    } else {
      btn = [["Setujui ulang", "approve", "#238636"], ["Hapus", "delete", "#444a56"]];
    }
    const tombol = btn.map(([txt, act, col]) =>
      `<form method="post" action="/admin/action" class="inl">
<input type="hidden" name="key" value="${esc(key)}">
<input type="hidden" name="mc" value="${esc(m.mc)}">
<input type="hidden" name="act" value="${act}">
<button class="b" style="background:${col}">${txt}</button></form>`).join("");
    const kapan = m.last_seen
      ? new Date(m.last_seen * 1000).toLocaleString("id-ID",
          { day: "2-digit", month: "2-digit", year: "numeric",
            hour: "2-digit", minute: "2-digit" }) : "-";
    return `<tr><td><b>${esc(m.nickname || "?")}</b>
<div class="dim">${esc(m.mc)}</div></td>
<td class="dim">${esc(m.app_version || "-")}</td>
<td class="dim">${kapan}</td><td>${tombol}</td></tr>`;
  };
  const tabel = (daftar) => daftar.length
    ? `<table><tr><th>Mesin</th><th>Versi</th><th>Terakhir</th><th>Aksi</th></tr>`
      + daftar.map(baris).join("") + "</table>"
    : '<div class="dim kosong">tidak ada</div>';
  const semua = Object.values(machines).sort((a, b) =>
    (b.last_seen || 0) - (a.last_seen || 0));
  const menunggu = semua.filter((m) => m.status === "pending");
  const oke = semua.filter((m) => m.status === "approved");
  const buruk = semua.filter((m) => m.status === "denied" || m.status === "revoked");
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TypingBot Admin</title><style>
body{background:#141519;color:#e9eaee;font:14px/1.5 system-ui;margin:0;padding:20px}
h1{font-size:20px;margin:0 0 10px}
.atas{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.chip{border-radius:12px;padding:3px 12px;font-size:12px;font-weight:600}
.k{background:#d2992222;color:#d29922} .h{background:#3fb95022;color:#3fb950}
.x{background:#f8514922;color:#f85149}
.muat{color:#e9eaee;background:#20232b;border:1px solid #2c303b;border-radius:8px;
padding:5px 12px;font-size:12px;cursor:pointer;text-decoration:none}
.dim{color:#9aa0ab;font-size:12px} .kosong{padding:10px 2px}
.judul{margin:18px 0 4px;font-weight:700;font-size:15px}
table{border-collapse:collapse;width:100%}
td,th{padding:8px 10px;border-bottom:1px solid #2c303b;text-align:left;vertical-align:top}
.inl{display:inline-block;margin:1px} .b{color:#fff;border:0;border-radius:6px;
padding:5px 10px;font-size:12px;cursor:pointer}
</style></head><body>
<h1>⚡ TypingBot Admin</h1>
<div class="atas">
<span class="chip k">⏳ ${menunggu.length} menunggu</span>
<span class="chip h">✅ ${oke.length} disetujui</span>
<span class="chip x">⛔ ${buruk.length} ditolak/dicabut</span>
<a class="muat" href="/admin?key=${encodeURIComponent(key)}">↻ Muat ulang</a>
<span class="dim">otomatis setiap 8 detik</span>
</div>
<div id="isi">
<div class="judul">⏳ Menunggu persetujuan</div>${tabel(menunggu)}
<div class="judul">✅ Disetujui</div>${tabel(oke)}
<div class="judul">⛔ Ditolak / dicabut</div>${tabel(buruk)}
</div>
<script>
setInterval(async()=>{try{
const r=await fetch(location.href);
const t=await r.text();
const d=new DOMParser().parseFromString(t,'text/html');
const n=d.getElementById('isi');
if(n)document.getElementById('isi').replaceWith(n);
}catch(e){}},8000);
</script></body></html>`;
}

async function readMachines() {
  const v = await env.MACHINES.get("machines");
  return v ? JSON.parse(v) : {};
}
async function writeMachines(m) {
  await env.MACHINES.put("machines", JSON.stringify(m));
}

function chunkKey(ver, i) {
  return `exe:${ver}:${i}`;
}

async function handle(request) {
  const u = new URL(request.url);
  const q = u.searchParams;

  if (u.pathname === "/api/latest") {
    const rel = await env.META.get("release");
    return rel ? json(JSON.parse(rel)) : json({ error: "no_release_yet" }, 404);
  }

  if (u.pathname === "/api/license/request" && request.method === "POST") {
    const d = await request.json();
    const mc = String(d.mc || "").slice(0, 32);
    if (!mc) return json({ error: "mc_required" }, 400);
    const machines = await readMachines();
    const m = machines[mc] ||
      { mc, status: "pending", first_seen: Math.floor(Date.now() / 1000) };
    m.nickname = String(d.nickname || "?").slice(0, 40) || m.nickname || "?";
    m.app_version = String(d.app_version || "").slice(0, 16);
    m.last_seen = Math.floor(Date.now() / 1000);
    machines[mc] = m;
    await writeMachines(machines);
    if (m.status === "approved") {
      return json({ status: "approved", token: await makeToken(mc) });
    }
    return json({ status: m.status });
  }

  if (u.pathname === "/api/license/status") {
    const mc = q.get("mc") || "";
    const machines = await readMachines();
    const m = machines[mc];
    if (!m) return json({ status: "unknown" });
    if (m.status !== "approved") return json({ status: m.status });
    m.last_seen = Math.floor(Date.now() / 1000);
    machines[mc] = m;
    await writeMachines(machines);
    return json({ status: "approved", token: await makeToken(mc) });
  }

  if (u.pathname === "/api/download") {
    let tok = null;
    try { tok = JSON.parse(atob(q.get("t") || "")); } catch (e) {}
    if (!(await tokenOk(tok))) return json({ error: "bad_token" }, 403);
    const raw = await env.META.get("release");
    if (!raw) return json({ error: "no_release_yet" }, 404);
    const rel = JSON.parse(raw);
    const n = Math.max(1, Math.ceil((rel.size || 1) / CHUNK));
    async function* potongan() {
      for (let i = 0; i < n; i++) {
        const b = await env.META.get(chunkKey(rel.version, i), "arrayBuffer");
        if (b === null) throw new Error("chunk_missing");
        yield b;
      }
    }
    return new Response(ReadableStream.from(potongan()), {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="TypingBot.exe"',
        "content-length": String(rel.size || 0),
      },
    });
  }

  if (u.pathname === "/admin") {
    if (q.get("key") !== env.ADMIN_KEY) {
      return new Response("<h3>kunci admin salah</h3>", { status: 403 });
    }
    return new Response(adminPage(await readMachines(), q.get("key")), {
      headers: { "content-type": "text/html; charset=utf-8" },
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
    const machines = await readMachines();
    if (!machines[mc]) return json({ error: "unknown_mc" }, 404);
    if (act === "delete") {
      delete machines[mc];
    } else {
      machines[mc].status = peta[act];
    }
    await writeMachines(machines);
    // BASE kadang diisi tanpa https:// -> redirect rusak; pakai origin
    // permintaan sebagai jatuhnya.
    const base = (env.BASE && env.BASE.includes("://")) ? env.BASE : u.origin;
    return Response.redirect(`${base}/admin?key=${encodeURIComponent(key)}`, 302);
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

export default {
  async fetch(request, environment, ctx) {
    env = environment;
    try {
      return await handle(request);
    } catch (e) {
      return json({ error: String(e) }, 500);
    }
  },
};
