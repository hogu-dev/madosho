import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Corpus, CorpusMember } from "../api/types";
import { Button, Heading, Panel, StatusDot } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

export function Corpora() {
  const { canWrite } = useAuth();
  const [corpora, setCorpora] = useState<Corpus[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setCorpora(await api.listCorpora()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load corpora"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    try { await api.createCorpus(n); setName(""); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to create corpus"); }
    finally { setBusy(false); }
  };

  const list = corpora ?? [];

  return (
    <Panel style={{ padding: "30px 32px" }}>
      <Heading level={1} style={{ margin: 0 }}>Corpora</Heading>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 0", maxWidth: 560,
        lineHeight: 1.55 }}>
        Collections that reference documents. A corpus never re-indexes a document — it points at
        documents already in the library and chooses, per document, which pipeline to query through.
      </p>

      {canWrite && (
        <div style={{ display: "flex", gap: 10, margin: "22px 0 4px", alignItems: "center" }}>
          <input value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }}
            placeholder="New corpus name" aria-label="New corpus name"
            style={{ fontSize: 13.5, fontFamily: "var(--font-ui)", padding: "8px 12px", borderRadius: 8,
              border: "1px solid var(--frame-rule)", background: "var(--card)", minWidth: 240 }} />
          <Button onClick={create} disabled={busy || !name.trim()}>+ Create corpus</Button>
        </div>
      )}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {corpora === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {corpora !== null && list.length === 0 && !error && (
        <div style={{ marginTop: 28, border: "1.5px dashed rgba(120,95,40,0.42)", borderRadius: 14,
          padding: "48px 40px", textAlign: "center", background: "rgba(252,247,237,0.25)" }}>
          <div style={{ fontSize: 36, opacity: 0.7 }} aria-hidden>📚</div>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 500,
            marginTop: 14 }}>No corpora yet</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.6,
            margin: "10px auto 0", maxWidth: 380 }}>
            Create one above, then add documents to it from your library.</p>
        </div>
      )}

      {list.length > 0 && (
        <div style={{ marginTop: 18 }}>
          {list.map((c) => <CorpusRow key={c.id} corpus={c} />)}
        </div>
      )}
    </Panel>
  );
}

function CorpusRow({ corpus }: { corpus: Corpus }) {
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<CorpusMember[] | null>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && members === null) {
      api.listCorpusMembers(corpus.id).then(setMembers).catch(() => setMembers([]));
    }
  };

  return (
    <div style={{ borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "15px 14px" }}>
        <button onClick={toggle} aria-label={open ? `Collapse ${corpus.name}` : `Expand ${corpus.name}`}
          style={{ display: "flex", alignItems: "center", gap: 11, background: "none", border: "none",
            cursor: "pointer", color: "var(--ink)", padding: 0, flex: 1, textAlign: "left" }}>
          <span aria-hidden style={{ color: "var(--ink-faint)", fontSize: 11, width: 12,
            transform: open ? "none" : "rotate(-90deg)", transition: "transform 0.12s" }}>▾</span>
          <span aria-hidden>📚</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 500 }}>{corpus.name}</span>
          {members !== null && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-faint)" }}>
              {members.length} document{members.length === 1 ? "" : "s"}</span>)}
        </button>
        <Link to={`/corpora/${corpus.id}`}
          style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--gilt)",
            textDecoration: "none" }}>Open →</Link>
      </div>

      {open && (
        <div style={{ padding: "0 0 12px 37px" }}>
          {members === null && (
            <p style={{ fontSize: 12, color: "var(--ink-faint)", margin: "2px 0 6px" }}>Loading…</p>)}
          {members !== null && members.length === 0 && (
            <p style={{ fontSize: 12.5, color: "var(--ink-faint)", margin: "2px 0 6px" }}>
              No documents in this corpus yet.</p>)}
          {(members ?? []).map((m) => (
            <Link key={m.document_id} to={`/documents/${m.document_id}`}
              style={{ display: "flex", alignItems: "center", gap: 9, padding: "5px 0",
                textDecoration: "none", color: "var(--ink)" }}>
              <span aria-hidden>📄</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, flex: 1, minWidth: 0,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.filename}</span>
              <StatusDot status={m.status} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default Corpora;
