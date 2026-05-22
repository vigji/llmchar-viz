import { h } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";

export default {
  id: "similarity",
  label: "Model similarity",
  lede: "How alike are two models' character picks? Cosine similarity of their pick-frequency vectors on the open-vocab sweep, ordered so behavioral families sit together.",
  async mount(ctx) {
    const order = await ctx.query(`SELECT c.model_id, m.label, c.order_idx, c.cluster_id FROM model_clusters c JOIN models m USING(model_id) ORDER BY c.order_idx`);
    const sim = await ctx.query("SELECT model_a, model_b, similarity FROM model_similarity");
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    if (!order.length) { view.append(h("p", { class: "note" }, "Similarity not built yet.")); ctx.el.append(view); return; }

    const labels = order.map((o) => o.label);
    const idx = Object.fromEntries(order.map((o, i) => [o.model_id, i]));
    const data = [];
    for (const s of sim) {
      if (idx[s.model_a] == null || idx[s.model_b] == null) continue;
      data.push([idx[s.model_a], idx[s.model_b], +s.similarity.toFixed(3)]);
    }
    const chartEl = h("div", { class: "chart tall card" });
    view.append(chartEl, h("p", { class: "note" }, "Click a cell to see the characters two models most share."));
    ctx.el.append(view);
    const chart = makeChart(chartEl);
    chart.setOption({
      grid: { left: 150, right: 30, top: 110, bottom: 20 },
      tooltip: { position: "top", formatter: (p) => `${labels[p.data[1]]} ↔ ${labels[p.data[0]]}<br/>similarity <b>${p.data[2]}</b>` },
      xAxis: { type: "category", data: labels, axisLabel: { rotate: 55, fontSize: 10, interval: 0 }, position: "top", splitArea: { show: true } },
      yAxis: { type: "category", data: labels, axisLabel: { fontSize: 10, interval: 0 }, splitArea: { show: true } },
      visualMap: { min: 0, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0,
        inRange: { color: ["#11141c", "#1c2230", COLORS.teal, COLORS.amber, COLORS.hot] }, textStyle: { color: COLORS.inkDim } },
      series: [{ type: "heatmap", data, emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 1 } } }],
    });
    chart.on("click", (p) => {
      const a = order[p.data[0]].model_id, b = order[p.data[1]].model_id;
      openShared(ctx, a, b, labels[p.data[0]], labels[p.data[1]]);
    });
  },
};

async function openShared(ctx, a, b, la, lb) {
  const rows = await ctx.query(`
    SELECT p.canonical, COUNT(DISTINCT r.response_id) n FROM picks p JOIN responses r ON p.response_id=r.response_id
    WHERE r.model_id IN ($a,$b) AND r.experiment='base_selfid_open'
      AND p.canonical IN (SELECT p2.canonical FROM picks p2 JOIN responses r2 ON p2.response_id=r2.response_id WHERE r2.model_id=$a)
      AND p.canonical IN (SELECT p3.canonical FROM picks p3 JOIN responses r3 ON p3.response_id=r3.response_id WHERE r3.model_id=$b)
    GROUP BY p.canonical ORDER BY n DESC LIMIT 20`, { $a: a, $b: b });
  const body = h("div", {}, [
    h("p", { class: "muted" }, `Characters picked by both ${la} and ${lb}:`),
    h("table", {}, [h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, [h("td", {}, r.canonical), h("td", { class: "mono", style: { textAlign: "right" } }, r.n)]))
      : [h("tr", {}, h("td", { class: "muted" }, "no shared picks"))])]),
  ]);
  ctx.openInspector(`${la} ↔ ${lb}`, body);
}
