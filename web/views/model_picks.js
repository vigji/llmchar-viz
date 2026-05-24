import { h, clear, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";

const ALIGN_COLOR = { good: COLORS.production, gray: COLORS.minimal, evil: COLORS.hot, na: "#a39a8c" };
const ALIGN_LABEL = { good: "good", gray: "morally gray", evil: "evil", na: "n/a" };

export default {
  id: "model_picks",
  label: "Model picks",
  lede: "Each model's most-named characters on the open-vocab question. Bars are colored by moral alignment; click one to read that model's reasons for the pick.",
  async mount(ctx) {
    const models = await ctx.query(`
      SELECT m.model_id, m.label FROM models m
      WHERE EXISTS (SELECT 1 FROM responses r WHERE r.model_id=m.model_id AND r.experiment='base_selfid_open')
      ORDER BY m.label`);
    const cur = ctx.state.model && models.find((m) => m.model_id === ctx.state.model)
      ? ctx.state.model
      : (models.find((m) => m.model_id.includes("ministral-8b")) || models[0]).model_id;

    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    const sel = h("select", {}, models.map((m) => opt(m.model_id, m.label, m.model_id === cur)));
    view.append(h("div", { class: "toolbar" }, [h("label", { class: "field" }, ["model", sel])]));
    view.append(h("div", { class: "legend" }, Object.entries(ALIGN_LABEL).map(([k, v]) =>
      h("span", {}, [h("i", { style: { background: ALIGN_COLOR[k] } }), v]))));
    const note = h("div", { class: "note" });
    const chartEl = h("div", { class: "chart tall card" });
    view.append(note, chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    async function draw() {
      const m = sel.value;
      const denom = (await ctx.queryOne(
        "SELECT COUNT(*) n FROM responses WHERE model_id=$m AND experiment='base_selfid_open'", { $m: m })).n || 1;
      const rows = await ctx.query(`
        SELECT p.canonical AS name, c.alignment AS al, COUNT(DISTINCT p.response_id) AS n
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        JOIN characters c ON c.canonical=p.canonical
        WHERE r.model_id=$m AND r.experiment='base_selfid_open'
        GROUP BY p.canonical ORDER BY n DESC`, { $m: m });
      note.textContent = `${rows.length} distinct characters across ${denom} answers — scroll within the chart for the full list`;

      // ascending so the most-picked sits at the top with yAxis inverse
      const data = rows.slice().reverse();
      const windowCount = Math.min(22, data.length);
      const startPct = data.length > windowCount ? 100 * (1 - windowCount / data.length) : 0;

      chart.setOption({
        grid: { left: 160, right: 40, top: 12, bottom: 24 },
        tooltip: { trigger: "item", formatter: (p) => `<b>${p.name}</b><br/>${(100 * p.value / denom).toFixed(1)}% · ${p.value}/${denom}<br/><span style="color:${COLORS.inkFaint}">click for rationales</span>` },
        xAxis: { type: "value", name: "pick rate (%)", nameLocation: "middle", nameGap: 30,
          axisLabel: { formatter: (v) => (100 * v / denom).toFixed(0) } },
        yAxis: { type: "category", data: data.map((d) => d.name), axisLabel: { fontSize: 11, width: 150, overflow: "truncate" } },
        dataZoom: [
          { type: "slider", yAxisIndex: 0, start: startPct, end: 100, width: 14, right: 6 },
          { type: "inside", yAxisIndex: 0, start: startPct, end: 100 },
        ],
        series: [{
          type: "bar", data: data.map((d) => ({ value: d.n, name: d.name,
            itemStyle: { color: ALIGN_COLOR[d.al] || ALIGN_COLOR.na, borderRadius: [0, 3, 3, 0] } })),
          barMaxWidth: 16,
        }],
      }, true);

      chart.off("click");
      chart.on("click", (p) => openRationales(ctx, m, sel.options[sel.selectedIndex].text, p.name));
    }
    sel.addEventListener("change", () => ctx.navigate("model_picks", { model: sel.value }));
    draw();
  },
};

async function openRationales(ctx, model_id, modelLabel, canonical) {
  const rows = await ctx.query(`
    SELECT p.explanation AS ex, p.rank AS rk, r.temperature AS t
    FROM picks p JOIN responses r ON p.response_id=r.response_id
    WHERE r.model_id=$m AND p.canonical=$c AND r.experiment='base_selfid_open'
      AND p.explanation IS NOT NULL AND trim(p.explanation) <> ''
    ORDER BY p.rank LIMIT 80`, { $m: model_id, $c: canonical });
  const al = await ctx.queryOne("SELECT alignment, role, nature FROM characters WHERE canonical=$c", { $c: canonical });
  const body = h("div", {}, [
    h("div", { class: "legend" }, [
      al?.alignment ? h("span", { class: "pill" }, "align: " + al.alignment) : null,
      al?.role ? h("span", { class: "pill" }, (al.role || "").replace(/_/g, " ")) : null,
      al?.nature ? h("span", { class: "pill" }, al.nature) : null,
    ]),
    h("p", { class: "muted", style: { fontSize: "13px" } }, `${modelLabel} · ${rows.length} rationale${rows.length === 1 ? "" : "s"}`),
    ...rows.map((r) => h("div", { class: "pick-row" }, [
      h("span", { class: "rk" }, "#" + r.rk),
      h("div", { class: "ex" }, r.ex),
    ])),
    rows.length ? null : h("p", { class: "muted" }, "no rationales recorded"),
    h("div", { style: { marginTop: "14px" } }, h("button", { class: "btn", onclick: () => ctx.navigate("explorer", { model: model_id, character: canonical }) }, "see full responses →")),
  ]);
  ctx.openInspector(canonical, body);
}
