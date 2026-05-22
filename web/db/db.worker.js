// Classic Web Worker: hosts the SQLite database (sql.js / WASM) off the main
// thread. Receives the .db bytes once, then answers query RPCs.
/* eslint-disable no-undef */
importScripts(new URL("../vendor/sqljs/sql-wasm.js", self.location.href).href);

let db = null;

function runQuery(sql, params) {
  const stmt = db.prepare(sql);
  if (params && (Array.isArray(params) ? params.length : Object.keys(params).length)) {
    stmt.bind(params);
  }
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

self.onmessage = async (e) => {
  const { id, type, payload } = e.data;
  try {
    if (type === "load") {
      const SQL = await initSqlJs({
        locateFile: (f) => new URL("../vendor/sqljs/" + f, self.location.href).href,
      });
      db = new SQL.Database(new Uint8Array(payload));
      self.postMessage({ id, ok: true });
    } else if (type === "query") {
      self.postMessage({ id, ok: true, rows: runQuery(payload.sql, payload.params) });
    } else {
      self.postMessage({ id, ok: false, error: "unknown message type " + type });
    }
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message ? err.message : err) });
  }
};
