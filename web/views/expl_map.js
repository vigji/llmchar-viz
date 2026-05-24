import { h, opt } from "../lib/dom.js";
import { makeChart, PALETTE, COLORS } from "../lib/charts.js";

export default {
  id: "expl_map",
  label: "Explanation map",
  lede: "Every reason a model gave for a pick, placed by meaning. Clusters are shared ways of explaining identification; toggle to see each model's centroid.",
  async mount(ctx) {
    const rows = await ctx.query(`
      SELECT p.expl_umap_x AS x, p.expl_umap_y AS y, p.expl_cluster_id AS cl,
             m.family, m.label AS model, p.canonical, substr(p.explanation,1,160) AS ex
      FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN models m USING(model_id)
      WHERE p.expl_umap_x IS NOT NULL`);
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    if (rows.length < 10) {
      view.append(h("p", { class: "note" }, "Explanation embeddings not built yet (run `make db`).")); ctx.el.append(view); return;
    }

    const colorBy = h("select", {}, [["family", "model family"], ["cl", "cluster"]].map(([v, l]) => opt(v, l, (ctx.state.color || "family") === v)));
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
    const cents = await ctx.query(`SELECT m.label, c.umap_x AS x, c.umap_y AS y FROM model_centroids c JOIN models m USING(model_id) WHERE c.space='explanation'`);

    function gkey(r, by) { return by === "family" ? (r.family || "—") : (r.cl === -1 || r.cl == null ? "noise" : "cluster " + r.cl); }

    function draw() {
      const by = colorBy.value;
      const groups = {};
      for (const r of rows) (groups[gkey(r, by)] ||= []).push(r);
      const names = Object.keys(groups).sort();
      const series = names.map((nm, i) => ({
        name: nm, type: "scatter", large: true, largeThreshold: 2000, progressive: 4000,
        data: groups[nm].map((r) => ({ value: [r.x, r.y], ex: r.ex, canonical: r.canonical, model: r.model })),
        symbolSize: 5,
        itemStyle: { color: nm === "noise" ? "#cabfae" : PALETTE[i % PALETTE.length], opacity: 0.6 },
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
        legend: { type: "scroll", top: 0, data: names },
        grid: { left: 20, right: 20, top: 36, bottom: 20 },
        tooltip: {
          trigger: "item", confine: true,
          formatter: (p) => p.seriesName === "models" ? `model: <b>${p.data.name}</b>`
            : `<b>${p.data.canonical}</b> · ${p.data.model}<br/><span style="color:${COLORS.inkDim}">${p.data.ex || ""}</span>`,
        },
        xAxis: { show: false, scale: true }, yAxis: { show: false, scale: true },
        series,
      }, true);
    }
    colorBy.addEventListener("change", () => ctx.navigate("expl_map", { color: colorBy.value, cent: centToggle.checked ? "1" : "" }));
    centToggle.addEventListener("change", draw);
    draw();
  },
};
