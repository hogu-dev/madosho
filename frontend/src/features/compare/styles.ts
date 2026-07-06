// frontend/src/features/compare/styles.ts
// Shared visual language for the side-by-side comparators. The whole comparison
// body (DocumentComparison) imports from here so the surface stays consistent --
// one codebase, per the design intent.
import type { CSSProperties } from "react";

export const hairline = "1px solid rgba(120,95,40,0.18)";

// The small uppercase mono caption the whole app leans on.
export const micro: CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
  textTransform: "uppercase", color: "var(--ink-faint)",
};

// A comparison column: fixed header over an independently-scrolling body, so the
// pipeline label stays pinned while you scroll its extracted text / chunks / hits.
export const pane: CSSProperties = {
  flex: 1, minWidth: 0, display: "flex", flexDirection: "column", maxHeight: "72vh",
};
export const paneHead: CSSProperties = {
  flexShrink: 0, padding: "9px 16px", borderBottom: hairline, background: "rgba(156,121,32,0.08)",
};
export const paneBody: CSSProperties = {
  flex: 1, minHeight: 0, overflow: "auto", padding: 16,
  whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.6,
};

// Minimum column width: with many pipelines lined up the row scrolls horizontally
// rather than squeezing every column into an unreadable sliver.
export const COL_MIN = 260;

// A page-rail button on the Extract view: gilt when the page has content
// differences (taller bar = more), dimmed when the pipelines agree.
export const railBtn = (active: boolean, changed: boolean): CSSProperties => ({
  minWidth: 30, padding: "4px 6px", cursor: "pointer", borderRadius: 7,
  fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink)",
  background: active ? "rgba(156,121,32,0.16)" : "transparent",
  border: `1px solid ${active ? "var(--gilt)" : "var(--frame-rule)"}`,
  opacity: changed ? 1 : 0.45,
});
export const navBtn: CSSProperties = {
  background: "transparent", border: "none", padding: 0, cursor: "pointer",
  color: "var(--gilt)", fontFamily: "var(--font-ui)", fontSize: 13,
};
export const picker: CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 13, padding: "6px 10px", borderRadius: 8,
  border: "1px solid var(--frame-rule)", background: "var(--card)", color: "var(--ink)",
};
