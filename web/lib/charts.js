// ECharts theme + helpers. `echarts` is the global from the vendored UMD build.
/* global echarts */

export const COLORS = {
  bg: "#0c0e13", panel: "#161a24", line: "#2a3242",
  ink: "#e9e7e1", inkDim: "#a6adba", inkFaint: "#6b7280",
  hot: "#ff7a45", teal: "#5fb3a3", blue: "#6ea8fe", violet: "#b08cff", amber: "#e3b341",
  bare: "#ff7a45", minimal: "#e3b341", production: "#5fb3a3",
};

// distinct-but-cool palette for categories; hot is held out for "the finding"
export const PALETTE = [
  "#5fb3a3", "#6ea8fe", "#b08cff", "#e3b341", "#7ec8a0", "#d98cb3",
  "#8fb0d9", "#c0a36e", "#69b7c7", "#a3b86c", "#cf8f6e", "#9aa0aa",
];

const THEME = {
  color: PALETTE,
  backgroundColor: "transparent",
  textStyle: { color: COLORS.inkDim, fontFamily: "ui-sans-serif, system-ui, sans-serif" },
  title: { textStyle: { color: COLORS.ink } },
  legend: { textStyle: { color: COLORS.inkDim }, inactiveColor: "#3a414e" },
  grid: { borderColor: COLORS.line },
  categoryAxis: { axisLine: { lineStyle: { color: COLORS.line } }, axisLabel: { color: COLORS.inkFaint }, splitLine: { lineStyle: { color: COLORS.line, opacity: 0.4 } } },
  valueAxis: { axisLine: { lineStyle: { color: COLORS.line } }, axisLabel: { color: COLORS.inkFaint }, splitLine: { lineStyle: { color: COLORS.line, opacity: 0.4 } } },
  tooltip: {
    backgroundColor: "#1c2230", borderColor: COLORS.line,
    textStyle: { color: COLORS.ink, fontSize: 12 }, extraCssText: "box-shadow:0 8px 30px rgba(0,0,0,.45);max-width:360px;white-space:normal;",
  },
};

try { echarts.registerTheme("llmchar", THEME); } catch (_) {}

export function makeChart(el) {
  const c = echarts.init(el, "llmchar", { renderer: "canvas" });
  const ro = new ResizeObserver(() => c.resize());
  ro.observe(el);
  return c;
}

export function condColor(cond) {
  return COLORS[cond] || COLORS.inkDim;
}
