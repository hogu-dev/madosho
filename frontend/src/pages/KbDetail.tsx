import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Kb, KbDetail as KbDetailT, KbPage } from "../api/types";
import { Button, Card, Heading, Panel } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

const TYPES = ["summary", "concept", "entity"] as const;

const inputStyle = { fontSize: 13.5, fontFamily: "var(--font-ui)", padding: "8px 12px",
  borderRadius: 8, border: "1px solid var(--frame-rule)", background: "var(--card)" } as const;

// Tags are entered comma-separated; sources one per line. Both round-trip as
// string lists through the store's already-supported page fields.
const parseTags = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const parseSources = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const srcLabel = (s: unknown) => (typeof s === "string" ? s : JSON.stringify(s));

export function KbDetail() {
  const { canWrite } = useAuth();
  const navigate = useNavigate();
  const { kbId } = useParams<{ kbId: string }>();
  const id = Number(kbId);
  const [kb, setKb] = useState<KbDetailT | null>(null);
  const [kbs, setKbs] = useState<Kb[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<KbPage | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ description: "", body: "", tags: "", sources: "" });
  const [adding, setAdding] = useState(false);
  const [newPage, setNewPage] = useState(
    { type: "concept", title: "", description: "", tags: "", sources: "", body: "" });
  const [moving, setMoving] = useState(false);
  const [moveTo, setMoveTo] = useState<number | "">("");
  const [moveType, setMoveType] = useState<string>("concept");

  const load = useCallback(async () => {
    try { setKb(await api.getKb(id)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load knowledge base"); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.listKbs().then(setKbs).catch(() => setKbs([])); }, []);

  const view = async (slug: string) => {
    setError(null);
    try {
      const p = await api.getKbPage(id, slug);
      setOpen(p); setEditing(false); setMoving(false);
      setDraft({ description: p.description, body: p.body,
        tags: p.tags.join(", "), sources: p.sources.map(srcLabel).join("\n") });
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load page"); }
  };

  const saveEdit = async () => {
    if (!open) return;
    setError(null);
    try {
      await api.editKbPage(id, open.slug, { description: draft.description, body: draft.body,
        tags: parseTags(draft.tags), sources: parseSources(draft.sources) });
      await view(open.slug); await load(); setEditing(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save page"); }
  };

  const addPage = async () => {
    if (!newPage.title.trim()) return;
    setError(null);
    try {
      await api.addKbPage(id, { type: newPage.type, title: newPage.title,
        description: newPage.description, body: newPage.body,
        tags: parseTags(newPage.tags), sources: parseSources(newPage.sources) });
      setAdding(false);
      setNewPage({ type: "concept", title: "", description: "", tags: "", sources: "", body: "" });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add page"); }
  };

  const startMove = () => {
    if (!open) return;
    setMoveTo(id); setMoveType(open.type); setMoving(true); setEditing(false);
  };

  const doMove = async () => {
    if (!open || moveTo === "") return;
    setError(null);
    try {
      await api.moveKbPage(id, open.slug, { dest_kb_id: Number(moveTo), type: moveType });
      if (Number(moveTo) !== id) { navigate(`/knowledge-bases/${moveTo}`); return; }
      setMoving(false); await load(); await view(open.slug);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to move page"); }
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

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}

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

          {adding && (
            <Card style={{ display: "grid", gap: 8, maxWidth: 640, margin: "12px 0 20px" }}>
              <select value={newPage.type} aria-label="Page type"
                onChange={(e) => setNewPage({ ...newPage, type: e.target.value })}
                style={inputStyle}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input placeholder="Title" value={newPage.title} style={inputStyle} aria-label="Page title"
                onChange={(e) => setNewPage({ ...newPage, title: e.target.value })} />
              <input placeholder="Description" value={newPage.description} style={inputStyle}
                aria-label="Page description"
                onChange={(e) => setNewPage({ ...newPage, description: e.target.value })} />
              <input placeholder="Tags (comma-separated)" value={newPage.tags} style={inputStyle}
                aria-label="Page tags"
                onChange={(e) => setNewPage({ ...newPage, tags: e.target.value })} />
              <textarea placeholder="Sources (one per line)" rows={3} value={newPage.sources}
                aria-label="Page sources"
                style={{ ...inputStyle, fontFamily: "var(--font-mono)", resize: "vertical" }}
                onChange={(e) => setNewPage({ ...newPage, sources: e.target.value })} />
              <textarea placeholder="Body" rows={6} value={newPage.body} aria-label="Page body"
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
                  {open.tags.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "10px 0 0" }}>
                      {open.tags.map((t) => (
                        <span key={t} style={{ fontFamily: "var(--font-mono)", fontSize: 11.5,
                          padding: "2px 8px", borderRadius: 999, background: "var(--code-bg)",
                          border: "1px solid var(--frame-rule)", color: "var(--ink-muted)" }}>{t}</span>
                      ))}
                    </div>
                  )}
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--font-mono)", fontSize: 12.5,
                    lineHeight: 1.6, margin: "16px 0 0", color: "var(--ink)" }}>{open.body}</pre>
                  {open.sources.length > 0 && (
                    <div style={{ margin: "16px 0 0" }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em",
                        textTransform: "uppercase", color: "var(--ink-faint)", marginBottom: 4 }}>
                        Sources
                      </div>
                      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--ink-muted)" }}>
                        {open.sources.map((s, i) => (
                          <li key={i} style={{ fontFamily: "var(--font-mono)" }}>{srcLabel(s)}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {canWrite && !moving && (
                    <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                      <Button variant="ghost" onClick={() => setEditing(true)}>Edit</Button>
                      <Button variant="ghost" onClick={startMove}>Move</Button>
                    </div>
                  )}
                  {canWrite && moving && (
                    <div style={{ marginTop: 16, display: "grid", gap: 8, maxWidth: 360 }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.08em",
                        textTransform: "uppercase", color: "var(--ink-faint)" }}>Move page</div>
                      <select value={moveTo} aria-label="Target knowledge base" style={inputStyle}
                        onChange={(e) => setMoveTo(Number(e.target.value))}>
                        {kbs.map((k) => (
                          <option key={k.id} value={k.id}>
                            {k.name}{k.id === id ? " (this KB)" : ` - ${k.corpus_name}`}
                          </option>
                        ))}
                      </select>
                      <select value={moveType} aria-label="Target type" style={inputStyle}
                        onChange={(e) => setMoveType(e.target.value)}>
                        {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <div style={{ display: "flex", gap: 8 }}>
                        <Button onClick={doMove}
                          disabled={moveTo === "" || (Number(moveTo) === id && moveType === open.type)}>
                          Move
                        </Button>
                        <Button variant="ghost" onClick={() => setMoving(false)}>Cancel</Button>
                      </div>
                    </div>
                  )}
                </Card>
              )}
              {open && editing && (
                <Card style={{ display: "grid", gap: 8 }}>
                  <Heading level={2} style={{ margin: 0 }}>{open.title}</Heading>
                  <input value={draft.description} style={inputStyle} aria-label="Edit description"
                    onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                  <input value={draft.tags} style={inputStyle} aria-label="Edit tags"
                    placeholder="Tags (comma-separated)"
                    onChange={(e) => setDraft({ ...draft, tags: e.target.value })} />
                  <textarea rows={3} value={draft.sources} aria-label="Edit sources"
                    placeholder="Sources (one per line)"
                    style={{ ...inputStyle, fontFamily: "var(--font-mono)", resize: "vertical" }}
                    onChange={(e) => setDraft({ ...draft, sources: e.target.value })} />
                  <textarea rows={10} value={draft.body} aria-label="Edit body"
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
