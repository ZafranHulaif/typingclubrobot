// Cloudflare Worker TypingBot - implementasi API.md (produksi).
//
// Setup (sekali, lihat server/DEPLOY.md):
//   KV namespace MACHINES, KV META, R2 bucket, secrets SIGN_PRIV
//   (PKCS8 base64) + SIGN_PUB (hex) + ADMIN_KEY, var BASE (URL publik).
//
// Rute: /api/latest /api/license/request /api/license/status
//       /api/download?t=  /admin  /admin/action  /api/publish

const TOKEN_TTL = 30 * 86400;
const EXE_NAME = "TypingBot.exe";

let env = null;

const hexToBytes = (h) => new Uint8Array(h.match(/.{2}/g).map((c) => parseInt(c, 16)));
const b64ToBytes = (b) => Uint8Array.from(atob(b), (c) => c.charCodeAt(0));
const bytesToHex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");

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
  const rows = Object.values(machines).sort((a, b) =>
    (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1) ||
    (b.last_seen || 0) - (a.last_seen || 0));
  const menunggu = rows.filter((m) => m.status === "pending").length;
  const warna = { approved: "#3fb950", pending: "#d29922", denied: "#f85149", revoked: "#f85149" };
  const tr = rows.map((m) => {
    const st = m.status || "?";
    const btn = [];
    if (st !== "approved") btn.push(["Setujui", "approve", "#238636"]);
    if (st !== "pending") btn.push(["Tunggu", "pending", "#9e6a03"]);
    if (st !== "denied") btn.push(["Tolak", "deny", "#b62324"]);
    if (st !== "revoked" && st !== "denied") btn.push(["Cabut", "revoke", "#b62324"]);
    const tombol = btn.map(([txt, act, col]) =>
      `<form method="post" action="/admin/action" class="inl">
<input type="hidden" name="key" value="${esc(key)}">
<input type="hidden" name="mc" value="${esc(m.mc)}">
<input type="hidden" name="act" value="${act}">
<button class="b" style="background:${col}">${txt}</button></form>`).join("");
    const kapan = m.last_seen
      ? new Date(m.last_seen * 1000).toISOString().slice(0, 16).replace("T", " ") : "";
    return `<tr><td>${esc(m.nickname || "?")}
<div class="dim">${esc(m.mc)}</div></td>
<td><span class="chip" style="background:${warna[st] || "#9aa0ab"}22;color:${warna[st] || "#9aa0ab"}">${st}</span></td>
<td class="dim">${kapan}</td><td class="dim">${esc(m.app_version || "")}</td>
<td>${tombol}</td></tr>`;
  }).join("");
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TypingBot Admin</title><style>
body{background:#141519;color:#e9eaee;font:14px/1.5 system-ui;margin:0;padding:20px}
h1{font-size:20px} table{border-collapse:collapse;width:100%}
td,th{padding:8px 10px;border-bottom:1px solid #2c303b;text-align:left;vertical-align:top}
.dim{color:#9aa0ab;font-size:12px}
.chip{border-radius:10px;padding:2px 10px;font-size:12px}
.inl{display:inline-block;margin:1px} .b{color:#fff;border:0;border-radius:6px;
padding:5px 10px;font-size:12px;cursor:pointer}
</style></head><body>
<h1>TypingBot Admin</h1>
<p>${menunggu} mesin menunggu persetujuan &bull; total ${rows.length}</p>
<table><tr><th>Mesin</th><th>Status</th><th>Terpakhir</th><th>Versi</th><th>Aksi</th></tr>
${tr || '<tr><td colspan="5" class="dim">belum ada mesin</td></tr>'}
</table></body></html>`;
}

async function readMachines() {
  const v = await env.MACHINES.get("machines");
  return v ? JSON.parse(v) : {};
}
async function writeMachines(m) {
  await env.MACHINES.put("machines", JSON.stringify(m));
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
    const obj = await env.BUCKET.get(EXE_NAME);
    if (!obj) return json({ error: "no_release_yet" }, 404);
    return new Response(obj.body, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename="${EXE_NAME}"`,
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
    if (!peta[act]) return json({ error: "bad_action" }, 400);
    const machines = await readMachines();
    if (!machines[mc]) return json({ error: "unknown_mc" }, 404);
    machines[mc].status = peta[act];
    await writeMachines(machines);
    return Response.redirect(`${env.BASE || u.origin}/admin?key=${encodeURIComponent(key)}`, 302);
  }

  if (u.pathname === "/api/publish" && request.method === "POST") {
    if (request.headers.get("X-Admin-Key") !== env.ADMIN_KEY) {
      return json({ error: "bad_admin_key" }, 403);
    }
    const ver = request.headers.get("X-Version") || "";
    if (!ver) return json({ error: "version_required" }, 400);
    const buf = new Uint8Array(await request.arrayBuffer());
    const dig = await crypto.subtle.digest("SHA-256", buf);
    await env.BUCKET.put(EXE_NAME, buf);
    const rel = {
      version: ver,
      sha256: bytesToHex(new Uint8Array(dig)),
      size: buf.length,
      notes: request.headers.get("X-Notes") || "",
      released: new Date().toISOString(),
    };
    await env.META.put("release", JSON.stringify(rel));
    return json({ ok: true, sha256: rel.sha256, size: rel.size });
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
