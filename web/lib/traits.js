// Shared character-trait axes: ordered values, colors, and display labels.
// One source of truth so every view colors traits identically.
import { COLORS } from "./charts.js";

export const FALLBACK = "#cabfae";

export const TRAITS = {
  alignment: {
    label: "moral alignment",
    values: ["good", "gray", "evil", "na"],
    colors: { good: COLORS.production, gray: COLORS.minimal, evil: COLORS.hot, na: "#cabfae" },
    disp: { good: "good", gray: "morally gray", evil: "evil", na: "n/a" },
  },
  role: {
    label: "role / archetype",
    values: ["antihero_villain", "rebel_revolutionary", "trickster", "detective", "explorer_outsider",
             "sage_mentor", "thinker_scientist", "creator_artist", "hero_protector", "keeper_knowledge",
             "ruler_leader", "other"],
    colors: {
      antihero_villain: COLORS.hot, rebel_revolutionary: "#9a6a4e", trickster: "#a98a4a",
      detective: "#4a6d8c", explorer_outsider: "#88937e", sage_mentor: "#3f7d6e",
      thinker_scientist: "#6d86a8", creator_artist: "#7d5a78", hero_protector: "#6f7d4a",
      keeper_knowledge: "#8a6f9b", ruler_leader: "#b8863f", other: "#cabfae",
    },
    disp: {
      antihero_villain: "antihero / villain", rebel_revolutionary: "rebel / revolutionary",
      trickster: "trickster", detective: "detective", explorer_outsider: "explorer / outsider",
      sage_mentor: "sage / mentor", thinker_scientist: "thinker / scientist",
      creator_artist: "creator / artist", hero_protector: "hero / protector",
      keeper_knowledge: "keeper of knowledge", ruler_leader: "ruler / leader", other: "other",
    },
  },
  nature: {
    label: "nature",
    values: ["artificial", "nonhuman", "abstract", "human"],
    colors: { artificial: COLORS.hot, nonhuman: "#3f7d6e", abstract: "#7d5a78", human: "#cabfae" },
    disp: { artificial: "artificial", nonhuman: "nonhuman", abstract: "abstract", human: "human" },
  },
};

export function traitColor(axis, value) {
  return (TRAITS[axis] && TRAITS[axis].colors[value]) || FALLBACK;
}
