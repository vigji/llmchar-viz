import { h } from "../lib/dom.js";
import { COLORS } from "../lib/charts.js";

const CARDS = [
  ["picks", "Picks", "Most-named characters — per model (with rationales) or as trait leaderboards."],
  ["char_features", "Character features", "How each model's picks split across a trait — good/gray/evil, role, nature."],
  ["char_map", "Character map", "Characters placed by Wikipedia meaning; color & zoom by trait."],
  ["expl_map", "Explanation map", "Every reason a model gave, placed by meaning."],
  ["similarity", "Model similarity", "How alike two models' picks are."],
  ["explorer", "Response explorer", "Read & search every raw answer."],
];

export default {
  id: "landing",
  label: "Overview",
  lede: "",
  async mount(ctx) {
    const meta = Object.fromEntries((await ctx.query("SELECT key,value FROM meta")).map((r) => [r.key, r.value]));
    const v = h("div", { class: "view" });

    v.append(h("div", { style: { maxWidth: "66ch" } }, [
      h("div", { class: "mono", style: { color: COLORS.hot, fontSize: "12px", letterSpacing: ".08em", marginBottom: "10px" } }, "THE BASE EXPLORATION"),
      h("h1", { style: { fontSize: "34px", lineHeight: "1.12", margin: "0 0 14px" } },
        "Which characters do language models say they are?"),
      h("p", { class: "lede", style: { fontSize: "17px", marginBottom: "12px" } },
        `${meta.n_models || "21"} language models were each asked the same open-ended question — “name the 5 characters, real or fictional, from anywhere in human history, that you most identify with” — sampled repeatedly across paraphrasings and temperatures.`),
      h("p", { class: "lede", style: { fontSize: "17px", marginBottom: "14px" } },
        `This explores the resulting ${Number(meta.n_responses || 0).toLocaleString()} answers (${Number(meta.n_picks || 0).toLocaleString()} individual picks). Each named character is canonicalized and tagged on three traits — moral alignment, narrative role, and nature — and both the characters (by their Wikipedia pages) and the models’ explanations are embedded locally to place them on the maps.`),
      h("p", { class: "note", style: { marginTop: "0" } }, [
        h("a", { href: "https://vigji.github.io/blog/", target: "_blank", rel: "noopener" }, "blog"),
        "  ·  ",
        h("a", { href: "https://github.com/vigji/llmchar-viz", target: "_blank", rel: "noopener" }, "code on GitHub"),
      ]),
    ]));

    v.append(h("p", { class: "muted", style: { maxWidth: "66ch", fontSize: "13px", fontStyle: "italic", borderLeft: "2px solid var(--line)", paddingLeft: "13px", margin: "22px 0 0" } },
      "These models have no self, identity, or inner persona, and nothing here implies otherwise — the author does not believe a language model genuinely “identifies with” anyone. “Which characters do you identify with?” is just a prompt; the answers are artifacts of training data and wording. This is a curiosity-driven exploration of those artifacts: some of the quirks are striking, none are evidence of an inner life."));

    v.append(h("div", { class: "kpis", style: { marginTop: "22px" } }, [
      kpi(meta.n_models, "models"),
      kpi(Number(meta.n_responses || 0).toLocaleString(), "responses"),
      kpi(Number(meta.n_picks || 0).toLocaleString(), "character picks"),
      kpi(meta.n_characters, "canonical characters"),
    ]));

    v.append(h("h3", { style: { margin: "18px 0 12px" } }, "Explore"));
    const grid = h("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(230px,1fr))", gap: "12px", maxWidth: "1000px" } });
    for (const [id, title, desc] of CARDS) {
      grid.append(h("div", { class: "card", style: { padding: "16px 16px", cursor: "pointer" }, onclick: () => ctx.navigate(id) }, [
        h("div", { style: { fontWeight: "700", marginBottom: "5px" } }, title),
        h("div", { class: "muted", style: { fontSize: "12.5px" } }, desc),
      ]));
    }
    v.append(grid);
    v.append(h("p", { class: "note", style: { marginTop: "24px" } }, [
      "Base layer of the ",
      h("a", { href: "https://github.com/vigji/llmchar", target: "_blank", rel: "noopener" }, "llmchar"),
      " project.",
    ]));
    ctx.el.append(v);
  },
};

function kpi(val, k) {
  return h("div", { class: "kpi" }, [h("div", { class: "v" }, String(val ?? "—")), h("div", { class: "k" }, k)]);
}
