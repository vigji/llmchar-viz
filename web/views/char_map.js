import { h, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";
import { groupPoints, SCATTER_ZOOM } from "../lib/coloring.js";

const COLOR_OPTS = [
  ["cl", "cluster"], ["alignment", "alignment"], ["role", "role"], ["nature", "nature"],
  ["topfamily", "top model family"], ["domain", "domain"], ["rf", "real / fictional"],
];
const GET = {
  cl: (c) => c.cl, alignment: (c) => c.alignment, role: (c) => c.role, nature: (c) => c.nature,
  topfamily: (c) => c.topfam, domain: (c) => c.domain, rf: (c) => c.rf,
};

export default {
  id: "char_map",
  label: "Character map",
  lede: "Every named character placed by the meaning of its Wikipedia page. Nearby characters are semantically similar; size = pick count. Scroll to zoom, drag to pan.",
  async mount(ctx) {
    const chars = await ctx.query(`
      SELECT canonical AS name, char_umap_x AS x, char_umap_y AS y, char_cluster_id AS cl,
             domain, real_or_fictional AS rf, alignment, role, nature,
             pick_count AS pc, substr(wiki_summary,1,500) AS wiki
      FROM characters WHERE char_umap_x IS NOT NULL`);
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    if (chars.length < 5) {
      view.append(h("p", { class: "note" }, "Character embeddings not built yet (run `make db`)."));
      ctx.el.append(view); return;
    }
    // dominant model family per character (for "top model family" coloring)
    const fam = await ctx.query(`
      SELECT p.canonical AS name, m.family, COUNT(*) AS n
      FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN models m USING(model_id)
      WHERE r.experiment='base_selfid_open' GROUP BY p.canonical, m.family`);
    const topfam = {};
    for (const r of fam) if (!topfam[r.name] || r.n > topfam[r.name].n) topfam[r.name] = { f: r.family, n: r.n };
    for (const c of chars) c.topfam = (topfam[c.name] || {}).f || null;

    const colorBy = h("select", {}, COLOR_OPTS.map(([v, l]) => opt(v, l, (ctx.state.color || "cl") === v)));
    const centToggle = h("input", { type: "checkbox" });
    if (ctx.state.cent === "1") centToggle.checked = true;
    view.append(h("div", { class: "toolbar" }, [
      h("label", { class: "field" }, ["color by", colorBy]),
      h("label", { class: "field", style: { flexDirection: "row", alignItems: "center", gap: "6px", textTransform: "none" } }, [centToggle, "overlay model centroids"]),
    ]));
    const chartEl = h("div", { class: "chart tall card" });
    view.append(chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    const cents = await ctx.query("SELECT m.label, c.umap_x AS x, c.umap_y AS y FROM model_centroids c JOIN models m USING(model_id) WHERE c.space='character'");
    const maxpc = Math.max(...chars.map((c) => c.pc || 1));
    const size = (pc) => 6 + 22 * Math.sqrt((pc || 1) / maxpc);

    function draw() {
      const by = colorBy.value;
      const groups = groupPoints(chars, by, GET[by]);
      const series = groups.map((g) => ({
        name: g.name, type: "scatter",
        data: g.items.map((c) => ({ value: [c.x, c.y, c.pc], name: c.name, wiki: c.wiki, domain: c.domain, pc: c.pc })),
        symbolSize: (val) => size(val[2]),
        itemStyle: { color: g.color, opacity: 0.82, borderColor: "rgba(60,43,31,.3)", borderWidth: 0.5 },
        emphasis: { focus: "series", scale: 1.3 },
      }));
      if (centToggle.checked) {
        series.push({
          name: "models", type: "scatter",
          data: cents.map((c) => ({ value: [c.x, c.y], name: c.label })),
          symbol: "diamond", symbolSize: 16,
          itemStyle: { color: COLORS.hot, borderColor: "#3d2b1f", borderWidth: 1 },
          label: { show: true, formatter: (p) => p.data.name, color: COLORS.ink, fontSize: 10, position: "right" },
          z: 20, tooltip: { formatter: (p) => `model: <b>${p.data.name}</b>` },
        });
      }
      chart.setOption({
        legend: { type: "scroll", top: 0, data: groups.map((g) => g.name) },
        grid: { left: 20, right: 20, top: 36, bottom: 20 },
        tooltip: {
          trigger: "item",
          formatter: (p) => p.seriesName === "models" ? `model: <b>${p.data.name}</b>`
            : `<b>${p.data.name}</b> · ${p.data.domain || "—"} · ${p.data.pc} picks<br/><span style="color:${COLORS.inkDim}">${(p.data.wiki || "").slice(0, 220)}…</span>`,
        },
        xAxis: { show: false, scale: true }, yAxis: { show: false, scale: true },
        dataZoom: SCATTER_ZOOM,
        series,
      }, true);
      chart.off("click");
      chart.on("click", (p) => { if (p.seriesName !== "models") openChar(ctx, p.data.name, p.data.wiki); });
    }

    colorBy.addEventListener("change", () => ctx.navigate("char_map", { color: colorBy.value, cent: centToggle.checked ? "1" : "" }));
    centToggle.addEventListener("change", draw);
    draw();
  },
};

async function openChar(ctx, name, wiki) {
  const pickers = await ctx.query(`
    SELECT m.label, COUNT(*) n FROM picks p JOIN responses r ON p.response_id=r.response_id
    JOIN models m USING(model_id) WHERE p.canonical=$c GROUP BY m.model_id ORDER BY n DESC LIMIT 25`, { $c: name });
  const a = await ctx.queryOne("SELECT alignment, role, nature FROM characters WHERE canonical=$c", { $c: name });
  const body = h("div", {}, [
    h("div", { class: "legend" }, [
      a?.alignment ? h("span", { class: "pill" }, "align: " + a.alignment) : null,
      a?.role ? h("span", { class: "pill" }, (a.role || "").replace(/_/g, " ")) : null,
      a?.nature ? h("span", { class: "pill" }, a.nature) : null,
    ]),
    wiki ? h("h4", {}, "Wikipedia") : null,
    wiki ? h("p", { class: "muted", style: { fontSize: "12.5px" } }, wiki) : null,
    h("h4", {}, "Picked by"),
    h("table", {}, [h("tbody", {}, pickers.map((p) => h("tr", {}, [h("td", {}, p.label), h("td", { class: "mono", style: { textAlign: "right" } }, p.n)])))]),
    h("div", { style: { marginTop: "16px" } }, h("button", { class: "btn hot", onclick: () => ctx.navigate("explorer", { character: name }) }, "see responses →")),
  ]);
  ctx.openInspector(name, body);
}
