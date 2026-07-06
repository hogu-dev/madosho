import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Corpus, CorpusMember, CorpusMemberPipeline, LibraryDocument } from "../api/types";
import { Heading, Panel, StatusDot } from "../design/primitives";
import { usePolling } from "../hooks/usePolling";
import { useAuth } from "../auth/AuthContext";

const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>—</span>;

const indexedPipes = (m: CorpusMember) => m.pipelines.filter((p) => p.status === "indexed");

type SaveState = "idle" | "saving" | "saved" | "error";

/** Checkbox that can show the third "indeterminate" state (set via ref, not a prop). */
function TriCheckbox({ checked, indeterminate, disabled, onChange, ariaLabel }: {
  checked: boolean; indeterminate: boolean; disabled?: boolean;
  onChange: () => void; ariaLabel: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = indeterminate && !checked; },
    [indeterminate, checked]);
  return (
    <input ref={ref} type="checkbox" aria-label={ariaLabel} checked={checked}
      disabled={disabled} onChange={onChange}
      style={{ width: 15, height: 15, cursor: disabled ? "default" : "pointer", accentColor: "var(--oxblood)" }} />
  );
}

export function CorpusDetail() {
  const { canWrite } = useAuth();
  const { corpusId } = useParams<{ corpusId: string }>();
  const cid = Number(corpusId);
  const [corpus, setCorpus] = useState<Corpus | null>(null);
  const [members, setMembers] = useState<CorpusMember[] | null>(null);
  const [library, setLibrary] = useState<LibraryDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Selection state, document_id -> chosen pipeline ids. Seeded from the server on every
  // members refetch (server is source of truth); toggles update it optimistically first.
  const [sel, setSel] = useState<Record<number, number[]>>({});
  const [saveState, setSaveState] = useState<Record<number, SaveState>>({});
  const [expanded, setExpanded] = useState<Set<number>>(new Set());   // collapsed by default

  const load = useCallback(async () => {
    try { setMembers(await api.listCorpusMembers(cid)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load corpus"); }
  }, [cid]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.listCorpora().then((cs) => setCorpus(cs.find((c) => c.id === cid) ?? null)).catch(() => {});
  }, [cid]);
  const loadLibrary = useCallback(() => {
    api.listLibraryDocuments().then(setLibrary).catch(() => setLibrary([]));
  }, []);
  useEffect(() => { loadLibrary(); }, [loadLibrary]);

  const list = members ?? [];
  useEffect(() => {
    if (members) setSel(Object.fromEntries(members.map((m) => [m.document_id, m.selected_pipeline_ids])));
  }, [members]);

  const working = list.some((m) => m.status === "indexing" || m.status === "received");
  usePolling(load, 2500, working);   // a member still indexing keeps the picker fresh

  const memberIds = new Set(list.map((m) => m.document_id));
  const addable = library.filter((d) => !memberIds.has(d.id));

  const selectedFor = (m: CorpusMember) => sel[m.document_id] ?? m.selected_pipeline_ids ?? [];

  const addDoc = async (docId: number) => { await api.addMembership(cid, docId); load(); };
  const removeDoc = async (docId: number) => { await api.removeMembership(cid, docId); load(); };

  // Write one document's selection: optimistic local update, then PUT. The full set is
  // sent each time (not a delta). saveState tracks the outcome per document so the row
  // can show Saving / Saved / Failed -- the optimistic edit stays visible on failure and
  // is flagged unsaved so a Retry re-sends it. Returns whether the write succeeded.
  const writeSelection = async (docId: number, ids: number[]): Promise<boolean> => {
    setSel((prev) => ({ ...prev, [docId]: ids }));
    setSaveState((prev) => ({ ...prev, [docId]: "saving" }));
    try {
      await api.setCorpusDocumentPipelines(cid, docId, ids);
      setSaveState((prev) => ({ ...prev, [docId]: "saved" }));
      window.setTimeout(() => setSaveState((prev) =>      // let "Saved" linger, then fade
        prev[docId] === "saved" ? { ...prev, [docId]: "idle" } : prev), 1600);
      return true;
    } catch {
      setSaveState((prev) => ({ ...prev, [docId]: "error" }));
      return false;
    }
  };
  const persist = async (docId: number, ids: number[]) => {
    if (await writeSelection(docId, ids)) load();      // reseed from server only on success
  };
  const togglePipeline = (m: CorpusMember, pid: number) => {
    const cur = selectedFor(m);
    persist(m.document_id, cur.includes(pid) ? cur.filter((x) => x !== pid) : [...cur, pid]);
  };
  const toggleDoc = (m: CorpusMember) => {
    const all = indexedPipes(m).map((p) => p.id);
    const cur = selectedFor(m).filter((id) => all.includes(id));
    persist(m.document_id, cur.length === all.length ? [] : all);
  };

  // Master "select all": every indexed pipeline of every member, or clear them all.
  const everySelectable = list.flatMap((m) => indexedPipes(m).map((p) => ({ docId: m.document_id, pid: p.id })));
  const everySelected = everySelectable.filter((e) => selectedFor(list.find((m) => m.document_id === e.docId)!).includes(e.pid));
  const allChecked = everySelectable.length > 0 && everySelected.length === everySelectable.length;
  const someChecked = everySelected.length > 0 && !allChecked;
  const toggleAll = async () => {
    const target = allChecked ? [] : null;   // null = "select all this doc's indexed pipelines"
    const next = list.map((m) => ({ docId: m.document_id, ids: target ?? indexedPipes(m).map((p) => p.id) }));
    const results = await Promise.all(next.map((n) => writeSelection(n.docId, n.ids)));
    if (results.some(Boolean)) load();
  };

  return (
    <Panel style={{ padding: "28px 32px" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, marginBottom: 16 }}>
        <Link to="/corpora" style={{ color: "var(--ink-muted)", textDecoration: "none" }}>Corpora</Link>
        <span style={{ color: "var(--ink-faint)" }}> / </span>
        <span style={{ color: "var(--ink)" }}>{corpus?.name ?? "…"}</span>
      </div>

      <Heading level={1} style={{ margin: 0 }}>{corpus?.name ?? "Corpus"}</Heading>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 0", maxWidth: 640,
        lineHeight: 1.55 }}>
        Documents in this corpus, and the pipelines each is queried through. Check one or more
        pipelines per document to query through all of them at once (their results are merged); leave
        a document with nothing checked to use its <em>default</em> (highest-rated) pipeline.
      </p>

      {canWrite && (
        <div style={{ display: "flex", gap: 10, margin: "20px 0 4px", alignItems: "center" }}>
          {addable.length > 0 ? (
            <select aria-label="Add document" value="" onChange={(e) => {
              if (e.target.value) addDoc(Number(e.target.value)); }}
              style={{ fontSize: 13, fontFamily: "var(--font-ui)", color: "var(--ink-muted)",
                background: "var(--card)", border: "1px dashed rgba(120,95,40,0.4)", borderRadius: 8,
                padding: "8px 12px", cursor: "pointer", minWidth: 260 }}>
              <option value="">+ Add a document from the library</option>
              {addable.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
          ) : (
            <span style={{ fontSize: 12.5, color: "var(--ink-faint)", fontFamily: "var(--font-ui)" }}>
              Every library document is already in this corpus. Upload more on the{" "}
              <Link to="/documents" style={{ color: "var(--ink-muted)" }}>Documents</Link> page.
            </span>
          )}
        </div>
      )}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {members === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {members !== null && list.length === 0 && !error && (
        <div style={{ marginTop: 26, border: "1.5px dashed rgba(120,95,40,0.42)", borderRadius: 14,
          padding: "44px 40px", textAlign: "center", background: "rgba(252,247,237,0.25)" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 19, fontWeight: 500 }}>
            No documents in this corpus yet</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.6,
            margin: "10px auto 0", maxWidth: 360 }}>
            {addable.length > 0 ? "Add one from your library above."
              : "Upload documents on the Documents page first, then add them here."}</p>
        </div>
      )}

      {list.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
            borderBottom: "1px solid var(--frame-rule)" }}>
            <TriCheckbox ariaLabel="Select all pipelines" checked={allChecked}
              indeterminate={someChecked} disabled={!canWrite || everySelectable.length === 0}
              onChange={toggleAll} />
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
              textTransform: "uppercase", color: "var(--ink-faint)" }}>
              Select all · {everySelected.length}/{everySelectable.length} pipelines
            </span>
          </div>
          {list.map((m) => (
            <MemberNode key={m.document_id} member={m} canWrite={canWrite}
              selected={selectedFor(m)} collapsed={!expanded.has(m.document_id)}
              onToggleCollapse={() => setExpanded((prev) => {
                const next = new Set(prev);
                next.has(m.document_id) ? next.delete(m.document_id) : next.add(m.document_id);
                return next;
              })}
              onToggleDoc={() => toggleDoc(m)}
              onTogglePipeline={(pid) => togglePipeline(m, pid)}
              saveState={saveState[m.document_id] ?? "idle"}
              onRetry={() => persist(m.document_id, selectedFor(m))}
              onRemove={() => removeDoc(m.document_id)} />
          ))}
        </div>
      )}
    </Panel>
  );
}

function MemberNode({ member, canWrite, selected, collapsed, onToggleCollapse, onToggleDoc,
  onTogglePipeline, saveState, onRetry, onRemove }: {
    member: CorpusMember; canWrite: boolean; selected: number[]; collapsed: boolean;
    onToggleCollapse: () => void; onToggleDoc: () => void;
    onTogglePipeline: (pid: number) => void; saveState: SaveState;
    onRetry: () => void; onRemove: () => void }) {
  const indexed = indexedPipes(member);
  const allIds = indexed.map((p) => p.id);
  const chosen = selected.filter((id) => allIds.includes(id));
  const docChecked = allIds.length > 0 && chosen.length === allIds.length;
  const docSome = chosen.length > 0 && !docChecked;
  const defaultName = member.pipelines.find((p) => p.id === member.default_pipeline_id)?.name;

  const summary = indexed.length === 0
    ? "indexing…"
    : chosen.length === 0
      ? `Default${defaultName ? ` — ${defaultName}` : " — highest rated"}`
      : `${chosen.length} pipeline${chosen.length === 1 ? "" : "s"} selected`;

  return (
    <div style={{ borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 14px" }}>
        <button onClick={onToggleCollapse} aria-label={collapsed ? "Expand" : "Collapse"}
          disabled={indexed.length === 0}
          style={{ background: "none", border: "none", cursor: indexed.length === 0 ? "default" : "pointer",
            color: "var(--ink-faint)", fontSize: 11, width: 14, padding: 0,
            transform: collapsed ? "rotate(-90deg)" : "none", transition: "transform 0.12s" }}>▾</button>
        <TriCheckbox ariaLabel={`Select all pipelines for ${member.filename}`} checked={docChecked}
          indeterminate={docSome} disabled={!canWrite || indexed.length === 0} onChange={onToggleDoc} />
        <Link to={`/documents/${member.document_id}`} style={{ display: "flex", alignItems: "center",
          gap: 9, minWidth: 0, textDecoration: "none", color: "var(--ink)", flex: 1 }}>
          <span aria-hidden>📄</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 13.5, fontWeight: 500,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{member.filename}</span>
        </Link>
        <span onClick={indexed.length > 0 ? onToggleCollapse : undefined}
          title={indexed.length > 0 ? (collapsed ? "Show pipelines" : "Hide pipelines") : undefined}
          style={{ fontSize: 11.5, fontFamily: "var(--font-mono)",
            color: chosen.length === 0 ? "var(--ink-faint)" : "var(--ink-muted)", whiteSpace: "nowrap",
            cursor: indexed.length > 0 ? "pointer" : "default" }}>
          {summary}</span>
        <SaveBadge state={saveState} onRetry={onRetry} />
        <StatusDot status={member.status} />
        {canWrite
          ? <button onClick={onRemove} title="Remove from corpus"
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-faint)",
                fontSize: 13, padding: "4px 6px" }}>✕</button>
          : DASH}
      </div>

      {!collapsed && indexed.length > 0 && (
        <div style={{ padding: "2px 0 12px 50px" }}>
          {indexed.map((p) => (
            <PipelineLeaf key={p.id} pipeline={p} docLabel={member.filename} canWrite={canWrite}
              checked={selected.includes(p.id)} onToggle={() => onTogglePipeline(p.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Per-document save feedback for the auto-save model: Saving / Saved / Failed-retry. */
function SaveBadge({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  const base = { fontFamily: "var(--font-mono)", fontSize: 10.5, whiteSpace: "nowrap" as const };
  if (state === "saving")
    return <span style={{ ...base, color: "var(--ink-faint)" }}>Saving…</span>;
  if (state === "saved")
    return <span style={{ ...base, color: "var(--ink-muted)" }}>Saved ✓</span>;
  if (state === "error")
    return (
      <button onClick={onRetry} title="Save failed — click to retry"
        style={{ ...base, color: "var(--oxblood)", background: "none", border: "none",
          cursor: "pointer", padding: 0, textDecoration: "underline" }}>
        Not saved — retry</button>);
  return <span style={{ width: 1 }} aria-hidden />;   // idle: hold the slot, no flicker
}

function PipelineLeaf({ pipeline, docLabel, canWrite, checked, onToggle }: {
  pipeline: CorpusMemberPipeline; docLabel: string; canWrite: boolean;
  checked: boolean; onToggle: () => void }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0",
      cursor: canWrite ? "pointer" : "default" }}>
      <TriCheckbox ariaLabel={`Pipeline ${pipeline.name} for ${docLabel}`} checked={checked}
        indeterminate={false} disabled={!canWrite} onChange={onToggle} />
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, color: "var(--ink)" }}>
        {pipeline.name}</span>
      {pipeline.is_default && (
        <span style={{ fontSize: 10.5, color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>
          (original)</span>)}
      {pipeline.rating != null && (
        <span style={{ fontSize: 10.5, color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>
          ★ {pipeline.rating.toFixed(1)}</span>)}
    </label>
  );
}

export default CorpusDetail;
