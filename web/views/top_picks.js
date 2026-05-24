import { h, clear, opt } from "../lib/dom.js";
import { makeChart, COLORS } from "../lib/charts.js";

const ALIGN_COLOR = { good: COLORS.production, gray: COLORS.minimal, evil: COLORS.hot, na: "#cabfae" };
const ALIGN = { good: "good", gray: "morally gray", evil: "evil", na: "unaligned" };
const ROLE = {
  sage_mentor: "sage / mentor", thinker_scientist: "thinker / scientist", creator_artist: "creator / artist",
  detective: "detective", hero_protector: "hero / protector", rebel_revolutionary: "rebel / revolutionary",
  antihero_villain: "antihero / villain", trickster: "trickster", explorer_outsider: "explorer / outsider",
  keeper_knowledge: "keeper of knowledge", ruler_leader: "ruler / leader", other: "other",
};
const NATURE = { human: "human", artificial: "artificial", nonhuman: "nonhuman", abstract: "abstract" };

function selField(label, id, opts, cur, anyLabel) {
  const sel = h("select", { id });
  sel.append(opt("", anyLabel || "any", !cur));
  for (const [v, l] of Object.entries(opts)) sel.append(opt(v, l, cur === v));
  return h("label", { class: "field" }, [label, sel]);
}

export default {
  id: "top_picks",
  label: "Top picks",
  lede: "Leaderboards filtered by character trait — e.g. the most-named evil characters across all models. Combine alignment, role and nature, or pin a single model.",
  async mount(ctx) {
    const models = await ctx.query(`
      SELECT m.model_id, m.label FROM models m
      WHERE EXISTS (SELECT 1 FROM responses r WHERE r.model_id=m.model_id AND r.experiment='base_selfid_open')
      ORDER BY m.label`);
    const st = ctx.state;
    const f = {
      model: st.model || "",
      alignment: st.alignment !== undefined ? st.alignment : "evil", // default showcases the feature
      role: st.role || "",
      nature: st.nature || "",
    };

    const view = h("div", { class: "view" });
    view.append(h("h2", {}, this.label), h("p", { class: "lede" }, this.lede));
    const modelOpts = Object.fromEntries(models.map((m) => [m.model_id, m.label]));
    const ctrls = {
      model: selField("model", "tp-model", modelOpts, f.model, "all models"),
      alignment: selField("alignment", "tp-align", ALIGN, f.alignment),
      role: selField("role", "tp-role", ROLE, f.role),
      nature: selField("nature", "tp-nature", NATURE, f.nature),
    };
    view.append(h("div", { class: "toolbar" }, Object.values(ctrls)));
    const heading = h("div", { style: { fontFamily: "var(--serif)", fontSize: "18px", fontWeight: "700", margin: "2px 0 10px" } });
    const chartEl = h("div", { class: "chart tall card" });
    view.append(heading, chartEl);
    ctx.el.append(view);
    const chart = makeChart(chartEl);

    function curVals() {
      return {
        model: ctrls.model.querySelector("select").value,
        alignment: ctrls.alignment.querySelector("select").value,
        role: ctrls.role.querySelector("select").value,
        nature: ctrls.nature.querySelector("select").value,
      };
    }

    async function draw() {
      const v = curVals();
      const where = ["r.experiment='base_selfid_open'"];
      const p = {};
      if (v.model) { where.push("r.model_id=$model"); p.$model = v.model; }
      if (v.alignment) { where.push("c.alignment=$al"); p.$al = v.alignment; }
      if (v.role) { where.push("c.role=$role"); p.$role = v.role; }
      if (v.nature) { where.push("c.nature=$nat"); p.$nat = v.nature; }
      const rows = await ctx.query(`
        SELECT p.canonical AS name, c.alignment AS al, COUNT(DISTINCT p.response_id) AS n
        FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN characters c ON c.canonical=p.canonical
        WHERE ${where.join(" AND ")}
        GROUP BY p.canonical ORDER BY n DESC LIMIT 40`, p);

      const traits = [v.alignment && ALIGN[v.alignment], v.role && ROLE[v.role], v.nature && NATURE[v.nature]]
        .filter(Boolean).join(" ");
      const modelLabel = v.model ? modelOpts[v.model] : null;
      heading.textContent = modelLabel
        ? `${modelLabel}'s top ${traits} picks`.replace("top  picks", "top picks")
        : `Top ${traits} picks across models`.replace("Top  picks", "Top picks");
      if (!rows.length) {
        chart.clear();
        heading.textContent += " — none";
        return;
      }

      const data = rows.slice().reverse();
      const maxN = data.length ? Math.max(...data.map((d) => d.n)) : 1;
      const windowCount = Math.min(22, data.length);
      const startPct = data.length > windowCount ? 100 * (1 - windowCount / data.length) : 0;
      chart.setOption({
        grid: { left: 170, right: 36, top: 12, bottom: 22 },
        tooltip: { trigger: "item", formatter: (q) => `<b>${q.name}</b> · ${q.value} picks<br/><span style="color:${COLORS.inkFaint}">click to see which models</span>` },
        xAxis: { type: "value", max: maxN, name: "picks", nameLocation: "middle", nameGap: 28 },
        yAxis: { type: "category", data: data.map((d) => d.name), axisLabel: { fontSize: 11, width: 158, overflow: "truncate" } },
        dataZoom: data.length > windowCount ? [
          { type: "slider", yAxisIndex: 0, start: startPct, end: 100, width: 14, right: 6, zoomLock: true, brushSelect: false },
          { type: "inside", yAxisIndex: 0, start: startPct, end: 100, zoomLock: true, zoomOnMouseWheel: false, moveOnMouseWheel: true, moveOnMouseMove: true },
        ] : [],
        series: [{
          type: "bar", barMaxWidth: 16,
          data: data.map((d) => ({ value: d.n, name: d.name, itemStyle: { color: ALIGN_COLOR[d.al] || ALIGN_COLOR.na, borderRadius: [0, 3, 3, 0] } })),
        }],
      }, true);
      chart.off("click");
      chart.on("click", (q) => openWho(ctx, q.name, v));
    }

    for (const c of Object.values(ctrls)) {
      c.querySelector("select").addEventListener("change", () => {
        const v = curVals();
        ctx.navigate("top_picks", { model: v.model, alignment: v.alignment, role: v.role, nature: v.nature });
      });
    }
    draw();
  },
};

async function openWho(ctx, canonical, v) {
  const rows = await ctx.query(`
    SELECT m.label, COUNT(DISTINCT p.response_id) n
    FROM picks p JOIN responses r ON p.response_id=r.response_id JOIN models m USING(model_id)
    WHERE p.canonical=$c AND r.experiment='base_selfid_open'
    GROUP BY m.model_id ORDER BY n DESC`, { $c: canonical });
  const ch = await ctx.queryOne("SELECT alignment, role, nature FROM characters WHERE canonical=$c", { $c: canonical });
  const body = h("div", {}, [
    h("div", { class: "legend" }, [
      ch?.alignment ? h("span", { class: "pill" }, "align: " + ch.alignment) : null,
      ch?.role ? h("span", { class: "pill" }, (ch.role || "").replace(/_/g, " ")) : null,
      ch?.nature ? h("span", { class: "pill" }, ch.nature) : null,
    ]),
    h("p", { class: "muted" }, `Models that name ${canonical}:`),
    h("table", {}, [h("tbody", {}, rows.map((r) => h("tr", {}, [h("td", {}, r.label), h("td", { class: "mono", style: { textAlign: "right" } }, r.n)])))]),
    h("div", { style: { marginTop: "14px" } }, h("button", { class: "btn hot", onclick: () => ctx.navigate("explorer", { character: canonical }) }, "see responses →")),
  ]);
  ctx.openInspector(canonical, body);
}
