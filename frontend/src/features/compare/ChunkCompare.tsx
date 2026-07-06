// frontend/src/features/compare/ChunkCompare.tsx
// N-way chunk comparison: each selected pipeline's stored chunks side by side --
// count, size stats, and the chunk list. Independent per column, so it scales to
// any number of pipelines with no cross-column logic.
import { useEffect, useState } from "react";
import { Heading } from "../../design/primitives";
import { api } from "../../api/client";
import type { Artifacts } from "../../api/types";
import { pane, paneHead, paneBody, micro, hairline, COL_MIN } from "./styles";

export function ChunkCompare({ pipelines }: { pipelines: { id: number; name: string }[] }) {
  const [arts, setArts] = useState<(Artifacts | null)[] | null>(null);
  const idsKey = pipelines.map((p) => p.id).join(",");

  useEffect(() => {
    setArts(null);
    Promise.all(pipelines.map((p) => api.getPipelineArtifacts(p.id).catch(() => null))).then(setArts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  if (!arts) return <p style={{ color: "var(--ink-muted)" }}>Loading chunks…</p>;

  return (
    <div style={{ display: "flex", border: "1px solid var(--frame-rule)", borderRadius: 12,
      overflow: "hidden", background: "var(--card)", overflowX: "auto" }}>
      {pipelines.map((p, i) => (
        <ChunkColumn key={p.id} name={p.name} art={arts[i]} border={i < pipelines.length - 1} />
      ))}
    </div>
  );
}

function ChunkColumn({ name, art, border }: { name: string; art: Artifacts | null; border?: boolean }) {
  const chunks = art?.chunks ?? [];
  const sizes = chunks.map((c) => c.text.length);
  const total = sizes.reduce((a, b) => a + b, 0);
  const avg = sizes.length ? Math.round(total / sizes.length) : 0;
  const min = sizes.length ? Math.min(...sizes) : 0;
  const max = sizes.length ? Math.max(...sizes) : 0;
  return (
    <div style={{ ...pane, minWidth: COL_MIN, borderRight: border ? hairline : undefined }}>
      <div style={paneHead}>
        <Heading level={3} style={{ margin: 0 }}>{name}</Heading>
        <div style={{ ...micro, marginTop: 4 }}>
          {chunks.length} chunk{chunks.length === 1 ? "" : "s"} · avg {avg} · min {min} · max {max} chars</div>
      </div>
      <div style={{ ...paneBody, whiteSpace: "normal", padding: 0 }}>
        {chunks.length === 0 ? <p style={{ padding: 16, color: "var(--ink-faint)" }}>No chunks.</p>
          : chunks.map((c, i) => (
            <div key={c.id || i} style={{ padding: "10px 16px", borderBottom: hairline }}>
              <div style={{ ...micro, display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                <span>#{i + 1}{c.page != null ? ` · p${c.page}` : ""}</span>
                <span>{c.text.length} chars</span>
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.55,
                color: "var(--ink-muted)", whiteSpace: "pre-wrap" }}>
                {c.text.length > 320 ? c.text.slice(0, 320) + "…" : c.text}</div>
            </div>
          ))}
      </div>
    </div>
  );
}
