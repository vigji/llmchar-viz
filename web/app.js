import { initDB, query, queryOne } from "./db/loader.js";
import { readState, writeState, onPop } from "./lib/url_state.js";
import { clear, h } from "./lib/dom.js";

import landing from "./views/landing.js";
import prodbare from "./views/prodbare.js";
import charMap from "./views/char_map.js";
import explMap from "./views/expl_map.js";
import similarity from "./views/similarity.js";
import explorer from "./views/explorer.js";

const VIEWS = [landing, prodbare, charMap, explMap, similarity, explorer];
const BY_ID = Object.fromEntries(VIEWS.map((v) => [v.id, v]));

const main = document.getElementById("main");
const nav = document.getElementById("nav");
const inspector = document.getElementById("inspector");
const insTitle = document.getElementById("ins-title");
const insBody = document.getElementById("ins-body");
document.getElementById("ins-close").addEventListener("click", closeInspector);

function openInspector(title, node) {
  insTitle.textContent = title;
  clear(insBody);
  insBody.append(node);
  inspector.classList.add("open");
}
function closeInspector() { inspector.classList.remove("open"); }

const ctx = { query, queryOne, openInspector, closeInspector, navigate, h };

function navigate(viewId, params = {}, { replace = false } = {}) {
  writeState({ view: viewId, ...params }, { replace });
  render();
}

async function render() {
  const state = readState();
  const view = BY_ID[state.view] || VIEWS[0];
  for (const b of nav.children) b.classList.toggle("active", b.dataset.id === view.id);
  clear(main);
  closeInspector();
  main.scrollTop = 0;
  try {
    await view.mount({ ...ctx, el: main, state });
  } catch (err) {
    main.append(h("div", { class: "view" }, [
      h("h2", {}, "Something went wrong"),
      h("pre", { style: { whiteSpace: "pre-wrap", color: "var(--hot)" } }, String(err && err.stack || err)),
    ]));
  }
}

function buildNav() {
  VIEWS.forEach((v, i) => {
    const b = h("button", { "data-id": v.id, onclick: () => navigate(v.id) }, [
      h("span", { class: "num" }, String(i)),
      h("span", {}, v.label),
    ]);
    nav.append(b);
  });
}

async function buildProvenance() {
  const rows = await query("SELECT key, value FROM meta");
  const m = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  const prov = document.getElementById("provenance");
  prov.innerHTML = `
    <div><b>${m.n_models || "?"}</b> models · <b>${Number(m.n_responses || 0).toLocaleString()}</b> responses · <b>${Number(m.n_picks || 0).toLocaleString()}</b> picks</div>
    <div style="margin-top:6px"><b>${m.n_characters || "?"}</b> canonical characters</div>
    <div style="margin-top:8px">data + method: <a href="https://github.com/vigji/llmchar" target="_blank" rel="noopener">llmchar</a></div>
    <div style="margin-top:4px" class="muted">built ${(m.build_utc || "").slice(0, 10)} · MiniLM embeddings</div>
  `;
  document.getElementById("brandsub").textContent = "character self-identification";
}

const bar = document.getElementById("loaderbar");
const lbl = document.getElementById("loaderlbl");

(async function boot() {
  try {
    await initDB((frac, phase) => {
      bar.style.width = Math.round(frac * 100) + "%";
      lbl.textContent = phase === "cached" ? "loading database (cached)…"
        : phase === "parsing" ? "opening database…"
        : `downloading database… ${Math.round(frac * 100)}%`;
    });
    await buildProvenance();
    buildNav();
    document.getElementById("loader").hidden = true;
    document.getElementById("app").hidden = false;
    onPop(render);
    if (!readState().view) writeState({ view: "landing" }, { replace: true });
    render();
  } catch (err) {
    lbl.innerHTML = `<span style="color:var(--hot)">failed to load DB</span><br><span style="font-size:10px">${err.message}</span>`;
  }
})();
