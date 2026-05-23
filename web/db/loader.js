// Spawns the SQLite worker, streams the .db file in with a progress callback,
// caches the bytes in Cache Storage, and exposes a promise-based query() RPC.

const DB_URL = new URL("../../llmchar.db", import.meta.url).href;
const CACHE_NAME = "llmchar-db-v1";

let worker = null;
let seq = 0;
const pending = new Map();

function rpc(type, payload, transfer) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, type, payload }, transfer || []);
  });
}

async function fetchWithProgress(url, onProgress) {
  // version the cache by the file's ETag/Last-Modified so a rebuilt DB busts it
  let ver = "";
  try {
    const head = await fetch(url, { method: "HEAD" });
    ver = head.headers.get("etag") || head.headers.get("last-modified") || head.headers.get("content-length") || "";
  } catch (_) { /* HEAD unsupported: fall back to unversioned key */ }
  const cacheKey = url + (ver ? "?v=" + encodeURIComponent(ver) : "");
  // Cache Storage only exists in a secure context (HTTPS or localhost). Over
  // plain HTTP on a LAN address `caches` is undefined — skip caching, just fetch.
  const cache = (typeof caches !== "undefined")
    ? await caches.open(CACHE_NAME).catch(() => null)
    : null;
  if (cache) {
    const hit = await cache.match(cacheKey);
    if (hit) {
      onProgress(1, "cached");
      return await hit.arrayBuffer();
    }
    // drop stale versions of this DB
    for (const k of await cache.keys()) {
      if (k.url.startsWith(url)) cache.delete(k).catch(() => {});
    }
  }
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`failed to fetch DB (${resp.status})`);
  const total = Number(resp.headers.get("content-length")) || 0;
  const reader = resp.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    if (total) onProgress(received / total, "download");
  }
  const buf = new Uint8Array(received);
  let off = 0;
  for (const c of chunks) { buf.set(c, off); off += c.length; }
  if (cache) {
    cache.put(cacheKey, new Response(buf, { headers: { "content-type": "application/octet-stream" } }))
      .catch(() => {});
  }
  return buf.buffer;
}

export async function initDB(onProgress = () => {}) {
  worker = new Worker(new URL("./db.worker.js", import.meta.url));
  worker.onmessage = (e) => {
    const { id, ok, rows, error } = e.data;
    const p = pending.get(id);
    if (!p) return;
    pending.delete(id);
    ok ? p.resolve(rows) : p.reject(new Error(error));
  };
  const buf = await fetchWithProgress(DB_URL, onProgress);
  onProgress(1, "parsing");
  await rpc("load", buf, [buf]);
}

export function query(sql, params) {
  return rpc("query", { sql, params });
}

// convenience: first row, or first scalar
export async function queryOne(sql, params) {
  const r = await query(sql, params);
  return r[0] || null;
}
