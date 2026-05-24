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

export default {
  id: "picks",
  label: "Picks",
  lede: "The most-named characters — across all models or one. Filter by trait, color by trait, and click a bar for the reasons (one model) or which models named it (all).",
  async mount(ctx) {
    const models = await ctx.query(`
      SELECT m.model_id, m.label FROM models m
      WHERE EXISTS (SELECT 1 FROM responses r WHERE r.model_id=m.model_id AND r.experiment='base_selfid_open')
      ORDER BY m.label`);
    const modelMap = Object.fromEntries(models.map((m) => [m.model_id, m.label]));
    const st = ctx.state;
    const colorBy = TRAITS[st.color] ? st.color : "alignment";
    const model = st.model && modelMap[st.model] ? st.model : "";
    const f = { alignment: st.alignment || "", role: st.role || "", nature: st.nature || "" };

    const view = h("div", { class: "view" });
    view.append(h("h2", {}, "Picks"), h("p", { class: "lede" }, this.lede));

    const modelSel = select(models.map((m) => [m.model_id, m.label]), model, "all models");
    const alignSel = select(TRAITS.alignment.values.map((v) => [v, TRAITS.alignment.disp[v]]), f.alignment, "any");
    const roleSel = select(TRAITS.role.values.map((v) => [v, TRAITS.role.disp[v]]), f.role, "any");
    const natureSel = select(TRAITS.nature.values.map((v) => [v, TRAITS.nature.disp[v]]), f.nature, "any");
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

      const m = modelSel.value;
      const where = ["r.experiment='base_selfid_open'"]; const p = {};
      if (m) { where.push("r.model_id=$m"); p.$m = m; }
      if (alignSel.value) { where.push("c.alignment=$al"); p.$al = alignSel.value; }
      if (roleSel.value) { where.push("c.role=$ro"); p.$ro = roleSel.value; }
      if (natureSel.value) { where.push("c.nature=$na"); p.$na = natureSel.value; }
      const lim = m ? "" : "LIMIT 80";
      const rows = await ctx.query(`
        SELECT p.canonical AS name, c.alignment, c.role, c.nature, COUNT(DISTINCT p.response_id) AS n
        FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN characters c ON c.canonical=p.canonical
        WHERE ${where.join(" AND ")} GROUP BY p.canonical ORDER BY n DESC ${lim}`, p);

      const td = (ax, v) => v ? (v === "na" ? "unaligned" : TRAITS[ax].disp[v]) : "";
      const traits = [td("alignment", alignSel.value), td("role", roleSel.value), td("nature", natureSel.value)].filter(Boolean).join(" ");
      heading.textContent = (m
        ? `${modelMap[m]}'s top ${traits} picks`
        : `Top ${traits} picks across models`).replace(/ {2,}/g, " ");

      if (!rows.length) { chart.clear(); note.textContent = "no matches"; return; }

      const cb = colorSel.value;
      const data = rows.slice().reverse();
      const windowCount = Math.min(22, data.length);
      const startPct = data.length > windowCount ? 100 * (1 - windowCount / data.length) : 0;

      let xLabel, max, denom = 0;
      if (m) {
        denom = (await ctx.queryOne("SELECT COUNT(*) n FROM responses WHERE model_id=$m AND experiment='base_selfid_open'", { $m: m })).n || 1;
        xLabel = "pick rate (%)"; max = denom;
        note.textContent = `${rows.length} distinct characters across ${denom} answers — scroll within the chart for the full list`;
      } else {
        xLabel = "picks (all models)"; max = Math.max(...rows.map((r) => r.n));
        note.textContent = `top ${rows.length} characters — scroll within the chart`;
      }

      chart.setOption({
        grid: { left: 168, right: 40, top: 12, bottom: 26 },
        tooltip: { trigger: "item", formatter: (q) => m
          ? `<b>${q.name}</b><br/>${(100 * q.value / denom).toFixed(1)}% · ${q.value}/${denom}<br/><span style="color:${COLORS.inkFaint}">click for rationales</span>`
          : `<b>${q.name}</b> · ${q.value} picks<br/><span style="color:${COLORS.inkFaint}">click to see which models</span>` },
        xAxis: { type: "value", max, name: xLabel, nameLocation: "middle", nameGap: 30,
          axisLabel: m ? { formatter: (v) => (100 * v / denom).toFixed(0) } : {} },
        yAxis: { type: "category", data: data.map((d) => d.name), axisLabel: { fontSize: 11, width: 156, overflow: "truncate" } },
        dataZoom: data.length > windowCount ? [
          { type: "slider", yAxisIndex: 0, start: startPct, end: 100, width: 14, right: 6, zoomLock: true, brushSelect: false },
          { type: "inside", yAxisIndex: 0, start: startPct, end: 100, zoomLock: true, zoomOnMouseWheel: false, moveOnMouseWheel: true, moveOnMouseMove: true },
        ] : [],
        series: [{ type: "bar", barMaxWidth: 16, data: data.map((d) => ({ value: d.n, name: d.name,
          itemStyle: { color: traitColor(cb, d[cb]), borderRadius: [0, 3, 3, 0] } })) }],
      }, true);

      chart.off("click");
      chart.on("click", (q) => m ? openRationales(ctx, m, modelMap[m], q.name) : openWho(ctx, q.name));
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
