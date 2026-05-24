// Shared categorical coloring for the scatter maps: groups points by a chosen
// attribute and resolves a color + legend label per group, reusing the trait
// palette so colors match Picks / Character features everywhere.
import { TRAITS, FALLBACK } from "./traits.js";
import { PALETTE } from "./charts.js";

export const FAMILY_COLOR = {
  mistral: "#bb4423", claude: "#6d86a8", openai: "#3f7d6e", gemini: "#b8863f",
  grok: "#7d5a78", qwen: "#9a6a4e", deepseek: "#4a6d8c", kimi: "#88937e",
};
export const famColor = (f) => FAMILY_COLOR[f] || FALLBACK;

// pts: point objects; colorBy: key; get: (pt)=>raw value.
// Returns groups [{ name(display), color, items }], largest first.
export function groupPoints(pts, colorBy, get) {
  const groups = new Map();
  for (const p of pts) {
    const v = get(p);
    const key = (v === null || v === undefined || v === "" || v === -1) ? "__none" : v;
    (groups.get(key) || groups.set(key, []).get(key)).push(p);
  }
  const trait = TRAITS[colorBy];
  const keys = [...groups.keys()].sort((a, b) => groups.get(b).length - groups.get(a).length);
  let pal = 0;
  return keys.map((k) => {
    let color, name;
    if (k === "__none") { color = "#cabfae"; name = colorBy === "cl" ? "unclustered" : "—"; }
    else if (trait) { color = trait.colors[k] || FALLBACK; name = trait.disp[k] || k; }
    else if (colorBy === "family" || colorBy === "topfamily") { color = famColor(k); name = k; }
    else if (colorBy === "cl") { color = PALETTE[((k % PALETTE.length) + PALETTE.length) % PALETTE.length]; name = "cluster " + k; }
    else { color = PALETTE[pal++ % PALETTE.length]; name = String(k); }
    return { key: k, name, color, items: groups.get(k) };
  });
}

// pan/zoom for a value-axis scatter (wheel zoom + drag pan, points clipped not dropped)
export const SCATTER_ZOOM = [
  { type: "inside", xAxisIndex: 0, filterMode: "none" },
  { type: "inside", yAxisIndex: 0, filterMode: "none" },
];
