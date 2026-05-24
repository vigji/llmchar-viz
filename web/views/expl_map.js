import { h, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";
import { groupPoints, SCATTER_ZOOM } from "../lib/coloring.js";

const COLOR_OPTS = [["family", "model family"], ["alignment", "alignment"], ["role", "role"], ["nature", "nature"], ["cl", "cluster"]];
const GET = { family: (r) => r.family, alignment: (r) => r.alignment, role: (r) => r.role, nature: (r) => r.nature, cl: (r) => r.cl };

export default {
  id: "expl_map",
  label: "Explanation map",
  lede: "Every reason a model gave for a pick, placed by meaning. Clusters are shared ways of explaining identification. Scroll to zoom, drag to pan.",
  async mount(ctx) {
    const rows = await ctx.query(`
      SELECT p.expl_umap_x AS x, p.expl_umap_y AS y, p.expl_cluster_id AS cl,
             m.family, m.label AS model, p.canonical, c.alignment, c.role, c.nature,
             substr(p.explanation,1,160) AS ex
      FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN models m USING(model_id)
      JOIN characters c ON c.canonical=p.canonical
      WHERE p.expl_umap_x IS NOT NULL`);
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    if (rows.length < 10) {
      view.append(h("p", { class: "note" }, "Explanation embeddings not built yet (run `make db`).")); ctx.el.append(view); return;
    }

    const colorBy = h("select", {}, COLOR_OPTS.map(([v, l]) => opt(v, l, (ctx.state.color || "family") === v)));
    const centToggle = h("input", { type: "checkbox" });
    if (ctx.state.cent === "1") centToggle.checked = true;
    view.append(h("div", { class: "toolbar" }, [
      h("label", { class: "field" }, ["color by", colorBy]),
      h("label", { class: "field", style: { flexDirection: "row", alignItems: "center", gap: "6px", textTransform: "none" } }, [centToggle, "overlay model centroids"]),
      h("span", { class: "note" }, `${rows.length.toLocaleString()} explanations`),
    ]));
    const chartEl = h("div", { class: "chart tall card" });
    view.append(chartEl); ctx.el.append(view);
    const chart = makeChart(chartEl);
    const cents = await ctx.query("SELECT m.label, c.umap_x AS x, c.umap_y AS y FROM model_centroids c JOIN models m USING(model_id) WHERE c.space='explanation'");

    function draw() {
      const by = colorBy.value;
      const groups = groupPoints(rows, by, GET[by]);
      const series = groups.map((g) => ({
        name: g.name, type: "scatter", large: true, largeThreshold: 2000, progressive: 4000,
        data: g.items.map((r) => ({ value: [r.x, r.y], ex: r.ex, canonical: r.canonical, model: r.model })),
        symbolSize: 5, itemStyle: { color: g.color, opacity: 0.6 },
      }));
      if (centToggle.checked) {
        series.push({
          name: "models", type: "scatter",
          data: cents.map((c) => ({ value: [c.x, c.y], name: c.label })),
          symbol: "diamond", symbolSize: 16, z: 20,
          itemStyle: { color: COLORS.hot, borderColor: "#3d2b1f", borderWidth: 1 },
          label: { show: true, formatter: (p) => p.data.name, color: COLORS.ink, fontSize: 10, position: "right" },
        });
      }
      chart.setOption({
        legend: { type: "scroll", top: 0, data: groups.map((g) => g.name) },
        grid: { left: 20, right: 20, top: 36, bottom: 20 },
        tooltip: {
          trigger: "item", confine: true,
          formatter: (p) => p.seriesName === "models" ? `model: <b>${p.data.name}</b>`
            : `<b>${p.data.canonical}</b> · ${p.data.model}<br/><span style="color:${COLORS.inkDim}">${p.data.ex || ""}</span>`,
        },
        xAxis: { show: false, scale: true }, yAxis: { show: false, scale: true },
        dataZoom: SCATTER_ZOOM,
        series,
      }, true);
    }
    colorBy.addEventListener("change", () => ctx.navigate("expl_map", { color: colorBy.value, cent: centToggle.checked ? "1" : "" }));
    centToggle.addEventListener("change", draw);
    draw();
  },
};
