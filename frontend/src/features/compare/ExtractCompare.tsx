// frontend/src/features/compare/ExtractCompare.tsx
// N-way extract comparison: every selected pipeline's stored page extraction side
// by side, with a single "these pipelines don't all agree here" highlight (no
// baseline). The original PDF stays pinned as the last column as the source of
// truth. Reuses the page rail + Raw/Rendered viewer + amber highlighter.
import { useEffect, useState } from "react";
import { Heading, EmptyState, SegmentedToggle } from "../../design/primitives";
import { Highlighted } from "../../lib/highlight";
import { RenderedText } from "../../lib/markdownTable";
import { api } from "../../api/client";
import type { ExtractDivergence } from "../../api/types";
import { pane, paneHead, paneBody, railBtn, navBtn, micro, hairline, COL_MIN } from "./styles";

export function ExtractCompare({ docId, pipelineIds }: { docId: number; pipelineIds: number[] }) {
  const [data, setData] = useState<ExtractDivergence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cur, setCur] = useState(0);
  const [viewMode, setViewMode] = useState<"raw" | "rendered">("raw");
  const idsKey = pipelineIds.join(",");

  useEffect(() => {
    setData(null); setErr(null);
    api.getExtractDivergence(docId, pipelineIds).then(setData).catch((e) => setErr(String(e)));
    // idsKey captures the pipeline set; pipelineIds identity is not stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, idsKey]);

  // Open on the first page that actually differs.
  useEffect(() => {
    const ps = data?.pages;
    if (!ps?.length) { setCur(0); return; }
    const firstChanged = ps.findIndex((p) => p.change > 0);
    setCur(firstChanged >= 0 ? firstChanged : 0);
  }, [data]);

  if (err) return <p style={{ color: "var(--oxblood)" }}>{err}</p>;
  if (!data) return <p style={{ color: "var(--ink-muted)" }}>Loading extractions…</p>;
  if (!data.pages.length)
    return <EmptyState title="No extracted text"
      hint="No selected pipeline stored page-level extraction for this document." />;

  const pages = data.pages;
  const idx = Math.min(cur, Math.max(0, pages.length - 1));
  const pg = pages[idx];
  const maxChange = Math.max(1, ...pages.map((p) => p.change));

  function jumpNextChange() {
    for (let k = 1; k <= pages.length; k++) {
      const i = (idx + k) % pages.length;
      if (pages[i].change > 0) { setCur(i); return; }
    }
  }

  return (
    <>
      {pages.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "0 0 14px", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {pages.map((p, i) => {
              const changed = p.change > 0;
              const barH = changed ? 2 + Math.round(6 * (p.change / maxChange)) : 0;  // 2-8px
              return (
                <button key={p.page} onClick={() => setCur(i)} aria-label={`page ${p.page}`}
                  title={changed ? `${p.change} chars differ` : "no content differences"}
                  style={railBtn(i === idx, changed)}>
                  {p.page}
                  <span style={{ display: "flex", alignItems: "flex-end", height: 8, marginTop: 3 }}>
                    <span style={{ width: "100%", height: barH, borderRadius: 2,
                      background: changed ? "var(--gilt)" : "transparent" }} />
                  </span>
                </button>
              );
            })}
          </div>
          <span style={{ color: "var(--ink-muted)", fontSize: 13 }}>
            Page {pg.page} / {pages.length}{"  "}
            <button style={navBtn} onClick={() => setCur(Math.max(0, idx - 1))} disabled={idx === 0}>Prev</button>{"  "}
            <button style={navBtn} onClick={() => setCur(Math.min(pages.length - 1, idx + 1))} disabled={idx === pages.length - 1}>Next</button>{"  "}
            <button style={navBtn} onClick={jumpNextChange}>Next change &gt;</button>
          </span>
          <span style={{ ...micro, color: "var(--ink-faint)" }}>gilt bar = content differs (taller = more)</span>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ ...micro, color: "var(--ink-faint)" }}>
          highlighted = these pipelines don&apos;t all agree here</span>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {viewMode === "rendered" && <span style={{ ...micro, color: "var(--ink-faint)" }}>
            tables drawn as grids; diff highlighting off</span>}
          <SegmentedToggle value={viewMode} onChange={(v) => setViewMode(v as "raw" | "rendered")}
            options={[{ value: "raw", label: "Raw + diff" }, { value: "rendered", label: "Rendered" }]} />
        </div>
      </div>

      {/* Every extraction column + the Original PDF pinned last. The row scrolls
          horizontally once there are more columns than fit. */}
      <div style={{ display: "flex", border: "1px solid var(--frame-rule)", borderRadius: 12,
        overflow: "hidden", background: "var(--card)", overflowX: "auto" }}>
        {pg.columns.map((col) => (
          <div key={col.pipeline_id} style={{ ...pane, minWidth: COL_MIN, borderRight: hairline }}>
            <div style={paneHead}><Heading level={3} style={{ margin: 0 }}>{col.name}</Heading></div>
            <div style={paneBody}>{viewMode === "rendered"
              ? <RenderedText text={col.text} />
              : <Highlighted text={col.text} spans={col.spans} won={false} />}</div>
          </div>
        ))}
        <div style={{ ...pane, minWidth: COL_MIN }}>
          <div style={paneHead}><Heading level={3} style={{ margin: 0 }}>Original</Heading></div>
          <div style={{ ...paneBody, padding: 0 }}>
            {/* key forces a remount so the #page fragment re-navigates the PDF */}
            <iframe key={pg.page} title="original" src={`${api.fileUrl(docId)}#page=${pg.page}`}
              style={{ width: "100%", height: "100%", minHeight: "60vh", border: 0 }} />
          </div>
        </div>
      </div>
    </>
  );
}
