// ECharts theme + helpers. `echarts` is the global from the vendored UMD build.
/* global echarts */

export const COLORS = {
  bg: "#fefcf8", panel: "#fffdf9", line: "#e4dccc",
  ink: "#1c1b1a", inkDim: "#6f6860", inkFaint: "#9a938a",
  hot: "#bb4423", brown: "#6b4c3b", tan: "#b98e55",
  bare: "#bb4423", minimal: "#b8863f", production: "#3f7d6e",
};

// muted, warm-harmonized palette readable on cream; hot is held out for "the finding"
export const PALETTE = [
  "#3f7d6e", "#4a6d8c", "#7d5a78", "#b8863f", "#6f7d4a", "#9a6a4e",
  "#5f8a9a", "#8a6f9b", "#a98a4a", "#6d86a8", "#88937e", "#a39a8c",
];

const SANS = '"Libertinus Sans", "Gill Sans", "Gill Sans MT", Calibri, sans-serif';
const THEME = {
  color: PALETTE,
  backgroundColor: "transparent",
  textStyle: { color: COLORS.inkDim, fontFamily: SANS },
  title: { textStyle: { color: COLORS.ink } },
  legend: { textStyle: { color: COLORS.inkDim, fontFamily: SANS }, inactiveColor: "#cabfae" },
  grid: { borderColor: COLORS.line },
  categoryAxis: { axisLine: { lineStyle: { color: COLORS.line } }, axisLabel: { color: COLORS.inkFaint }, splitLine: { lineStyle: { color: COLORS.line, opacity: 0.6 } } },
  valueAxis: { axisLine: { lineStyle: { color: COLORS.line } }, axisLabel: { color: COLORS.inkFaint }, splitLine: { lineStyle: { color: COLORS.line, opacity: 0.6 } } },
  tooltip: {
    backgroundColor: "#fffdf9", borderColor: COLORS.line,
    textStyle: { color: COLORS.ink, fontSize: 12, fontFamily: SANS },
    extraCssText: "box-shadow:0 10px 34px rgba(60,43,31,.18);max-width:360px;white-space:normal;",
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
