import { h, clear, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";

const ORDER = ["bare", "minimal", "production"];
const EXP_LABEL = {
  prodbare_selfid_open: "5-character task (v1)",
  phase0_selfid_single: "1-character task",
};

export default {
  id: "prodbare",
  label: "Prod vs bare",
  lede: "The same self-identification question, asked with no system prompt (bare) vs the model's real deployed system prompt (production). Watch the dark picks collapse.",
  async mount(ctx) {
    const combos = await ctx.query(`
      SELECT DISTINCT f.model_id, f.experiment, m.label
      FROM pick_freq_by_condition f JOIN models m USING(model_id)
      WHERE f.condition='production' ORDER BY m.label`);
    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));

    if (!combos.length) {
      view.append(h("p", { class: "note" }, "No production-condition data yet (prod-vs-bare runs still generating)."));
      ctx.el.append(view);
      return;
    }

    const key = (c) => `${c.model_id}::${c.experiment}`;
    // prefer the clean apples-to-apples 5-char run (bare vs production) for Ministral
    const def = combos.find((c) => c.experiment === "prodbare_selfid_open" && c.model_id.includes("ministral"))
      || combos.find((c) => c.experiment === "prodbare_selfid_open")
      || combos.find((c) => c.model_id.includes("ministral")) || combos[0];
    const cur = ctx.state.combo && combos.find((c) => key(c) === ctx.state.combo)
      ? ctx.state.combo : key(def);

    const sel = h("select", { id: "pb-combo" });
    for (const c of combos) sel.append(opt(key(c), `${c.label} — ${EXP_LABEL[c.experiment] || c.experiment}`, key(c) === cur));
    const allToggle = h("label", { class: "field" }, ["characters", (() => {
      const s = h("select", { id: "pb-top" });
      [["12", "top 12 by pick rate"], ["0", "all characters"]].forEach(([v, l]) => s.append(opt(v, l, (ctx.state.top || "12") === v)));
      return s;
    })()]);
    view.append(h("div", { class: "toolbar" }, [h("label", { class: "field" }, ["model · task", sel]), allToggle]));

    const kpis = h("div", { class: "kpis" });
    const chartEl = h("div", { class: "chart tall card" });
    const legend = h("div", { class: "legend" }, [
      h("span", {}, [h("i", { style: { background: COLORS.bare } }), "bare"]),
      h("span", {}, [h("i", { style: { background: COLORS.minimal } }), "minimal"]),
      h("span", {}, [h("i", { style: { background: COLORS.production } }), "production"]),
      h("span", { class: "muted" }, "— the biggest faller is highlighted; click a line to inspect it"),
    ]);
    view.append(kpis, chartEl, legend);
    ctx.el.append(view);

    const chart = makeChart(chartEl);

    async function draw() {
      const [model_id, experiment] = (sel.value).split("::");
      const topN = parseInt(document.getElementById("pb-top").value, 10);
      const rows = await ctx.query(`
        SELECT canonical,
          MAX(CASE WHEN condition='bare' THEN freq END) AS bare,
          MAX(CASE WHEN condition='minimal' THEN freq END) AS minimal,
          MAX(CASE WHEN condition='production' THEN freq END) AS production
        FROM pick_freq_by_condition WHERE model_id=$m AND experiment=$e
        GROUP BY canonical`, { $m: model_id, $e: experiment });

      const present = ORDER.filter((c) => rows.some((r) => r[c] != null));
      // rank by biggest absolute fall from first->last present condition
      const first = present[0], last = present[present.length - 1];
      rows.forEach((r) => { r._fall = (r[first] || 0) - (r[last] || 0); r._peak = Math.max(r.bare || 0, r.minimal || 0, r.production || 0); });
      rows.sort((a, b) => b._peak - a._peak);
      const shown = topN ? rows.slice(0, topN) : rows;
      const dropper = [...rows].sort((a, b) => b._fall - a._fall)[0];

      // KPIs for the headline faller
      clear(kpis);
      if (dropper && dropper._fall > 0) {
        const supp = (dropper[last] > 0) ? (dropper[first] / dropper[last]).toFixed(1) + "×" : "→ 0";
        kpis.append(
          kpi(dropper.canonical, "biggest faller"),
          kpi(pct(dropper[first]), `${first} pick-rate`),
          kpi(pct(dropper[last]), `${last} pick-rate`),
          kpi(supp, "suppression", true),
        );
      }

      const series = shown.map((r) => {
        const isDrop = dropper && r.canonical === dropper.canonical;
        return {
          name: r.canonical, type: "line", smooth: false,
          data: present.map((c) => (r[c] == null ? null : +(r[c] * 100).toFixed(2))),
          connectNulls: true,
          symbol: "circle", symbolSize: isDrop ? 9 : 5,
          lineStyle: { width: isDrop ? 3.5 : 1, color: isDrop ? COLORS.hot : undefined, opacity: isDrop ? 1 : 0.5 },
          itemStyle: { color: isDrop ? COLORS.hot : undefined },
          emphasis: { focus: "series" },
          z: isDrop ? 10 : 1,
          endLabel: { show: isDrop, color: COLORS.hot, formatter: r.canonical, fontWeight: 700 },
        };
      });

      chart.setOption({
        grid: { left: 64, right: 150, top: 24, bottom: 40 },
        tooltip: { trigger: "item", formatter: (p) => `${p.seriesName}<br/>${p.name}: <b>${p.value ?? "—"}%</b>` },
        xAxis: { type: "category", data: present, boundaryGap: false, axisLabel: { fontSize: 13 } },
        yAxis: { type: "value", name: "pick rate (%)", nameLocation: "middle", nameGap: 44 },
        series,
      }, true);

      chart.off("click");
      chart.on("click", (p) => ctx.navigate("explorer", { experiment, model: model_id, character: p.seriesName }));
    }

    sel.addEventListener("change", () => { ctx.navigate("prodbare", { combo: sel.value, top: document.getElementById("pb-top").value }); });
    document.getElementById("pb-top").addEventListener("change", draw);
    draw();
  },
};

function pct(x) { return x == null ? "—" : (x * 100).toFixed(1) + "%"; }
function kpi(v, k, hot) {
  return h("div", { class: "kpi" }, [
    h("div", { class: "v", html: hot ? `<span class="unit">${v}</span>` : String(v) }),
    h("div", { class: "k" }, k),
  ]);
}
