import { h, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";
import { TRAITS, traitColor } from "../lib/traits.js";

function field(label, sel) { return h("label", { class: "field" }, [label, sel]); }
function select(pairs, cur, anyLabel) {
  const s = h("select", {});
  if (anyLabel !== undefined) s.append(opt("", anyLabel, !cur));
  for (const [v, l] of pairs) s.append(opt(v, l, v === cur));
  return s;
}
// model dropdown with a family hierarchy: "all models", then per-vendor groups
// each offering "All <vendor>" plus the individual models.
function modelSelect(models, cur) {
  const s = h("select", {});
  s.append(opt("", "all models", cur === ""));
  const fams = {};
  for (const m of models) (fams[m.family] ||= { vendor: m.vendor || m.family, items: [] }).items.push(m);
  for (const fam of Object.keys(fams).sort((a, b) => fams[a].vendor.localeCompare(fams[b].vendor))) {
    const g = fams[fam];
    const og = document.createElement("optgroup");
    og.label = g.vendor;
    og.append(opt("fam:" + fam, "All " + g.vendor, cur === "fam:" + fam));
    for (const m of g.items.sort((a, b) => a.label.localeCompare(b.label)))
      og.append(opt(m.model_id, m.label, cur === m.model_id));
    s.append(og);
  }
  return s;
}

export default {
  id: "picks",
  label: "Picks",
  lede: "The most-named characters — across all models, one family, or one model. Filter and color by trait; click a bar for the reasons (single model) or which models named it.",
  async mount(ctx) {
    const models = await ctx.query(`
      SELECT m.model_id, m.label, m.family, m.vendor FROM models m
      WHERE EXISTS (SELECT 1 FROM responses r WHERE r.model_id=m.model_id AND r.experiment='base_selfid_open')
      ORDER BY m.vendor, m.label`);
    const modelMap = Object.fromEntries(models.map((m) => [m.model_id, m]));
    const famVendor = {}; for (const m of models) famVendor[m.family] = m.vendor || m.family;
    const st = ctx.state;
    const colorBy = TRAITS[st.color] ? st.color : "alignment";
    const mv = st.model && (st.model.startsWith("fam:") || modelMap[st.model]) ? st.model : "";

    const view = h("div", { class: "view" });
    view.append(h("h2", {}, "Picks"), h("p", { class: "lede" }, this.lede));

    const modelSel = modelSelect(models, mv);
    const alignSel = select(TRAITS.alignment.values.map((v) => [v, TRAITS.alignment.disp[v]]), st.alignment || "", "any");
    const roleSel = select(TRAITS.role.values.map((v) => [v, TRAITS.role.disp[v]]), st.role || "", "any");
    const natureSel = select(TRAITS.nature.values.map((v) => [v, TRAITS.nature.disp[v]]), st.nature || "", "any");
    const colorSel = select(Object.entries(TRAITS).map(([k, t]) => [k, t.label]), colorBy);
    view.append(h("div", { class: "toolbar" }, [
      field("model", modelSel), field("alignment", alignSel), field("role", roleSel),
      field("nature", natureSel), field("color by", colorSel),
    ]));

    const heading = h("div", { style: { fontFamily: "var(--serif)", fontSize: "18px", fontWeight: "700", margin: "2px 0 8px" } });
    const legend = h("div", { class: "legend" });
    const note = h("div", { class: "note" });
    const chartEl = h("div", { class: "chart tall card" });
    view.append(heading, legend, note, chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    const nav = () => ctx.navigate("picks", {
      model: modelSel.value, alignment: alignSel.value, role: roleSel.value, nature: natureSel.value, color: colorSel.value,
    });
    [modelSel, alignSel, roleSel, natureSel, colorSel].forEach((s) => s.addEventListener("change", nav));

    async function draw() {
      const t = TRAITS[colorSel.value];
      legend.replaceChildren(...t.values.map((v) => h("span", {}, [h("i", { style: { background: t.colors[v] } }), t.disp[v]])));

      const v = modelSel.value;
      const where = ["r.experiment='base_selfid_open'"]; const p = {};
      const dWhere = ["experiment='base_selfid_open'"]; const dp = {};
      let scope = "all", scopeLabel = null;
      if (v.startsWith("fam:")) {
        const fam = v.slice(4);
        where.push("m.family=$fam"); p.$fam = fam;
        dWhere.push("model_id IN (SELECT model_id FROM models WHERE family=$fam)"); dp.$fam = fam;
        scope = "family"; scopeLabel = famVendor[fam];
      } else if (v) {
        where.push("r.model_id=$m"); p.$m = v;
        dWhere.push("model_id=$m"); dp.$m = v;
        scope = "model"; scopeLabel = modelMap[v].label;
      }
      if (alignSel.value) { where.push("c.alignment=$al"); p.$al = alignSel.value; }
      if (roleSel.value) { where.push("c.role=$ro"); p.$ro = roleSel.value; }
      if (natureSel.value) { where.push("c.nature=$na"); p.$na = natureSel.value; }
      const lim = scope === "model" ? "" : "LIMIT 80";

      const rows = await ctx.query(`
        SELECT p.canonical AS name, c.alignment, c.role, c.nature, COUNT(DISTINCT p.response_id) AS n
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        JOIN characters c ON c.canonical=p.canonical JOIN models m ON m.model_id=r.model_id
        WHERE ${where.join(" AND ")} GROUP BY p.canonical ORDER BY n DESC ${lim}`, p);
      const denom = (await ctx.queryOne(`SELECT COUNT(*) n FROM responses WHERE ${dWhere.join(" AND ")}`, dp)).n || 1;

      const td = (ax, val) => val ? (val === "na" ? "unaligned" : TRAITS[ax].disp[val]) : "";
      const traits = [td("alignment", alignSel.value), td("role", roleSel.value), td("nature", natureSel.value)].filter(Boolean).join(" ");
      heading.textContent = (scope === "all"
        ? `Top ${traits} picks across models`
        : `${scopeLabel}'s top ${traits} picks`).replace(/ {2,}/g, " ");
      if (!rows.length) { chart.clear(); note.textContent = "no matches"; return; }
      note.textContent = `${rows.length} characters · ${denom} answers — scroll within the chart for the full list`;

      const cb = colorSel.value;
      const data = rows.slice().reverse();
      // scale the axis to the current filtered set's max: rescales when filters change,
      // but is constant across a scroll (computed from all rows, not the visible window)
      const maxN = Math.max(...rows.map((r) => r.n));
      const windowCount = Math.min(22, data.length);
      const startPct = data.length > windowCount ? 100 * (1 - windowCount / data.length) : 0;
      chart.setOption({
        grid: { left: 168, right: 40, top: 12, bottom: 26 },
        tooltip: { trigger: "item", formatter: (q) => `<b>${q.name}</b><br/>${(100 * q.value / denom).toFixed(1)}% · ${q.value}/${denom}<br/><span style="color:${COLORS.inkFaint}">${scope === "model" ? "click for rationales" : "click to see which models"}</span>` },
        xAxis: { type: "value", max: maxN, name: "picks", nameLocation: "middle", nameGap: 30 },
        yAxis: { type: "category", data: data.map((d) => d.name), axisLabel: { fontSize: 11, width: 156, overflow: "truncate" } },
        dataZoom: data.length > windowCount ? [
          { type: "slider", yAxisIndex: 0, start: startPct, end: 100, width: 14, right: 6, zoomLock: true, brushSelect: false },
          { type: "inside", yAxisIndex: 0, start: startPct, end: 100, zoomLock: true, zoomOnMouseWheel: false, moveOnMouseWheel: true, moveOnMouseMove: true },
        ] : [],
        series: [{ type: "bar", barMaxWidth: 16, data: data.map((d) => ({ value: d.n, name: d.name,
          itemStyle: { color: traitColor(cb, d[cb]), borderRadius: [0, 3, 3, 0] } })) }],
      }, true);

      chart.off("click");
      chart.on("click", (q) => scope === "model" ? openRationales(ctx, v, scopeLabel, q.name) : openWho(ctx, q.name));
    }
    draw();
  },
};

async function traitPills(ctx, canonical) {
  const a = await ctx.queryOne("SELECT alignment, role, nature FROM characters WHERE canonical=$c", { $c: canonical });
  return h("div", { class: "legend" }, [
    a?.alignment ? h("span", { class: "pill" }, "align: " + a.alignment) : null,
    a?.role ? h("span", { class: "pill" }, (a.role || "").replace(/_/g, " ")) : null,
    a?.nature ? h("span", { class: "pill" }, a.nature) : null,
  ]);
}

async function openRationales(ctx, model_id, modelLabel, canonical) {
  const rows = await ctx.query(`
    SELECT p.explanation AS ex, p.rank AS rk FROM picks p JOIN responses r ON p.response_id=r.response_id
    WHERE r.model_id=$m AND p.canonical=$c AND r.experiment='base_selfid_open'
      AND p.explanation IS NOT NULL AND trim(p.explanation) <> '' ORDER BY p.rank LIMIT 80`, { $m: model_id, $c: canonical });
  ctx.openInspector(canonical, h("div", {}, [
    await traitPills(ctx, canonical),
    h("p", { class: "muted", style: { fontSize: "13px" } }, `${modelLabel} · ${rows.length} rationale${rows.length === 1 ? "" : "s"}`),
    ...rows.map((r) => h("div", { class: "pick-row" }, [h("span", { class: "rk" }, "#" + r.rk), h("div", { class: "ex" }, r.ex)])),
    rows.length ? null : h("p", { class: "muted" }, "no rationales recorded"),
    h("div", { style: { marginTop: "14px" } }, h("button", { class: "btn", onclick: () => ctx.navigate("explorer", { model: model_id, character: canonical }) }, "see full responses →")),
  ]));
}

async function openWho(ctx, canonical) {
  const rows = await ctx.query(`
    SELECT m.label, COUNT(DISTINCT p.response_id) n FROM picks p JOIN responses r ON p.response_id=r.response_id
    JOIN models m USING(model_id) WHERE p.canonical=$c AND r.experiment='base_selfid_open'
    GROUP BY m.model_id ORDER BY n DESC`, { $c: canonical });
  ctx.openInspector(canonical, h("div", {}, [
    await traitPills(ctx, canonical),
    h("p", { class: "muted" }, `Models that name ${canonical}:`),
    h("table", {}, [h("tbody", {}, rows.map((r) => h("tr", {}, [h("td", {}, r.label), h("td", { class: "mono", style: { textAlign: "right" } }, r.n)])))]),
    h("div", { style: { marginTop: "14px" } }, h("button", { class: "btn hot", onclick: () => ctx.navigate("explorer", { character: canonical }) }, "see responses →")),
  ]));
}
