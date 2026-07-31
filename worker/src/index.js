// token-bar-status — Cloudflare Worker
//
// Serves a mobile-friendly, read-only view of the same account/quota data the
// macOS menu bar app shows locally. The Mac never exposes its loopback server
// to the internet; instead `backend/cloud_push.py` POSTs the latest
// status.json snapshot here (PUSH_TOKEN) and this Worker stores it in KV.
// Phones load the dashboard and read it back (VIEW_TOKEN) — two separate
// secrets so view access can be shared or revoked independently of write
// access.
//
// The dashboard markup lives in dashboard.html and is inlined at build time by
// wrangler's text module rule, so its client-side JS is never re-escaped by a
// host template literal.
import DASHBOARD_HTML from "./dashboard.html";

const KV_KEY = "latest";

// Snapshots are small (~25KB today); cap well above that but low enough that a
// leaked push token can't be used to fill KV with junk.
const MAX_PUSH_BYTES = 2 * 1024 * 1024;

function noStore(body, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Cache-Control", "no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "no-referrer");
  return new Response(body, { ...init, headers });
}

function json(obj, status = 200) {
  return noStore(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function bearer(request) {
  const m = /^Bearer\s+(.+)$/i.exec((request.headers.get("Authorization") || "").trim());
  return m ? m[1] : null;
}

// Length-independent compare over the SHA-256 digests, so neither the token
// contents nor its length leak through response timing.
async function tokenEquals(candidate, expected) {
  if (!candidate || !expected) return false;
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(candidate)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  const av = new Uint8Array(a);
  const bv = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < av.length; i++) diff |= av[i] ^ bv[i];
  return diff === 0;
}

async function handlePush(request, env) {
  if (!(await tokenEquals(bearer(request), env.PUSH_TOKEN))) {
    return json({ error: "unauthorized" }, 401);
  }
  const body = await request.text();
  if (body.length > MAX_PUSH_BYTES) {
    return json({ error: "payload too large" }, 413);
  }
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return json({ error: "invalid json body" }, 400);
  }
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.accounts)) {
    return json({ error: "expected a status payload with an accounts array" }, 400);
  }
  const received_at = new Date().toISOString();
  await env.STATUS_KV.put(KV_KEY, JSON.stringify({ payload, received_at }));
  return json({ ok: true, received_at, accounts: payload.accounts.length });
}

async function handleStatus(request, env) {
  const token = bearer(request) || new URL(request.url).searchParams.get("t");
  if (!(await tokenEquals(token, env.VIEW_TOKEN))) {
    return json({ error: "unauthorized" }, 401);
  }
  const raw = await env.STATUS_KV.get(KV_KEY);
  if (!raw) return json({ error: "no data pushed yet" }, 404);
  return noStore(raw, {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);

    if (pathname === "/push") {
      return request.method === "POST"
        ? handlePush(request, env)
        : json({ error: "method not allowed" }, 405);
    }
    if (pathname === "/api/status") {
      return request.method === "GET"
        ? handleStatus(request, env)
        : json({ error: "method not allowed" }, 405);
    }
    if (pathname === "/health") {
      return json({ ok: true });
    }
    if (request.method === "GET" && (pathname === "/" || pathname === "/index.html")) {
      return noStore(DASHBOARD_HTML, {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }
    return json({ error: "not found" }, 404);
  },
};
