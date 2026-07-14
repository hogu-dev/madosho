import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { KbDetail as KbDetailT, KbPage } from "../api/types";
import { Button, Card, Heading, Panel } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

const TYPES = ["summary", "concept", "entity"] as const;

const inputStyle = { fontSize: 13.5, fontFamily: "var(--font-ui)", padding: "8px 12px",
  borderRadius: 8, border: "1px solid var(--frame-rule)", background: "var(--card)" } as const;

export function KbDetail() {
  const { canWrite } = useAuth();
  const { kbId } = useParams<{ kbId: string }>();
  const id = Number(kbId);
  const [kb, setKb] = useState<KbDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<KbPage | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ description: "", body: "" });
  const [adding, setAdding] = useState(false);
  const [newPage, setNewPage] = useState({ type: "concept", title: "", description: "", body: "" });

  const load = useCallback(async () => {
    try { setKb(await api.getKb(id)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load knowledge base"); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const view = async (slug: string) => {
    setError(null);
    try {
      const p = await api.getKbPage(id, slug);
      setOpen(p); setEditing(false); setDraft({ description: p.description, body: p.body });
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load page"); }
  };

  const saveEdit = async () => {
    if (!open) return;
    setError(null);
    try { await api.editKbPage(id, open.slug, draft); await view(open.slug); await load(); setEditing(false); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to save page"); }
  };

  const addPage = async () => {
    if (!newPage.title.trim()) return;
    setError(null);
    try {
      await api.addKbPage(id, newPage);
      setAdding(false); setNewPage({ type: "concept", title: "", description: "", body: "" });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add page"); }
  };

  if (!kb && !error) return (
    <Panel style={{ padding: "28px 32px" }}>
      <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>
    </Panel>
  );

  return (
    <Panel style={{ padding: "28px 32px" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, marginBottom: 16 }}>
        <Link to="/knowledge-bases" style={{ color: "var(--ink-muted)", textDecoration: "none" }}>
          Knowledge bases</Link>
        <span style={{ color: "var(--ink-faint)" }}> / </span>
        <span style={{ color: "var(--ink)" }}>{kb?.name ?? "…"}</span>
      </div>

      {kb && (
        <>
          <Heading level={1} style={{ margin: 0 }}>{kb.name}</Heading>
          <p style={{ fontSize: 13, color: "var(--ink-faint)", margin: "6px 0 0" }}>
            Attached to{" "}
            <Link to={`/corpora/${kb.corpus_id}`} style={{ color: "var(--ink-muted)" }}>
              {kb.corpus_name}
            </Link>
          </p>

          {canWrite && (
            <div style={{ margin: "18px 0 4px" }}>
              <Button variant="ghost" onClick={() => setAdding((v) => !v)}>
                {adding ? "Cancel" : "+ Add page"}
              </Button>
            </div>
          )}

          {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}

          {adding && (
            <Card style={{ display: "grid", gap: 8, maxWidth: 640, margin: "12px 0 20px" }}>
              <select value={newPage.type}
                onChange={(e) => setNewPage({ ...newPage, type: e.target.value })}
                style={inputStyle}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input placeholder="Title" value={newPage.title} style={inputStyle}
                onChange={(e) => setNewPage({ ...newPage, title: e.target.value })} />
              <input placeholder="Description" value={newPage.description} style={inputStyle}
                onChange={(e) => setNewPage({ ...newPage, description: e.target.value })} />
              <textarea placeholder="Body" rows={6} value={newPage.body}
                style={{ ...inputStyle, fontFamily: "var(--font-mono)", resize: "vertical" }}
                onChange={(e) => setNewPage({ ...newPage, body: e.target.value })} />
              <div>
                <Button onClick={addPage} disabled={!newPage.title.trim()}>Save page</Button>
              </div>
            </Card>
          )}

          <div style={{ display: "flex", gap: 24, marginTop: adding ? 0 : 18, alignItems: "flex-start" }}>
            <div style={{ minWidth: 220, flex: "0 0 220px" }}>
              {TYPES.map((t) => {
                const rows = kb.pages.filter((p) => p.type === t);
                if (!rows.length) return null;
                return (
                  <div key={t} style={{ marginBottom: 16 }}>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em",
                      textTransform: "uppercase", color: "var(--ink-faint)", marginBottom: 4 }}>
                      {t}
                    </div>
                    {rows.map((p) => (
                      <button key={p.slug} onClick={() => view(p.slug)}
                        style={{ display: "block", width: "100%", textAlign: "left", background: "none",
                          border: "none", cursor: "pointer", padding: "6px 0",
                          fontFamily: "var(--font-mono)", fontSize: 13,
                          color: open?.slug === p.slug ? "var(--gilt)" : "var(--ink)" }}>
                        {p.title}
                      </button>
                    ))}
                  </div>
                );
              })}
              {kb.pages.length === 0 && (
                <p style={{ fontSize: 12.5, color: "var(--ink-faint)" }}>
                  No pages yet - add one above.
                </p>
              )}
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              {!open && (
                <p style={{ fontSize: 13, color: "var(--ink-faint)" }}>
                  Pick a page on the left to view it.
                </p>
              )}
              {open && !editing && (
                <Card>
                  <Heading level={2} style={{ margin: 0 }}>{open.title}</Heading>
                  <p style={{ fontStyle: "italic", color: "var(--ink-muted)", fontSize: 13.5,
                    margin: "8px 0 0" }}>{open.description}</p>
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", fontSize: 12.5,
                    lineHeight: 1.6, margin: "16px 0 0", color: "var(--ink)" }}>{open.body}</pre>
                  {canWrite && (
                    <div style={{ marginTop: 16 }}>
                      <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
                    </div>
                  )}
                </Card>
              )}
              {open && editing && (
                <Card style={{ display: "grid", gap: 8 }}>
                  <Heading level={2} style={{ margin: 0 }}>{open.title}</Heading>
                  <input value={draft.description} style={inputStyle}
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                  <textarea rows={10} value={draft.body}
                    style={{ ...inputStyle, fontFamily: "var(--font-mono)", resize: "vertical" }}
                    onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
                  <div style={{ display: "flex", gap: 8 }}>
                    <Button onClick={saveEdit}>Save</Button>
                    <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}

export default KbDetail;
