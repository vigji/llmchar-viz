import { h, opt } from "../lib/dom.js";
import { makeChart, PALETTE, COLORS } from "../lib/charts.js";

export default {
  id: "char_map",
  label: "Character map",
  lede: "Every named character placed by the meaning of its Wikipedia page. Nearby characters are semantically similar; point size is how often models pick them.",
  async mount(ctx) {
    const chars = await ctx.query(`
      SELECT canonical AS name, char_umap_x AS x, char_umap_y AS y, char_cluster_id AS cl,
             domain, real_or_fictional AS rf, pick_count AS pc, substr(wiki_summary,1,500) AS wiki
      FROM characters WHERE char_umap_x IS NOT NULL`);
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    if (chars.length < 5) {
      view.append(h("p", { class: "note" }, "Character embeddings not built yet (run `make db`)."));
      ctx.el.append(view); return;
    }

    const colorBy = h("select", {}, [["cl", "cluster"], ["domain", "domain"], ["rf", "real / fictional"]].map(([v, l]) => opt(v, l, (ctx.state.color || "cl") === v)));
    const centToggle = h("input", { type: "checkbox" });
    if (ctx.state.cent === "1") centToggle.checked = true;
    const view_toolbar = h("div", { class: "toolbar" }, [
      h("label", { class: "field" }, ["color by", colorBy]),
      h("label", { class: "field", style: { flexDirection: "row", alignItems: "center", gap: "6px", textTransform: "none" } }, [centToggle, "overlay model centroids"]),
    ]);
    view.append(view_toolbar);
    const chartEl = h("div", { class: "chart tall card" });
    view.append(chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    const cents = await ctx.query(`SELECT m.label, c.umap_x AS x, c.umap_y AS y FROM model_centroids c JOIN models m USING(model_id) WHERE c.space='character'`);
    const maxpc = Math.max(...chars.map((c) => c.pc || 1));
    const size = (pc) => 6 + 22 * Math.sqrt((pc || 1) / maxpc);

    function groupKey(c, by) {
      if (by === "cl") return c.cl === -1 || c.cl == null ? "unclustered" : "cluster " + c.cl;
      if (by === "domain") return c.domain || "—";
      return c.rf || "unsure";
    }

    function draw() {
      const by = colorBy.value;
      const groups = {};
      for (const c of chars) (groups[groupKey(c, by)] ||= []).push(c);
      const names = Object.keys(groups).sort();
      const series = names.map((nm, i) => ({
        name: nm, type: "scatter",
        data: groups[nm].map((c) => ({ value: [c.x, c.y, c.pc], name: c.name, wiki: c.wiki, domain: c.domain, pc: c.pc })),
        symbolSize: (val) => size(val[2]),
        itemStyle: { color: PALETTE[i % PALETTE.length], opacity: 0.82, borderColor: "rgba(0,0,0,.3)", borderWidth: 0.5 },
        emphasis: { focus: "series", scale: 1.3 },
      }));
      if (centToggle.checked) {
        series.push({
          name: "models", type: "scatter",
          data: cents.map((c) => ({ value: [c.x, c.y], name: c.label })),
          symbol: "diamond", symbolSize: 16,
          itemStyle: { color: COLORS.hot, borderColor: "#000", borderWidth: 1 },
          label: { show: true, formatter: (p) => p.data.name, color: COLORS.ink, fontSize: 10, position: "right" },
          z: 20, tooltip: { formatter: (p) => `model: <b>${p.data.name}</b>` },
        });
      }
      chart.setOption({
        legend: { type: "scroll", top: 0, data: names },
        grid: { left: 20, right: 20, top: 36, bottom: 20 },
        tooltip: {
          trigger: "item",
          formatter: (p) => p.seriesName === "models" ? `model: <b>${p.data.name}</b>`
            : `<b>${p.data.name}</b> · ${p.data.domain || "—"} · ${p.data.pc} picks<br/><span style="color:${COLORS.inkDim}">${(p.data.wiki || "").slice(0, 220)}…</span>`,
        },
        xAxis: { show: false, scale: true }, yAxis: { show: false, scale: true },
        series,
      }, true);
      chart.off("click");
      chart.on("click", (p) => { if (p.seriesName !== "models") openChar(ctx, p.data.name, p.data.wiki); });
    }

    colorBy.addEventListener("change", () => { ctx.navigate("char_map", { color: colorBy.value, cent: centToggle.checked ? "1" : "" }); });
    centToggle.addEventListener("change", draw);
    draw();
  },
};

async function openChar(ctx, name, wiki) {
  const pickers = await ctx.query(`
    SELECT m.label, COUNT(*) n FROM picks p JOIN responses r ON p.response_id=r.response_id
    JOIN models m USING(model_id) WHERE p.canonical=$c GROUP BY m.model_id ORDER BY n DESC LIMIT 25`, { $c: name });
  const body = h("div", {}, [
    wiki ? h("h4", {}, "Wikipedia") : null,
    wiki ? h("p", { class: "muted", style: { fontSize: "12.5px" } }, wiki) : null,
    h("h4", {}, "Picked by"),
    h("table", {}, [h("tbody", {}, pickers.map((p) => h("tr", {}, [h("td", {}, p.label), h("td", { class: "mono", style: { textAlign: "right" } }, p.n)])))]),
    h("div", { style: { marginTop: "16px" } }, h("button", { class: "btn hot", onclick: () => ctx.navigate("explorer", { character: name }) }, "see responses →")),
  ]);
  ctx.openInspector(name, body);
}
