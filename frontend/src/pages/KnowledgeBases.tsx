import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Corpus, Kb } from "../api/types";
import { Button, Heading, Panel } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

export function KnowledgeBases() {
  const { canWrite } = useAuth();
  const [kbs, setKbs] = useState<Kb[] | null>(null);
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpusId, setCorpusId] = useState<number | "">("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setKbs(await api.listKbs()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load knowledge bases"); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.listCorpora().then(setCorpora).catch(() => setCorpora([])); }, []);

  const create = async () => {
    const n = name.trim();
    if (!corpusId || !n) return;
    setBusy(true);
    try { await api.createKb(Number(corpusId), n); setName(""); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to create knowledge base"); }
    finally { setBusy(false); }
  };

  const list = kbs ?? [];
  const byCorpus = corpora
    .map((c) => ({ corpus: c, items: list.filter((k) => k.corpus_id === c.id) }))
    .filter((g) => g.items.length > 0);

  return (
    <Panel style={{ padding: "30px 32px" }}>
      <Heading level={1} style={{ margin: 0 }}>Knowledge bases</Heading>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 0", maxWidth: 560,
        lineHeight: 1.55 }}>
        Curated wikis attached to a corpus - summary, concept, and entity pages an agent can grow
        while it works a goal, or you can write and edit by hand.
      </p>

      {canWrite && (
        <div style={{ display: "flex", gap: 10, margin: "22px 0 4px", alignItems: "center" }}>
          <select value={corpusId} aria-label="Corpus"
            onChange={(e) => setCorpusId(e.target.value ? Number(e.target.value) : "")}
            style={{ fontSize: 13.5, fontFamily: "var(--font-ui)", padding: "8px 12px", borderRadius: 8,
              border: "1px solid var(--frame-rule)", background: "var(--card)", minWidth: 180 }}>
            <option value="">Corpus...</option>
            {corpora.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <input value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }}
            placeholder="New knowledge base name" aria-label="New knowledge base name"
            style={{ fontSize: 13.5, fontFamily: "var(--font-ui)", padding: "8px 12px", borderRadius: 8,
              border: "1px solid var(--frame-rule)", background: "var(--card)", minWidth: 240 }} />
          <Button onClick={create} disabled={busy || !corpusId || !name.trim()}>+ Create KB</Button>
        </div>
      )}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {kbs === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {kbs !== null && list.length === 0 && !error && (
        <div style={{ marginTop: 28, border: "1.5px dashed rgba(120,95,40,0.42)", borderRadius: 14,
          padding: "48px 40px", textAlign: "center", background: "rgba(252,247,237,0.25)" }}>
          <div style={{ fontSize: 36, opacity: 0.7 }} aria-hidden>📖</div>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 500,
            marginTop: 14 }}>No knowledge bases yet</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.6,
            margin: "10px auto 0", maxWidth: 380 }}>
            Create one above, attached to a corpus.</p>
        </div>
      )}

      {byCorpus.length > 0 && (
        <div style={{ marginTop: 18 }}>
          {byCorpus.map((g) => (
            <div key={g.corpus.id} style={{ marginBottom: 22 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em",
                textTransform: "uppercase", color: "var(--ink-faint)", padding: "0 14px 6px" }}>
                {g.corpus.name}
              </div>
              {g.items.map((k) => (
                <div key={k.id} style={{ display: "flex", alignItems: "center",
                  justifyContent: "space-between", padding: "13px 14px",
                  borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 9 }}>
                    <span aria-hidden>📖</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 13.5,
                      fontWeight: 500 }}>{k.name}</span>
                  </span>
                  <Link to={`/knowledge-bases/${k.id}`}
                    style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--gilt)",
                      textDecoration: "none" }}>Open →</Link>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default KnowledgeBases;
