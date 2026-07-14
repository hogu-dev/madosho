import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { LibraryDocument } from "../api/types";
import { Button, Heading, Panel, StatusDot, MeterBar } from "../design/primitives";
import { usePolling } from "../hooks/usePolling";
import { UploadModal } from "./UploadModal";
import { ImportKbModal } from "./ImportKbModal";
import { ReconfigModal } from "./ReconfigModal";
import { BuildConsole } from "./BuildConsole";
import { useAuth } from "../auth/AuthContext";

type Filter = "all" | "indexed" | "indexing" | "failed";
const bucket = (s: string): Exclude<Filter, "all"> =>
  s === "indexed" ? "indexed" : s === "failed" ? "failed" : "indexing";

const GRID = "2.5fr 1fr 1.5fr 0.7fr 1fr 0.7fr";
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>—</span>;

export function Documents() {
  const { canWrite } = useAuth();
  const [docs, setDocs] = useState<LibraryDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [importKbOpen, setImportKbOpen] = useState(false);
  const [reconfigDoc, setReconfigDoc] = useState<LibraryDocument | null>(null);

  const load = useCallback(async () => {
    try { setDocs(await api.listLibraryDocuments()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load documents"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const list = docs ?? [];
  const working = list.some((d) => d.status === "indexing" || d.status === "received");
  usePolling(load, 2500, working);

  const counts = {
    all: list.length,
    indexed: list.filter((d) => bucket(d.status) === "indexed").length,
    indexing: list.filter((d) => bucket(d.status) === "indexing").length,
    failed: list.filter((d) => bucket(d.status) === "failed").length,
  };
  const rows = list.filter((d) => filter === "all" || bucket(d.status) === filter);

  const chip = (key: Filter, text: string) => (
    <span onClick={() => setFilter(key)} data-active={filter === key ? "true" : "false"}
      style={{ fontSize: 12, cursor: "pointer", borderRadius: 20, padding: "5px 13px",
        fontWeight: filter === key ? 600 : 400,
        color: filter === key ? "var(--ink)" : "#473c29",
        background: filter === key ? "#d3c4a3" : "transparent",
        border: "1px solid rgba(120,95,40,0.28)" }}>{text}</span>
  );

  return (
    <Panel style={{ padding: "30px 32px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 24 }}>
        <div>
          <Heading level={1} style={{ margin: 0 }}>Documents</Heading>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 0", maxWidth: 560,
            lineHeight: 1.55 }}>
            Every source in madosho — indexed once, then shared across any corpus. A document carries
            its own pipelines; corpora only reference it.</p>
        </div>
        <div style={{ display: "flex", gap: 10, flexShrink: 0 }}>
          <Button variant="ghost" onClick={() => setImportKbOpen(true)} disabled={!canWrite}>
            ⧉ Import KB</Button>
          <Button onClick={() => setUploadOpen(true)} disabled={!canWrite}>↑ Upload PDF</Button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "22px 0 4px",
        flexWrap: "wrap" }}>
        {chip("all", `All ${counts.all}`)}
        {chip("indexed", `Indexed ${counts.indexed}`)}
        {chip("indexing", `Indexing ${counts.indexing}`)}
        {chip("failed", `Failed ${counts.failed}`)}
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {docs === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {docs !== null && docs.length === 0 && !error && (
        <div style={{ marginTop: 28, border: "1.5px dashed rgba(120,95,40,0.42)", borderRadius: 14,
          padding: "56px 40px", textAlign: "center", background: "rgba(252,247,237,0.25)" }}>
          <div style={{ fontSize: 40, opacity: 0.7 }} aria-hidden>📄</div>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 21, fontWeight: 500,
            marginTop: 16 }}>Your library is empty</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.6,
            margin: "10px auto 24px", maxWidth: 380 }}>
            Upload a PDF to index it. madosho parses, chunks and embeds it in the background, then it's
            ready to scry and to tune.</p>
          <Button onClick={() => setUploadOpen(true)} disabled={!canWrite}>↑ Upload your first PDF</Button>
        </div>
      )}

      {docs !== null && docs.length > 0 && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, padding: "12px 14px",
            fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-faint)",
            borderBottom: "1px solid var(--frame-rule)" }}>
            <div>Document</div><div>Status</div><div>Corpora</div><div>Pipes</div>
            <div>Effective</div><div style={{ textAlign: "right" }}>Updated</div>
          </div>
          {rows.map((d) => <Row key={d.id} doc={d} onChanged={load} onReconfig={setReconfigDoc} />)}
        </div>
      )}

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={load} />
      <ImportKbModal open={importKbOpen} onClose={() => setImportKbOpen(false)} onImported={load} />
      <ReconfigModal open={reconfigDoc !== null} doc={reconfigDoc}
        onClose={() => setReconfigDoc(null)} onDone={load} />
    </Panel>
  );
}

function Row({ doc, onChanged, onReconfig }:
  { doc: LibraryDocument; onChanged: () => void; onReconfig: (doc: LibraryDocument) => void }) {
  const cells = (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
        <span aria-hidden>📄</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13.5, fontWeight: 500,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{doc.filename}</div>
          {doc.progress?.page_count != null && (
            <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{doc.progress.page_count} pages</div>
          )}
        </div>
      </div>
      <StatusDot status={doc.status} />
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        {doc.corpora.length === 0 ? DASH : doc.corpora.map((c) => (
          <span key={c.id} style={{ fontSize: 11, background: "rgba(156,121,32,0.16)", borderRadius: 5,
            padding: "2px 8px", color: "var(--ink-muted)" }}>{c.name}</span>
        ))}
      </div>
      <div>{DASH}</div>
      <div>{doc.rating == null ? DASH : <MeterBar value={doc.rating} max={15} />}</div>
      <div style={{ textAlign: "right" }}>{DASH}</div>
    </>
  );
  const style = { display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center",
    padding: "15px 14px", color: "var(--ink)", textDecoration: "none" } as const;
  const indexing = doc.status === "indexing" || doc.status === "received";
  return (
    <div style={{ borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
      {/* Failed docs aren't navigable to a useful workbench view; render plain. */}
      {doc.status === "failed"
        ? <div style={style}>{cells}</div>
        : <Link to={`/documents/${doc.id}`} style={style}>{cells}</Link>}
      {/* Live build console so you can watch indexing without leaving the library. */}
      {indexing && (
        <div style={{ padding: "0 14px 14px" }}><BuildConsole progress={doc.progress} compact /></div>
      )}
      {doc.status === "failed" &&
        <FailedActions doc={doc} onChanged={onChanged} onReconfig={onReconfig} />}
    </div>
  );
}

function FailedActions({ doc, onChanged, onReconfig }:
  { doc: LibraryDocument; onChanged: () => void; onReconfig: (doc: LibraryDocument) => void }) {
  const { canWrite } = useAuth();
  const [busy, setBusy] = useState(false);
  const act = (fn: () => Promise<unknown>) => async () => {
    setBusy(true);
    try { await fn(); onChanged(); } finally { setBusy(false); }
  };
  const btn = { fontSize: 12, padding: "5px 12px", cursor: "pointer", borderRadius: 6,
    border: "1px solid var(--frame-rule)", background: "transparent", color: "var(--ink)" } as const;
  return (
    <div style={{ padding: "0 14px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
      {doc.error && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--oxblood)",
          background: "rgba(132,48,31,0.08)", border: "1px solid rgba(132,48,31,0.25)",
          borderRadius: 6, padding: "8px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word",
          maxHeight: 120, overflowY: "auto" }}>{doc.error}</div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button style={btn} disabled={!canWrite || busy}
          onClick={() => onReconfig(doc)}>Reconfig</button>
        <button style={btn} disabled={!canWrite || busy}
          onClick={act(() => api.rebuildDocument(doc.id))}>Retry</button>
        <button style={btn} disabled={!canWrite || busy}
          onClick={act(() => api.deleteDocument(doc.id))}>Delete</button>
      </div>
    </div>
  );
}

export default Documents;
