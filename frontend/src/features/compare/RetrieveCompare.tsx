// frontend/src/features/compare/RetrieveCompare.tsx
// N-way retrieval comparison: one query box drives a /query per selected pipeline,
// and the ranked-hit lists show what each pipeline surfaces and in what order.
import { useState } from "react";
import { Heading, Button } from "../../design/primitives";
import { api } from "../../api/client";
import type { Hit } from "../../api/types";
import { pane, paneHead, paneBody, picker, micro, hairline, COL_MIN } from "./styles";

export function RetrieveCompare({ docId, pipelines }:
  { docId: number; pipelines: { id: number; name: string }[] }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<(Hit[] | null)[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    if (!q.trim()) return;
    setRunning(true); setErr(null); setHits(null);
    try {
      const results = await Promise.all(pipelines.map((p) =>
        api.query({ document_id: docId, prompt: q, pipelines: [p.name] })
          .then((r) => r.hits ?? []).catch(() => null)));
      setHits(results);
    } catch (e) { setErr(String(e)); }
    finally { setRunning(false); }
  }

  return (
    <>
      <form onSubmit={(e) => { e.preventDefault(); run(); }}
        style={{ display: "flex", gap: 10, marginBottom: 14 }}>
        <input aria-label="query" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Ask a question to compare what each pipeline retrieves…"
          style={{ ...picker, flex: 1 }} />
        <Button type="submit" disabled={running || !q.trim()}>{running ? "Querying…" : "Run query"}</Button>
      </form>
      {err && <p style={{ color: "var(--oxblood)" }}>{err}</p>}
      {hits && (
        <div style={{ display: "flex", border: "1px solid var(--frame-rule)", borderRadius: 12,
          overflow: "hidden", background: "var(--card)", overflowX: "auto" }}>
          {pipelines.map((p, i) => (
            <HitColumn key={p.id} name={p.name} hits={hits[i]} border={i < pipelines.length - 1} />
          ))}
        </div>
      )}
    </>
  );
}

function HitColumn({ name, hits, border }: { name: string; hits: Hit[] | null; border?: boolean }) {
  return (
    <div style={{ ...pane, minWidth: COL_MIN, borderRight: border ? hairline : undefined }}>
      <div style={paneHead}>
        <Heading level={3} style={{ margin: 0 }}>{name}</Heading>
        <div style={{ ...micro, marginTop: 4 }}>{hits?.length ?? 0} hit{(hits?.length ?? 0) === 1 ? "" : "s"}</div>
      </div>
      <div style={{ ...paneBody, whiteSpace: "normal", padding: 0 }}>
        {!hits?.length ? <p style={{ padding: 16, color: "var(--ink-faint)" }}>No hits.</p>
          : hits.map((h, i) => (
            <div key={i} style={{ padding: "10px 16px", borderBottom: hairline }}>
              <div style={{ ...micro, display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                <span>#{i + 1}{h.page != null ? ` · p${h.page}` : ""}</span>
                <span>{h.score.toFixed(3)}</span>
              </div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.55,
                color: "var(--ink-muted)", whiteSpace: "pre-wrap" }}>
                {h.text.length > 320 ? h.text.slice(0, 320) + "…" : h.text}</div>
            </div>
          ))}
      </div>
    </div>
  );
}
