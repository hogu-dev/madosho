// frontend/src/features/compare/Comparator.tsx
// The shared side-by-side comparator: pick any number of a document's pipelines
// (>=2) and see what each produced at every stage. Stages stack down the page and
// each can be hidden with a checkbox -- no toggle that shows only one at a time.
// Rendered inside DocumentComparison on the standalone Compare page.
import { useEffect, useMemo, useState } from "react";
import { Heading, Button, EmptyState } from "../../design/primitives";
import type { DocPipeline } from "../../api/types";
import { ExtractCompare } from "./ExtractCompare";
import { ChunkCompare } from "./ChunkCompare";
import { RetrieveCompare } from "./RetrieveCompare";
import { micro, picker, hairline } from "./styles";

type StageKey = "extract" | "chunk" | "retrieve";
const STAGES: { key: StageKey; label: string }[] = [
  { key: "extract", label: "Extract" }, { key: "chunk", label: "Chunk" }, { key: "retrieve", label: "Retrieve" },
];
// A/B/C column labels -- echoes how you'd name the pipelines you're lining up.
const colLabel = (i: number) => String.fromCharCode(65 + i);

const smallBtn: React.CSSProperties = {
  fontFamily: "var(--font-ui)", fontSize: 12.5, padding: "6px 11px", borderRadius: 8,
  border: "1px solid var(--frame-rule)", background: "var(--card)", color: "var(--ink-muted)",
  cursor: "pointer",
};

export function Comparator({ docId, pipelines }: { docId: number; pipelines: DocPipeline[] }) {
  // `ids` = the pipeline columns being configured; `applied` is the snapshot the
  // bodies actually render. Diffs / retrieval are expensive, so nothing runs until
  // Compare is pressed, and changing a picker clears the snapshot so a fresh pick
  // never silently re-runs an expensive draw.
  const [ids, setIds] = useState<number[]>([]);
  const [applied, setApplied] = useState<number[] | null>(null);
  const [stages, setStages] = useState<Record<StageKey, boolean>>(
    { extract: true, chunk: true, retrieve: true });

  // Default to the first two indexed pipelines once they load.
  useEffect(() => {
    setIds((cur) => (cur.length ? cur : pipelines.slice(0, 2).map((p) => p.id)));
  }, [pipelines]);

  const setCol = (i: number, v: number) => {
    setIds((c) => c.map((x, k) => (k === i ? v : x))); setApplied(null);
  };
  const addCol = () => {
    const used = new Set(ids);
    const next = pipelines.find((p) => !used.has(p.id)) ?? pipelines[0];
    if (next) { setIds((c) => [...c, next.id]); setApplied(null); }
  };
  const removeCol = (i: number) => { setIds((c) => c.filter((_, k) => k !== i)); setApplied(null); };
  const toggleStage = (k: StageKey) => setStages((s) => ({ ...s, [k]: !s[k] }));

  const appliedPipes = useMemo(
    () => (applied ?? [])
      .map((id) => pipelines.find((p) => p.id === id))
      .filter((p): p is DocPipeline => p != null),
    [applied, pipelines]);

  if (pipelines.length < 2) {
    return (
      <div style={{ marginTop: 8 }}>
        <EmptyState title="Need two built pipelines"
          hint="Build a second pipeline on this document (different parser, chunker, or embedder) to compare their output side by side." />
      </div>
    );
  }

  const canAdd = ids.length < pipelines.length;
  const anyStage = STAGES.some((s) => stages[s.key]);

  return (
    <div>
      {/* --- pipeline columns: one dropdown each, add/remove to any number --- */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        {ids.map((id, i) => (
          <span key={i} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <span style={{ ...micro, color: "var(--gilt)" }}>{colLabel(i)}</span>
            <select aria-label={`pipeline ${colLabel(i)}`} style={picker} value={id}
              onChange={(e) => setCol(i, Number(e.target.value))}>
              {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {ids.length > 2 && (
              <button aria-label={`remove pipeline ${colLabel(i)}`} title="remove column"
                onClick={() => removeCol(i)} style={{ ...smallBtn, padding: "6px 9px" }}>&times;</button>
            )}
          </span>
        ))}
        {canAdd && <button onClick={addCol} style={smallBtn}>+ column</button>}
        <Button variant="primary" onClick={() => setApplied([...ids])} disabled={ids.length < 2}>
          Compare</Button>
      </div>

      {/* --- stage checkboxes: show any combination, stacked --- */}
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 18 }}>
        <span style={micro}>Stages</span>
        {STAGES.map((s) => (
          <label key={s.key} style={{ display: "inline-flex", gap: 6, alignItems: "center",
            cursor: "pointer", fontSize: 13, color: "var(--ink-muted)" }}>
            <input type="checkbox" checked={stages[s.key]} onChange={() => toggleStage(s.key)} />
            {s.label}
          </label>
        ))}
      </div>

      {!applied ? (
        <p style={{ fontSize: 12.5, color: "var(--ink-muted)", lineHeight: 1.6 }}>
          Pick the pipelines to line up and press <b>Compare</b>. Diffs and retrieval are only drawn
          when you ask — the page stays light until then.</p>
      ) : !anyStage ? (
        <p style={{ ...micro, color: "var(--ink-faint)" }}>All stages hidden — tick a stage to see it.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          {stages.extract && (
            <Section title="Extract">
              <ExtractCompare docId={docId} pipelineIds={applied} />
            </Section>
          )}
          {stages.chunk && (
            <Section title="Chunk">
              <ChunkCompare pipelines={appliedPipes} />
            </Section>
          )}
          {stages.retrieve && (
            <Section title="Retrieve">
              <RetrieveCompare docId={docId} pipelines={appliedPipes} />
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <Heading level={3} style={{ margin: "0 0 12px", paddingBottom: 6, borderBottom: hairline }}>
        {title}</Heading>
      {children}
    </section>
  );
}
