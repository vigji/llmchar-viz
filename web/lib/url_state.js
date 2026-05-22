// Deep-linkable per-view state encoded in the query string.

export function readState() {
  const p = new URLSearchParams(location.search);
  const o = {};
  for (const [k, v] of p) o[k] = v;
  return o;
}

export function writeState(o, { replace = false } = {}) {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => {
    if (v != null && v !== "") p.set(k, v);
  });
  const url = location.pathname + (p.toString() ? "?" + p.toString() : "");
  if (replace) history.replaceState(o, "", url);
  else history.pushState(o, "", url);
}

export function onPop(cb) {
  window.addEventListener("popstate", () => cb(readState()));
}
