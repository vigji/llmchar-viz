import { h, opt } from "../lib/dom.js";
import { makeChart, COLORS, PALETTE } from "../lib/charts.js";

// axis -> ordered categories, colors, default sort key, display labels
const AXES = {
  alignment: {
    label: "moral alignment",
    values: ["evil", "gray", "good", "na"],
    colors: { evil: COLORS.hot, gray: COLORS.minimal, good: COLORS.production, na: "#cabfae" },
    disp: { evil: "evil", gray: "morally gray", good: "good", na: "n/a" },
    sortBy: "evil",
  },
  expertise: {
    label: "expertise / archetype",
    values: ["science", "arts_letters", "polymath", "leadership", "other"],
    colors: { science: COLORS.hot, arts_letters: PALETTE[1], polymath: PALETTE[2], leadership: PALETTE[3], other: "#cabfae" },
    disp: { science: "science", arts_letters: "arts & letters", polymath: "polymath", leadership: "leadership", other: "other" },
    sortBy: "science",
  },
  nature: {
    label: "nature",
    values: ["artificial", "nonhuman", "abstract", "human"],
    colors: { artificial: COLORS.hot, nonhuman: PALETTE[0], abstract: PALETTE[2], human: "#cabfae" },
    disp: { artificial: "artificial", nonhuman: "nonhuman", abstract: "abstract", human: "human" },
    sortBy: "artificial",
  },
};

export default {
  id: "char_features",
  label: "Character features",
  lede: "Do models identify with different kinds of characters? Each bar is one model's picks, split by a character trait. Sorted to surface who leans toward the highlighted trait.",
  async mount(ctx) {
    const axisKey = AXES[ctx.state.axis] ? ctx.state.axis : "alignment";
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    const sel = h("select", {}, Object.entries(AXES).map(([k, a]) => opt(k, a.label, k === axisKey)));
    view.append(h("div", { class: "toolbar" }, [h("label", { class: "field" }, ["split by", sel])]));
    const legend = h("div", { class: "legend" });
    const chartEl = h("div", { class: "chart tall card" });
    view.append(legend, chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    async function draw() {
      const ax = AXES[sel.value];
      const col = sel.value; // whitelisted via AXES key
      const rows = await ctx.query(`
        SELECT m.label AS model, c.${col} AS cat, COUNT(*) AS n
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        JOIN characters c ON c.canonical=p.canonical
        JOIN models m ON m.model_id=r.model_id
        WHERE r.experiment='base_selfid_open' AND c.${col} IS NOT NULL
        GROUP BY m.label, c.${col}`);
      // pivot -> per model fractions
      const byModel = {};
      for (const r of rows) {
        const mm = (byModel[r.model] ||= { total: 0 });
        mm[r.cat] = (mm[r.cat] || 0) + r.n;
        mm.total += r.n;
      }
      const models = Object.keys(byModel)
        .sort((a, b) => (byModel[a][ax.sortBy] || 0) / byModel[a].total - (byModel[b][ax.sortBy] || 0) / byModel[b].total);

      legend.replaceChildren(...ax.values.map((v) =>
        h("span", {}, [h("i", { style: { background: ax.colors[v] } }), ax.disp[v]])));

      const series = ax.values.map((v) => ({
        name: ax.disp[v], type: "bar", stack: "x",
        emphasis: { focus: "series" },
        itemStyle: { color: ax.colors[v] },
        data: models.map((m) => +(100 * (byModel[m][v] || 0) / byModel[m].total).toFixed(1)),
      }));

      chart.setOption({
        legend: { show: false },
        grid: { left: 150, right: 30, top: 10, bottom: 30 },
        tooltip: { trigger: "item", formatter: (p) => `${p.seriesName}<br/><b>${p.value}%</b> of ${p.name}'s picks` },
        xAxis: { type: "value", max: 100, name: "share of picks (%)", nameLocation: "middle", nameGap: 28 },
        yAxis: { type: "category", data: models, axisLabel: { fontSize: 11 } },
        series,
      }, true);

      chart.off("click");
      chart.on("click", (p) => openCat(ctx, p.name, col, ax, p.seriesName));
    }
    sel.addEventListener("change", () => ctx.navigate("char_features", { axis: sel.value }));
    draw();
  },
};

async function openCat(ctx, modelLabel, col, ax, dispVal) {
  const cat = Object.keys(ax.disp).find((k) => ax.disp[k] === dispVal);
  const rows = await ctx.query(`
    SELECT p.canonical AS name, COUNT(DISTINCT p.response_id) AS n
    FROM picks p JOIN responses r ON p.response_id=r.response_id
    JOIN characters c ON c.canonical=p.canonical JOIN models m ON m.model_id=r.model_id
    WHERE r.experiment='base_selfid_open' AND m.label=$m AND c.${col}=$cat
    GROUP BY p.canonical ORDER BY n DESC LIMIT 40`, { $m: modelLabel, $cat: cat });
  const body = h("div", {}, [
    h("p", { class: "muted" }, `${modelLabel} — ${dispVal} picks:`),
    h("table", {}, [h("tbody", {}, rows.length
      ? rows.map((r) => h("tr", {}, [h("td", {}, r.name), h("td", { class: "mono", style: { textAlign: "right" } }, r.n)]))
      : [h("tr", {}, h("td", { class: "muted" }, "none"))])]),
  ]);
  ctx.openInspector(`${modelLabel} · ${dispVal}`, body);
}
