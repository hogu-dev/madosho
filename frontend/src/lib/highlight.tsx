// frontend/src/lib/highlight.tsx
// Paints disagreement spans amber on load; once a verdict lands, the winning
// side's spans gain a green edge (the same success green the rest of the UI
// uses for "answering queries") so the approved conversion reads as endorsed.
import type { ReactNode } from "react";

const AMBER = "rgba(184,146,67,0.40)";
const WIN_GREEN = "#4a7a3c";

export function Highlighted(
  { text, spans, won }: { text: string; spans: [number, number][]; won: boolean },
) {
  if (!spans.length) return <>{text}</>;
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const out: ReactNode[] = [];
  let pos = 0;
  sorted.forEach(([start, end], i) => {
    if (start > pos) out.push(text.slice(pos, start));
    out.push(
      <mark key={i} style={{
        background: AMBER, color: "var(--ink)", fontWeight: 600, borderRadius: 2,
        borderBottom: won ? `2px solid ${WIN_GREEN}` : "2px solid transparent",
      }}>{text.slice(start, end)}</mark>);
    pos = end;
  });
  if (pos < text.length) out.push(text.slice(pos));
  return <>{out}</>;
}
