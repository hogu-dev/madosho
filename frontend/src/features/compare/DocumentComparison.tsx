// frontend/src/features/compare/DocumentComparison.tsx
// The full per-document comparison body, shared so there is one codebase for it.
// Renders (top to bottom): a read-only scoreboard (every step rated across this
// document's pipelines, the highest-rated tool per step marked, total /15), a
// "not yet built" rail (registry tools no pipeline here uses yet), an advisory
// "recommended test" combo, and the shared <Comparator> that lines up what each
// pipeline actually produced at every stage. Parameterised by docId only -- it has
// no opinion on HOW the document was chosen, so the standalone Compare page (doc
// picker or ?document deep-link) can drop it in once a document is selected.
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, Heading, StatusDot, SegmentScore } from "../../design/primitives";
import { api } from "../../api/client";
import type { Components, DocPipeline, RecommendedPipeline } from "../../api/types";
import { Comparator } from "./Comparator";
import { micro, hairline } from "./styles";

const fmtRating = (v: number) => (Number.isInteger(v) ? v : v.toFixed(1));

const SLOT_ROWS: { key: string; label: string }[] = [
  { key: "extract", label: "Extract" }, { key: "chunk", label: "Chunk" }, { key: "index", label: "Index" },
];
// Map a pipeline slot to the /components registry key, for the "not yet built" nudge.
const SLOT_TO_KIND: Record<string, string> = { extract: "parser", chunk: "chunker", index: "embedder" };

// Highest per-step rating across the pipeline columns, for the winner highlight.
function bestBySlot(pipes: DocPipeline[]): Record<string, number> {
  const best: Record<string, number> = {};
  for (const p of pipes) {
    for (const slot of Object.keys(p.steps)) {
      const r = p.steps[slot];
      if (best[slot] == null || r > best[slot]) best[slot] = r;
    }
  }
  return best;
}

export function DocumentComparison({ docId }: { docId: number }) {
  // pipes stays null until the first load resolves, so we can tell "still loading"
  // apart from "loaded, but this document has no pipelines" and avoid flashing the
  // empty state at a document that actually has pipelines.
  const [pipes, setPipes] = useState<DocPipeline[] | null>(null);
  const [reco, setReco] = useState<RecommendedPipeline | null>(null);
  const [components, setComponents] = useState<Components | null>(null);

  const load = useCallback(() => {
    setPipes(null);
    api.getDocumentPipelines(docId).then(setPipes).catch(() => setPipes([]));
    api.getRecommendedPipeline(docId).then(setReco).catch(() => setReco(null));
    api.components().then(setComponents).catch(() => setComponents(null));
  }, [docId]);
  useEffect(() => { load(); }, [load]);

  const indexed = useMemo(() => (pipes ?? []).filter((p) => p.status === "indexed"), [pipes]);

  if (pipes == null) return <p style={{ color: "var(--ink-muted)" }}>Loading pipelines…</p>;
  if (pipes.length === 0) {
    return <EmptyState title="Nothing to compare yet"
      hint="Build a pipeline on this document to compare its steps." />;
  }

  const best = bestBySlot(pipes);

  return (
    <>
      {/* --- step-by-step scoreboard: each step across every pipeline, read-only --- */}
      <div style={{ border: "1px solid var(--frame-rule)", borderRadius: 12, background: "var(--card)",
        overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ ...micro, textAlign: "left", padding: "14px 18px",
                borderBottom: `2px solid var(--frame-rule)`, width: 96 }}>Step</th>
              {pipes.map((p) => (
                <th key={p.id} style={{ textAlign: "left", padding: "12px 18px", verticalAlign: "top",
                  borderBottom: "2px solid var(--frame-rule)", borderLeft: hairline }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 600,
                      overflowWrap: "anywhere" }}>{p.name}</span>
                    {p.effective && <span style={{ ...micro, color: "var(--ink)", background: "var(--gilt)",
                      borderRadius: 5, padding: "2px 8px" }}>Effective</span>}
                  </div>
                  <div style={{ marginTop: 6 }}><StatusDot status={p.status} /></div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SLOT_ROWS.map((row) => (
              <tr key={row.key}>
                <th style={{ ...micro, textAlign: "left", padding: "14px 18px", borderTop: hairline,
                  verticalAlign: "middle" }}>{row.label}</th>
                {pipes.map((p) => {
                  const r = p.steps[row.key];
                  const isBest = pipes.length > 1 && r != null && r === best[row.key];
                  return (
                    <td key={p.id} style={{ padding: "14px 18px", verticalAlign: "middle", borderTop: hairline,
                      borderLeft: hairline, background: isBest ? "rgba(156,121,32,0.12)" : undefined }}
                      title={isBest ? "highest-rated for this step" : undefined}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, color: "var(--ink-muted)",
                        marginBottom: 6, display: "flex", alignItems: "center", gap: 7 }}>
                        {p.slots[row.key] ?? "—"}
                        {isBest && <span style={{ ...micro, color: "var(--gilt)" }}>best</span>}
                      </div>
                      {r != null ? <SegmentScore value={r} /> : <span style={{ color: "var(--ink-faint)" }}>—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <th style={{ ...micro, textAlign: "left", padding: "16px 18px",
                borderTop: "2px solid var(--frame-rule)", verticalAlign: "middle" }}>Total</th>
              {pipes.map((p) => (
                <td key={p.id} style={{ padding: "16px 18px", borderTop: "2px solid var(--frame-rule)",
                  borderLeft: hairline }} title="summed step ratings (advice, not a verdict)">
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600 }}>
                    {fmtRating(p.rating)}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink-faint)" }}>/15</span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <NotYetBuilt pipes={pipes} components={components} />

      {/* --- advisory "recommended test": best tool per slot, a combo worth building. --- */}
      {reco && !reco.already_built && (
        <div style={{ marginTop: 18, border: "1px solid var(--frame-rule)", borderRadius: 10,
          padding: "12px 16px", background: "rgba(156,121,32,0.10)", fontSize: 12.5,
          color: "var(--ink-muted)", lineHeight: 1.7 }}>
          <span style={{ ...micro, color: "var(--gilt)", marginRight: 10 }}>Recommended test</span>
          extract <b>{reco.slots.extract}</b> · chunk <b>{reco.slots.chunk}</b> · index <b>{reco.slots.index}</b>
          <span style={{ fontFamily: "var(--font-mono)", marginLeft: 10 }}>
            projected {fmtRating(reco.projected_rating)}/15</span>
          <div style={{ marginTop: 4, color: "var(--ink-faint)" }}>
            The highest-rated tool in each step, combined. Summed ratings ignore step interactions,
            so this is a combo worth testing — never a guarantee it is better. Build it from the document page.</div>
        </div>
      )}

      {/* --- the comparator: any number of pipelines, all stages stacked --- */}
      <div style={{ marginTop: 28 }}>
        <Heading level={3} style={{ margin: "0 0 12px" }}>Compare what each pipeline produced</Heading>
        <Comparator docId={docId} pipelines={indexed} />
      </div>
    </>
  );
}

// --- "Red / not run": registry tools that no pipeline on this document has built
// yet, per step. A nudge to go build one, never a gate. ---
function NotYetBuilt({ pipes, components }: { pipes: DocPipeline[]; components: Components | null }) {
  if (!components) return null;
  const missing = SLOT_ROWS.map((row) => {
    const kind = SLOT_TO_KIND[row.key];
    const built = new Set(pipes.map((p) => p.slots[row.key]).filter(Boolean) as string[]);
    const tools = (components[kind] ?? []).map((c) => c.name).filter((n) => !built.has(n));
    return { label: row.label, tools };
  }).filter((m) => m.tools.length);
  if (!missing.length) return null;
  return (
    <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 14, alignItems: "baseline" }}>
      <span style={{ ...micro, color: "var(--oxblood)" }}>Not yet built</span>
      {missing.map((m) => (
        <span key={m.label} style={{ display: "inline-flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={micro}>{m.label}</span>
          {m.tools.map((t) => (
            <span key={t} title="no pipeline on this document uses this tool yet — build one to compare it"
              style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, padding: "2px 8px", borderRadius: 5,
                color: "var(--oxblood)", border: "1px solid rgba(140,40,40,0.35)",
                background: "rgba(140,40,40,0.06)" }}>{t}</span>
          ))}
        </span>
      ))}
    </div>
  );
}
