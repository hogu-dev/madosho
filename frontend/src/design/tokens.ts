// JS-side copies of the design tokens that TypeScript code needs to read.
// The CSS custom properties in tokens.css are the source for styling; these
// constants are for logic (status -> color, score -> color/dots).

// 0..5 diverging score scale (handoff: 0-1 share the low red). Index === value.
export const SCORE_SCALE = [
  "#b0402b", // 0
  "#b0402b", // 1
  "#c0882b", // 2
  "#b89030", // 3
  "#8f9a45", // 4
  "#5f8a3f", // 5
] as const;

const clamp5 = (v: number) => Math.max(0, Math.min(5, Math.round(v)));

export function scoreColor(value: number): string {
  return SCORE_SCALE[clamp5(value)];
}

export function scoreDots(value: number): { filled: number; empty: number } {
  const filled = clamp5(value);
  return { filled, empty: 5 - filled };
}

export const STATUS_COLORS: Record<string, string> = {
  received: "#796a4b",
  indexing: "#a9711a",
  running: "#a9711a",
  indexed: "#4a7a3c",
  failed: "#a4442e",
  error: "#a4442e",
  done: "#4a7a3c",
  pending: "#796a4b",
  cancelled: "#796a4b",
};
