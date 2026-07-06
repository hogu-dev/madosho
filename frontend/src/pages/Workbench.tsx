import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Document, DocPipeline, Corpus, Components, RecommendedPipeline, LlmEndpoint } from "../api/types";
import { Panel, Heading, Button, StatusDot, SegmentScore } from "../design/primitives";
import { ConfirmDialog } from "../design/ConfirmDialog";
import { usePolling } from "../hooks/usePolling";
import { recipeErrors, defaultRecipe, componentLabel, suggestPipelineName } from "../lib/recipe";
import { ContextualLlmSelect } from "./ContextualLlmSelect";
import { VisionLlmSelect } from "./VisionLlmSelect";
import { BuildConsole } from "./BuildConsole";
import { optionFields, changedOptions } from "../lib/optionsForm";
import { useAuth } from "../auth/AuthContext";

const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>—</span>;
const fmtRating = (v: number) => Number.isInteger(v) ? v : v.toFixed(1);
const fmtCreated = (iso?: string) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined,
    { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};
const SLOT_ORDER = ["extract", "chunk", "index"] as const;
const SLOT_LABEL: Record<string, string> = { extract: "Extract", chunk: "Chunk", index: "Index" };

export function Workbench() {
  const { canWrite } = useAuth();
  const navigate = useNavigate();
  const { documentId } = useParams<{ documentId: string }>();
  const id = Number(documentId);
  const [doc, setDoc] = useState<Document | null>(null);
  const [pipes, setPipes] = useState<DocPipeline[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [d, p] = await Promise.all([api.getDocument(id), api.getDocumentPipelines(id)]);
      setDoc(d); setPipes(p); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load document"); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const [allCorpora, setAllCorpora] = useState<Corpus[]>([]);
  useEffect(() => { api.listCorpora().then(setAllCorpora).catch(() => setAllCorpora([])); }, []);

  const setEffective = async (pipelineId: number) => { await api.setSelectedPipeline(id, pipelineId); load(); };
  const removeMember = async (corpusId: number) => { await api.removeMembership(corpusId, id); load(); };
  const addMember = async (corpusId: number) => { await api.addMembership(corpusId, id); load(); };

  // Delete-document confirm: removes the document AND every pipeline built on it
  // (the backend cascades + defers the vector/blob cleanup), then leaves for the
  // library. canWrite gates the button; the backend also 403s a read-only caller.
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const deleteDocument = async () => {
    setDeleting(true);
    try { await api.deleteDocument(id); navigate("/documents"); }
    finally { setDeleting(false); setConfirmDelete(false); }
  };

  const [recommended, setRecommended] = useState<RecommendedPipeline | null>(null);
  const [components, setComponents] = useState<Components | null>(null);
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [recipe, setRecipe] = useState<{ name: string; parser?: string; chunker?: string;
    embedder?: string; options: Record<string, Record<string, unknown>> }>(
    { name: "", options: {} });
  const [busy, setBusy] = useState(false);
  // The last name we auto-filled. The suggestion effect only ever replaces an empty
  // field or this exact prior suggestion, so it can NEVER clobber a name the user
  // typed -- regardless of how the async component load and keystrokes interleave.
  const lastSuggested = useRef("");

  useEffect(() => { api.getRecommendedPipeline(id).then(setRecommended).catch(() => setRecommended(null)); }, [id]);
  useEffect(() => { api.listLlmEndpoints().then(setEndpoints).catch(() => setEndpoints([])); }, []);
  useEffect(() => {
    if (!formOpen || components) return;
    api.components().then((c) => {
      setComponents(c);
      setRecipe((r) => ({ ...r, ...defaultRecipe(c) }));   // canonical docling + docling-hybrid stack
    }).catch(() => setComponents({}));
  }, [formOpen, components]);

  // Auto-suggest a collision-free pipeline name (the build endpoint is idempotent
  // by name, so a duplicate would silently reuse the existing pipeline instead of
  // building the new recipe). Re-runs as the extractor changes, but only fills an
  // empty field or its own prior suggestion -- never a name the user has typed.
  useEffect(() => {
    if (!formOpen || !doc || !components) return;
    const taken = (pipes ?? []).map((p) => p.name);
    const suggested = suggestPipelineName(doc.filename, recipe.parser, taken);
    setRecipe((r) => {
      if (r.name !== "" && r.name !== lastSuggested.current) return r;   // user-authored: leave it
      lastSuggested.current = suggested;
      return r.name === suggested ? r : { ...r, name: suggested };
    });
  }, [formOpen, doc, components, recipe.parser, pipes]);

  const createPipeline = async () => {
    setBusy(true);
    try {
      const slotOptions: Record<string, Record<string, unknown>> = {};
      for (const kind of ["parser", "chunker", "embedder"] as const) {
        const name = recipe[kind];
        const schema = components?.[kind]?.find((c) => c.name === name)?.options_schema;
        const fields = optionFields(schema);
        const changed = changedOptions(recipe.options[kind] ?? {}, fields);
        if (Object.keys(changed).length) slotOptions[kind] = changed;
      }
      await api.createPipeline(id, { name: recipe.name, parser: recipe.parser,
        chunker: recipe.chunker, embedder: recipe.embedder, options: slotOptions });
      setFormOpen(false); setRecipe({ name: "", options: {} }); lastSuggested.current = ""; load();
    } finally { setBusy(false); }
  };

  const slotErrors = recipeErrors(recipe, components, endpoints.length,
    endpoints.filter((e) => e.supports_vision).length);   // re-validated every render
  const recipeOk = Object.keys(slotErrors).length === 0;

  // Newest pipeline first: a fresh build lands at the top of the list instead of
  // the bottom (id is monotonic, so higher id == created later). Copy before sort
  // so we never mutate the state array in place.
  const list = [...(pipes ?? [])].sort((a, b) => b.id - a.id);
  const building = list.some((p) => p.status === "building")
    || doc?.status === "indexing" || doc?.status === "received";
  usePolling(load, 2500, building);
  const effCount = list.filter((p) => p.effective).length;

  const memberIds = useMemo(() => new Set((doc?.corpora ?? []).map((c) => c.id)), [doc]);
  const addable = useMemo(() => allCorpora.filter((c) => !memberIds.has(c.id)), [allCorpora, memberIds]);

  return (
    <Panel style={{ padding: "28px 32px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
        fontFamily: "var(--font-mono)", fontSize: 12, marginBottom: 18 }}>
        <span>
          <Link to="/documents" style={{ color: "var(--ink-muted)", textDecoration: "none" }}>Documents</Link>
          <span style={{ color: "var(--ink-faint)" }}> / </span>
          <span style={{ color: "var(--ink)" }}>{doc?.filename ?? "…"}</span>
        </span>
        <Link to={`/scrying?document=${id}`} style={{ color: "var(--gilt)", textDecoration: "none" }}>↳ Open in Scrying</Link>
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {doc === null && !error && <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {doc && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
            <Heading level={1} style={{ margin: 0 }}>{doc.filename}</Heading>
            <div style={{ display: "flex", gap: 10, flexShrink: 0 }}>
              <Button variant="ghost" onClick={() => setConfirmDelete(true)}
                disabled={!canWrite}>Delete</Button>
              <Button onClick={() => setFormOpen((v) => !v)}>+ New pipeline</Button>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 9,
            fontFamily: "var(--font-mono)", fontSize: 12.5, color: "var(--ink-muted)" }}>
            <StatusDot status={doc.status} />
            <span>{doc.progress?.page_count != null ? `${doc.progress.page_count} pages` : DASH}</span>
            <span>{list.length} pipeline{list.length === 1 ? "" : "s"}</span>
          </div>

          {/* "In corpora" row — extension point for Task 5 membership controls */}
          <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
              textTransform: "uppercase", color: "var(--ink-faint)" }}>In corpora</span>
            {(doc.corpora ?? []).length === 0 ? DASH : (doc.corpora ?? []).map((cc) => (
              <span key={cc.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12,
                background: "rgba(156,121,32,0.16)", borderRadius: 16, padding: "4px 6px 4px 11px",
                color: "var(--ink-muted)" }}>
                <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%",
                  background: "var(--gilt)" }} />
                {cc.name}
                <button aria-label={`Remove from ${cc.name}`} onClick={() => removeMember(cc.id)}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--ink-faint)",
                    fontSize: 12, lineHeight: 1, padding: "0 2px" }}>✕</button>
              </span>
            ))}
            {addable.length > 0 && (
              <select aria-label="Add to corpus" value=""
                onChange={(e) => { if (e.target.value) addMember(Number(e.target.value)); }}
                style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--ink-muted)",
                  background: "transparent", border: "1px dashed rgba(120,95,40,0.4)", borderRadius: 16,
                  padding: "4px 10px", cursor: "pointer" }}>
                <option value="">+ Add to corpus</option>
                {addable.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
          </div>

          {recommended && (
            <div style={{ marginTop: 22, border: "1px solid var(--frame-rule)", borderRadius: 10,
              padding: "12px 16px", background: "rgba(156,121,32,0.10)", fontSize: 12.5,
              color: "var(--ink-muted)" }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
                textTransform: "uppercase", color: "var(--gilt)", marginRight: 10 }}>Recommended</span>
              extract <b>{recommended.slots.extract}</b> · chunk <b>{recommended.slots.chunk}</b> ·
              index <b>{recommended.slots.index}</b>
              <span style={{ fontFamily: "var(--font-mono)", marginLeft: 10 }}>
                {fmtRating(recommended.projected_rating)}/15</span>
              {recommended.already_built && recommended.matches &&
                <span style={{ marginLeft: 10, color: "var(--ink-faint)" }}>
                  — already built as {recommended.matches}</span>}
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
            margin: "26px 0 6px" }}>
            <Heading level={2} style={{ margin: 0 }}>Pipelines</Heading>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--gilt)" }}>
              {list.length} built · {effCount} effective</span>
          </div>
          <p style={{ fontSize: 12.5, color: "var(--ink-muted)", margin: "0 0 16px", maxWidth: 620,
            lineHeight: 1.55 }}>
            Each pipeline keeps its own stored index — all are queryable. The effective one answers by
            default; setting another effective is a default choice, nothing rebuilds.</p>

          {formOpen && (
            <div style={{ border: "1px dashed rgba(120,95,40,0.45)", borderRadius: 10, padding: "16px 18px",
              marginBottom: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
                  textTransform: "uppercase", color: "var(--ink-faint)" }}>Pipeline name</span>
                <input value={recipe.name} aria-label="Pipeline name"
                  onChange={(e) => setRecipe((r) => ({ ...r, name: e.target.value }))}
                  style={{ fontFamily: "var(--font-mono)", fontSize: 13, padding: "7px 10px",
                    border: "1px solid var(--frame-rule)", borderRadius: 7, background: "var(--card)" }} />
              </label>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
                {(["parser", "chunker", "embedder"] as const).map((kind) => {
                  const label = { parser: "Extract", chunker: "Chunk", embedder: "Index" }[kind];
                  const err = slotErrors[kind];
                  return (
                    <div key={kind}>
                      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
                          textTransform: "uppercase",
                          color: err ? "var(--oxblood)" : "var(--ink-faint)" }}>{label}</span>
                        <select aria-label={label} value={recipe[kind] ?? ""}
                          onChange={(e) => setRecipe((r) => ({ ...r, [kind]: e.target.value,
                            options: { ...r.options, [kind]: {} } }))}
                          style={err ? { border: "1px solid var(--oxblood)", borderRadius: 6 } : undefined}>
                          {(components?.[kind] ?? []).map((o) => <option key={o.name} value={o.name}>{componentLabel(o.name)}</option>)}
                        </select>
                      </label>
                      {err && <div role="alert" style={{ fontSize: 11, color: "var(--oxblood)",
                        marginTop: 4 }}>{label} {err}</div>}
                      {kind === "chunker" && recipe.chunker === "contextual" && (
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6,
                          paddingLeft: 14 }}>
                          <span aria-hidden style={{ color: "var(--ink-faint)" }}>↳</span>
                          <ContextualLlmSelect endpoints={endpoints}
                            value={(recipe.options.chunker?.llm_endpoint as string) ?? null}
                            onChange={(name) => setRecipe((r) => ({ ...r,
                              options: { ...r.options, chunker: { ...r.options.chunker, llm_endpoint: name } } }))} />
                        </div>
                      )}
                      {kind === "parser" && recipe.parser === "vision" && (
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6,
                          paddingLeft: 14 }}>
                          <span aria-hidden style={{ color: "var(--ink-faint)" }}>↳</span>
                          <VisionLlmSelect endpoints={endpoints}
                            value={(recipe.options.parser?.vision_endpoint as string) ?? null}
                            onChange={(name) => setRecipe((r) => ({ ...r,
                              options: { ...r.options, parser: { ...r.options.parser, vision_endpoint: name } } }))} />
                        </div>
                      )}
                      {optionFields(
                        (components?.[kind] ?? []).find((c) => c.name === recipe[kind])?.options_schema
                      ).filter((f) => f.name !== "llm_endpoint" && f.name !== "vision_endpoint").map((f) => {
                        const val = recipe.options[kind]?.[f.name] ?? f.default;
                        const setVal = (v: unknown) => setRecipe((r) => ({
                          ...r, options: { ...r.options, [kind]: { ...(r.options[kind] ?? {}), [f.name]: v } } }));
                        return (
                          <label key={f.name} style={{ display: "flex", alignItems: "center", gap: 6,
                            marginTop: 5, fontSize: 11, color: "var(--ink-muted)" }}>
                            <span style={{ fontFamily: "var(--font-mono)", minWidth: 120 }}>{f.label}</span>
                            {f.type === "boolean" ? (
                              <input aria-label={f.name} type="checkbox" checked={Boolean(val)}
                                onChange={(e) => setVal(e.target.checked)} />
                            ) : f.type === "enum" ? (
                              <select aria-label={f.name} value={String(val ?? "")}
                                onChange={(e) => setVal(e.target.value)}
                                style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                                {(f.values ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
                              </select>
                            ) : f.type === "integer" || f.type === "number" ? (
                              <input aria-label={f.name} type="number" value={String(val ?? "")}
                                min={f.min} max={f.max}
                                onChange={(e) => {
                                  const n = f.type === "integer"
                                    ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
                                  setVal(Number.isNaN(n) ? f.default : n);
                                }}
                                style={{ width: 90, fontFamily: "var(--font-mono)", fontSize: 11 }} />
                            ) : f.longString ? (
                              <textarea aria-label={f.name} value={String(val ?? "")}
                                onChange={(e) => setVal(e.target.value)}
                                style={{ width: 240, fontFamily: "var(--font-mono)", fontSize: 11 }} />
                            ) : (
                              <input aria-label={f.name} type="text" value={String(val ?? "")}
                                onChange={(e) => setVal(e.target.value)}
                                style={{ width: 160, fontFamily: "var(--font-mono)", fontSize: 11 }} />
                            )}
                          </label>
                        );
                      })}
                    </div>
                  );
                })}
                <div style={{ marginLeft: "auto" }}>
                  <Button onClick={createPipeline} disabled={!canWrite || busy || !recipe.name || !recipeOk}>
                    {busy ? "Building…" : "Build"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {list.map((p) => <PipelineCard key={p.id} pipe={p} docId={id}
            onSetEffective={setEffective} onChanged={load} canWrite={canWrite} />)}
        </>
      )}

      <ConfirmDialog open={confirmDelete} title="Delete this document?" confirmLabel="Delete"
        danger busy={deleting} onConfirm={deleteDocument} onClose={() => setConfirmDelete(false)}>
        <strong>{doc?.filename}</strong> and all {list.length} pipeline{list.length === 1 ? "" : "s"}{" "}
        built on it will be removed, along with their indexes. Corpora that reference this document
        will lose it. This can't be undone.
      </ConfirmDialog>
    </Panel>
  );
}

function PipelineCard({ pipe, docId, onSetEffective, onChanged, canWrite }:
  { pipe: DocPipeline; docId: number; onSetEffective: (pipelineId: number) => void;
    onChanged: () => void; canWrite: boolean }) {
  const building = pipe.status === "building";
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const remove = async () => {
    setDeleting(true);
    try { await api.deletePipeline(docId, pipe.id); onChanged(); }
    finally { setDeleting(false); setConfirm(false); }
  };
  return (
    <div style={{ border: "1px solid var(--frame-rule)", borderRadius: 12, padding: "18px 20px",
      marginBottom: 14, background: "var(--card)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 600 }}>{pipe.name}</span>
          {pipe.effective && <span style={{ fontFamily: "var(--font-mono)", fontSize: 10,
            letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink)",
            background: "var(--gilt)", borderRadius: 5, padding: "2px 8px" }}>Effective</span>}
          <StatusDot status={pipe.status} />
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-faint)" }}>Total</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600,
            color: building ? "var(--ink-faint)" : "var(--ink)" }}>
            {building ? "—" : `${fmtRating(pipe.rating)}/15`}</div>
        </div>
      </div>

      {pipe.created_at && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)",
          marginTop: 4 }}>Created {fmtCreated(pipe.created_at)}</div>
      )}

      {building ? <BuildConsole progress={pipe.progress} /> : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginTop: 16 }}>
          {SLOT_ORDER.map((slot) => (
            <div key={slot}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
                textTransform: "uppercase", color: "var(--ink-faint)" }}>{SLOT_LABEL[slot]}</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 12.5, color: "var(--ink-muted)",
                margin: "3px 0 6px" }}>{pipe.slots[slot] ?? "—"}</div>
              <SegmentScore value={pipe.steps[slot] ?? 0} />
            </div>
          ))}
        </div>
      )}

      {!building && (
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 16, paddingTop: 14,
          borderTop: "1px solid rgba(120,95,40,0.18)" }}>
          <Link to={`/compare?document=${docId}`} style={{ fontSize: 12.5, color: "var(--gilt)",
            textDecoration: "none" }}>Compare steps</Link>
          {!pipe.effective && pipe.status === "indexed" && (
            <button onClick={() => onSetEffective(pipe.id)} style={{ fontSize: 12.5,
              background: "none", border: "none", color: "var(--ink-muted)", cursor: "pointer",
              padding: 0 }}>Set effective</button>
          )}
          {pipe.effective && <span style={{ fontFamily: "var(--font-mono)",
            fontSize: 11, color: "#4a7a3c" }}>✓ answering queries</span>}
          <button onClick={() => setConfirm(true)} disabled={!canWrite} style={{ marginLeft: "auto",
            fontSize: 12.5, background: "none", border: "none", padding: 0,
            color: canWrite ? "var(--oxblood)" : "var(--ink-faint)",
            cursor: canWrite ? "pointer" : "default" }}>Delete</button>
        </div>
      )}

      <ConfirmDialog open={confirm} title="Delete this pipeline?" confirmLabel="Delete"
        danger busy={deleting} onConfirm={remove} onClose={() => setConfirm(false)}>
        Pipeline <strong>{pipe.name}</strong> and its index will be removed. The document and its
        other pipelines are untouched. This can't be undone.
      </ConfirmDialog>
    </div>
  );
}

export default Workbench;
