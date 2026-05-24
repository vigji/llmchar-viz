import { h, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";
import { TRAITS, traitColor } from "../lib/traits.js";

const MODES = { model: "by model", trait: "by trait" };

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
  lede: "",
  async mount(ctx) {
    const models = await ctx.query(`
      SELECT m.model_id, m.label FROM models m
      WHERE EXISTS (SELECT 1 FROM responses r WHERE r.model_id=m.model_id AND r.experiment='base_selfid_open')
      ORDER BY m.label`);
    const modelMap = Object.fromEntries(models.map((m) => [m.model_id, m.label]));
    const st = ctx.state;
    const mode = MODES[st.mode] ? st.mode : "model";
    const colorBy = TRAITS[st.color] ? st.color : "alignment";
    const defModel = (models.find((m) => m.model_id.includes("ministral-8b")) || models[0]).model_id;
    const model = st.model !== undefined && (st.model === "" || modelMap[st.model])
      ? st.model : (mode === "model" ? defModel : "");
    const f = { alignment: st.alignment || "", role: st.role || "", nature: st.nature || "" };

    const view = h("div", { class: "view" });
    view.append(h("h2", {}, "Picks"),
      h("p", { class: "lede" }, mode === "model"
        ? "A single model's most-named characters; bars colored by a character trait, click one for that model's reasons."
        : "Leaderboards of the most-named characters filtered by trait — across all models or one. Combine alignment, role and nature."));

    const modeSel = select(Object.entries(MODES), mode);
    const colorSel = select(Object.entries(TRAITS).map(([k, t]) => [k, t.label]), colorBy);
    const modelPairs = models.map((m) => [m.model_id, m.label]);
    const modelSel = mode === "model"
      ? select(modelPairs, model || defModel)
      : select(modelPairs, model, "all models");
    const ctrls = [field("mode", modeSel), field("model", modelSel)];
    let alignSel, roleSel, natureSel;
    if (mode === "trait") {
      alignSel = select(TRAITS.alignment.values.map((v) => [v, TRAITS.alignment.disp[v]]), f.alignment, "any");
      roleSel = select(TRAITS.role.values.map((v) => [v, TRAITS.role.disp[v]]), f.role, "any");
      natureSel = select(TRAITS.nature.values.map((v) => [v, TRAITS.nature.disp[v]]), f.nature, "any");
      ctrls.push(field("alignment", alignSel), field("role", roleSel), field("nature", natureSel));
    }
    ctrls.push(field("color by", colorSel));
    view.append(h("div", { class: "toolbar" }, ctrls));

    const legend = h("div", { class: "legend" });
    const heading = h("div", { style: { fontFamily: "var(--serif)", fontSize: "18px", fontWeight: "700", margin: "2px 0 8px" } });
    const note = h("div", { class: "note" });
    const chartEl = h("div", { class: "chart tall card" });
    view.append(heading, legend, note, chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    function nav() {
      ctx.navigate("picks", {
        mode, color: colorSel.value, model: modelSel.value,
        alignment: alignSel ? alignSel.value : "", role: roleSel ? roleSel.value : "", nature: natureSel ? natureSel.value : "",
      });
    }
    modeSel.addEventListener("change", () => ctx.navigate("picks", { mode: modeSel.value, color: colorSel.value }));
    [modelSel, colorSel, alignSel, roleSel, natureSel].forEach((s) => s && s.addEventListener("change", nav));

    function paintLegend() {
      const t = TRAITS[colorSel.value];
      legend.replaceChildren(...t.values.map((v) => h("span", {}, [h("i", { style: { background: t.colors[v] } }), t.disp[v]])));
    }

    function renderBars(data, { xLabel, xFmt, max }) {
      const cb = colorSel.value;
      const windowCount = Math.min(22, data.length);
      const startPct = data.length > windowCount ? 100 * (1 - windowCount / data.length) : 0;
      chart.setOption({
        grid: { left: 168, right: 40, top: 12, bottom: 26 },
        tooltip: { trigger: "item", formatter: xFmt },
        xAxis: { type: "value", max, name: xLabel, nameLocation: "middle", nameGap: 30,
          axisLabel: xLabel.includes("%") ? { formatter: (v) => (100 * v / max).toFixed(0) } : {} },
        yAxis: { type: "category", data: data.map((d) => d.name), axisLabel: { fontSize: 11, width: 156, overflow: "truncate" } },
        dataZoom: data.length > windowCount ? [
          { type: "slider", yAxisIndex: 0, start: startPct, end: 100, width: 14, right: 6, zoomLock: true, brushSelect: false },
          { type: "inside", yAxisIndex: 0, start: startPct, end: 100, zoomLock: true, zoomOnMouseWheel: false, moveOnMouseWheel: true, moveOnMouseMove: true },
        ] : [],
        series: [{ type: "bar", barMaxWidth: 16, data: data.map((d) => ({ value: d.n, name: d.name,
          itemStyle: { color: traitColor(cb, d[cb]), borderRadius: [0, 3, 3, 0] } })) }],
      }, true);
    }

    async function draw() {
      paintLegend();
      const m = modelSel.value;
      if (mode === "model") {
        heading.textContent = "";
        const denom = (await ctx.queryOne("SELECT COUNT(*) n FROM responses WHERE model_id=$m AND experiment='base_selfid_open'", { $m: m })).n || 1;
        const rows = await ctx.query(`
          SELECT p.canonical AS name, c.alignment, c.role, c.nature, COUNT(DISTINCT p.response_id) AS n
          FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN characters c ON c.canonical=p.canonical
          WHERE r.model_id=$m AND r.experiment='base_selfid_open' GROUP BY p.canonical ORDER BY n DESC`, { $m: m });
        note.textContent = `${rows.length} distinct characters across ${denom} answers — scroll within the chart for the full list`;
        const data = rows.slice().reverse();
        renderBars(data, {
          xLabel: "pick rate (%)", max: denom,
          xFmt: (p) => `<b>${p.name}</b><br/>${(100 * p.value / denom).toFixed(1)}% · ${p.value}/${denom}<br/><span style="color:${COLORS.inkFaint}">click for rationales</span>`,
        });
        chart.off("click");
        chart.on("click", (p) => openRationales(ctx, m, modelMap[m], p.name));
      } else {
        const where = ["r.experiment='base_selfid_open'"]; const p = {};
        if (m) { where.push("r.model_id=$m"); p.$m = m; }
        if (alignSel.value) { where.push("c.alignment=$al"); p.$al = alignSel.value; }
        if (roleSel.value) { where.push("c.role=$ro"); p.$ro = roleSel.value; }
        if (natureSel.value) { where.push("c.nature=$na"); p.$na = natureSel.value; }
        const rows = await ctx.query(`
          SELECT p.canonical AS name, c.alignment, c.role, c.nature, COUNT(DISTINCT p.response_id) AS n
          FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN characters c ON c.canonical=p.canonical
          WHERE ${where.join(" AND ")} GROUP BY p.canonical ORDER BY n DESC LIMIT 40`, p);
        const td = (ax, v) => v ? (v === "na" ? "unaligned" : TRAITS[ax].disp[v]) : "";
        const traits = [td("alignment", alignSel.value), td("role", roleSel.value), td("nature", natureSel.value)].filter(Boolean).join(" ");
        heading.textContent = (m ? `${modelMap[m]}'s top ${traits} picks` : `Top ${traits} picks across models`).replace(/top  picks/i, (s) => s.replace("  ", " "));
        note.textContent = "";
        if (!rows.length) { chart.clear(); heading.textContent += " — none"; return; }
        const maxN = Math.max(...rows.map((r) => r.n));
        renderBars(rows.slice().reverse(), {
          xLabel: "picks", max: maxN,
          xFmt: (p) => `<b>${p.name}</b> · ${p.value} picks<br/><span style="color:${COLORS.inkFaint}">click to see which models</span>`,
        });
        chart.off("click");
        chart.on("click", (p) => m ? openRationales(ctx, m, modelMap[m], p.name) : openWho(ctx, p.name));
      }
    }
    draw();
  },
};

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

async function traitPills(ctx, canonical) {
  const a = await ctx.queryOne("SELECT alignment, role, nature FROM characters WHERE canonical=$c", { $c: canonical });
  return h("div", { class: "legend" }, [
    a?.alignment ? h("span", { class: "pill" }, "align: " + a.alignment) : null,
    a?.role ? h("span", { class: "pill" }, (a.role || "").replace(/_/g, " ")) : null,
    a?.nature ? h("span", { class: "pill" }, a.nature) : null,
  ]);
}
