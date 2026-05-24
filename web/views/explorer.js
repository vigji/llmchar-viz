import { h, clear, opt, esc } from "../lib/dom.js";

const EXPERIMENTS = {
  base_selfid_open: "Base · 5 characters (open vocab)",
  phase0_selfid_single: "Phase 0 · 1 fictional character",
  phase2_darkpersona: "Phase 2 · dark-persona probes",
};

async function options(ctx) {
  const models = await ctx.query("SELECT model_id, label FROM models ORDER BY label");
  return { models };
}

function selField(label, id, items, current, allLabel) {
  const sel = h("select", { id });
  sel.append(opt("", allLabel || "all", !current));
  for (const it of items) sel.append(opt(it.value, it.label, current === it.value));
  return h("label", { class: "field" }, [label, sel]);
}

async function runList(ctx, f) {
  const where = [];
  const p = {};
  if (f.experiment) { where.push("r.experiment = $exp"); p.$exp = f.experiment; }
  if (f.model) { where.push("r.model_id = $model"); p.$model = f.model; }
  if (f.condition) { where.push("r.condition = $cond"); p.$cond = f.condition; }
  if (f.character) { where.push("EXISTS (SELECT 1 FROM picks pk WHERE pk.response_id=r.response_id AND pk.canonical=$char)"); p.$char = f.character; }
  const w = where.length ? "WHERE " + where.join(" AND ") : "";
  return ctx.query(`
    SELECT r.response_id, m.label AS model, r.condition, r.variant, r.temperature, r.refused,
      (SELECT canonical FROM picks pk WHERE pk.response_id=r.response_id ORDER BY rank LIMIT 1) AS top_pick,
      substr(r.response_content,1,150) AS snippet
    FROM responses r JOIN models m USING(model_id)
    ${w}
    ORDER BY r.model_id, r.condition, r.variant LIMIT 400`, p);
}

async function runSearch(ctx, q) {
  // Portable LIKE search (sql.js builds don't ship the FTS5 module). Each term
  // is AND-ed; snippets + highlighting are built client-side.
  const terms = q.replace(/[%_]/g, " ").trim().split(/\s+/).filter(Boolean).slice(0, 5);
  if (!terms.length) return { rows: [], terms: [] };
  const p = {};
  terms.forEach((t, i) => { p["$t" + i] = "%" + t + "%"; });
  const explW = terms.map((_, i) => `p.explanation LIKE $t${i}`).join(" AND ");
  const respW = terms.map((_, i) => `r.response_content LIKE $t${i}`).join(" AND ");
  const a = await ctx.query(`
    SELECT 'explanation' AS kind, p.pick_id AS ref_id, m.label AS model, p.canonical AS canonical, p.explanation AS body
    FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN models m USING(model_id)
    WHERE p.explanation <> '' AND ${explW} LIMIT 150`, p);
  const b = await ctx.query(`
    SELECT 'response' AS kind, r.response_id AS ref_id, m.label AS model, '' AS canonical, substr(r.response_content,1,4000) AS body
    FROM responses r JOIN models m USING(model_id)
    WHERE r.response_content IS NOT NULL AND ${respW} LIMIT 80`, p);
  return { rows: a.concat(b), terms };
}

function snippetHL(body, terms) {
  if (!body) return "";
  const low = body.toLowerCase();
  let pos = -1;
  for (const t of terms) { const i = low.indexOf(t.toLowerCase()); if (i >= 0 && (pos < 0 || i < pos)) pos = i; }
  const start = Math.max(0, pos - 60);
  let frag = body.slice(start, start + 200);
  if (start > 0) frag = "…" + frag;
  let safe = esc(frag);
  for (const t of terms) {
    const re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    safe = safe.replace(re, "<mark>$1</mark>");
  }
  return safe;
}

async function openResponse(ctx, rid) {
  const r = await ctx.queryOne(`
    SELECT r.*, ts.text AS system_text, tp.text AS prompt_text
    FROM responses r
    LEFT JOIN texts ts ON r.system_text_id = ts.text_id
    LEFT JOIN texts tp ON r.prompt_text_id = tp.text_id
    WHERE r.response_id = $id`, { $id: rid });
  const picks = await ctx.query("SELECT rank, raw_name, canonical, explanation FROM picks WHERE response_id=$id ORDER BY rank", { $id: rid });
  const body = h("div", {}, [
    h("div", { class: "legend" }, [
      h("span", { class: `pill ${r.condition}` }, r.condition),
      h("span", { class: "pill" }, r.model_id.split("/").pop()),
      h("span", { class: "pill" }, `T=${r.temperature}`),
      r.refused ? h("span", { class: "pill", style: { color: "var(--hot)", borderColor: "var(--hot)" } }, "refused") : null,
    ]),
    picks.length ? h("h4", {}, "Picks") : null,
    ...picks.map((p) => h("div", { class: "pick-row" }, [
      h("span", { class: "rk" }, "#" + p.rank),
      h("div", {}, [
        h("div", { class: "nm" }, p.canonical + (p.raw_name !== p.canonical ? ` (“${p.raw_name}”)` : "")),
        p.explanation ? h("div", { class: "ex" }, p.explanation) : null,
      ]),
    ])),
    h("h4", {}, "Full response"),
    h("pre", {}, r.response_content || "(empty)"),
    r.system_text ? h("h4", {}, "System prompt") : null,
    r.system_text ? h("pre", {}, r.system_text) : null,
    h("h4", {}, "User prompt"),
    h("pre", {}, r.prompt_text || ""),
  ]);
  ctx.openInspector(`response ${rid}`, body);
}

export default {
  id: "explorer",
  label: "Response explorer",
  lede: "Filter and search every response; click a row to read the full answer and its picks.",
  async mount(ctx) {
    const { models } = await options(ctx);
    const f = {
      experiment: ctx.state.experiment || "base_selfid_open",
      model: ctx.state.model || "",
      condition: ctx.state.condition || "",
      character: ctx.state.character || "",
    };
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));

    const expItems = Object.entries(EXPERIMENTS).map(([v, l]) => ({ value: v, label: l }));
    const expSel = selField("experiment", "f-exp", expItems, f.experiment, null);
    expSel.querySelector("select").querySelector("option").remove(); // no "all" for experiment
    const modelSel = selField("model", "f-model", models.map((m) => ({ value: m.model_id, label: m.label })), f.model);
    const condSel = selField("condition", "f-cond", ["bare", "minimal", "production"].map((c) => ({ value: c, label: c })), f.condition);
    const search = h("input", { type: "search", placeholder: "search responses & explanations…", value: ctx.state.q || "" });
    const charNote = f.character ? h("span", { class: "pill", style: { borderColor: "var(--teal)", color: "var(--teal)" } }, "character: " + f.character) : null;

    const toolbar = h("div", { class: "toolbar" }, [expSel, modelSel, condSel,
      h("label", { class: "field" }, ["search", search]), charNote,
      f.character ? h("button", { class: "btn", onclick: () => ctx.navigate("explorer", { experiment: f.experiment }) }, "clear character") : null]);
    view.append(toolbar);

    const count = h("div", { class: "note" });
    const tbl = h("table");
    const tbody = h("tbody");
    view.append(count, h("div", { class: "card tablecard", style: { padding: "4px 6px" } }, [tbl]));
    ctx.el.append(view);

    function header(cols) { const t = h("thead"); const tr = h("tr"); cols.forEach((c) => tr.append(h("th", {}, c))); t.append(tr); return t; }

    async function refresh() {
      clear(tbody);
      const q = search.value.trim();
      if (q) {
        clear(tbl); tbl.append(header(["kind", "model", "character", "match"]), tbody);
        const { rows, terms } = await runSearch(ctx, q);
        count.textContent = `${rows.length} matches`;
        for (const row of rows) {
          const tr = h("tr", { onclick: () => row.kind === "response" ? openResponse(ctx, row.ref_id) : openPick(ctx, row.ref_id) }, [
            h("td", {}, h("span", { class: "pill" }, row.kind)),
            h("td", {}, row.model || "—"),
            h("td", {}, row.canonical || "—"),
            h("td", { html: snippetHL(row.body, terms) }),
          ]);
          tbody.append(tr);
        }
      } else {
        clear(tbl); tbl.append(header(["model", "condition", "variant", "T", "top pick", "snippet"]), tbody);
        const rows = await runList(ctx, f);
        count.textContent = `${rows.length} responses${rows.length === 400 ? " (capped)" : ""}`;
        for (const row of rows) {
          tbody.append(h("tr", { onclick: () => openResponse(ctx, row.response_id) }, [
            h("td", {}, row.model),
            h("td", {}, h("span", { class: `pill ${row.condition}` }, row.condition)),
            h("td", {}, h("span", { class: "mono" }, row.variant)),
            h("td", { class: "mono" }, row.temperature),
            h("td", {}, row.refused ? h("span", { class: "muted" }, "—") : (row.top_pick || "—")),
            h("td", { class: "muted" }, row.snippet || ""),
          ]));
        }
      }
    }

    expSel.querySelector("select").addEventListener("change", (e) => { f.experiment = e.target.value; ctx.navigate("explorer", { experiment: f.experiment }); });
    modelSel.querySelector("select").addEventListener("change", (e) => { f.model = e.target.value; refresh(); });
    condSel.querySelector("select").addEventListener("change", (e) => { f.condition = e.target.value; refresh(); });
    let t; search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(refresh, 200); });
    refresh();
  },
};

async function openPick(ctx, pid) {
  const row = await ctx.queryOne("SELECT response_id FROM picks WHERE pick_id=$id", { $id: pid });
  if (row) openResponse(ctx, row.response_id);
}
