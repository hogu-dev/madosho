// frontend/src/pages/Quality.tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { Corpus, Cube, CubeCell, DocGroup, PipelineRow, Document, EvalRun, Proposal, VirtualModel } from "../api/types";
import { Panel, Heading, EmptyState, SegmentScore, Button, StatusDot } from "../design/primitives";
import { Modal } from "../design/Modal";
import { ConfirmDialog } from "../design/ConfirmDialog";
import { usePolling } from "../hooks/usePolling";
import { dismissProposalAction } from "./proposalActions";

const SOURCE_LABEL: Record<string, string> = {
  human: "Human verdict", measured: "Measured eval", "f-empirical": "Measured (whole-pipeline)",
  static: "Static estimate", rollup: "Corpus rollup",
};

const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

// Build dims ride each pipeline row; retrieval dims sit on the per-document strip
// (they are not rated per pipeline today). ALL_DIMS is only for the evidence modal title.
const BUILD_DIMS: { key: string; label: string }[] = [
  { key: "extraction", label: "Extract" }, { key: "chunk", label: "Chunk" }, { key: "embed", label: "Embed" },
];
const RETR_DIMS: { key: string; label: string; abbr: string }[] = [
  { key: "keyword", label: "Keyword", abbr: "key" },
  { key: "semantic", label: "Semantic", abbr: "sem" },
  { key: "rerank", label: "Rerank", abbr: "rer" },
];
const ALL_DIMS = [...BUILD_DIMS, ...RETR_DIMS];
const PGRID = "1.7fr 1fr 1fr 1fr 0.8fr";

function Scoreboard(
  { cube, docName, onCellClick }:
  { cube: Cube; docName: (id: number | null) => string;
    onCellClick: (documentId: number | null, dim: string, cell: CubeCell) => void },
) {
  const head = { ...mono(9.5, "var(--ink-faint)"), letterSpacing: "0.06em", textTransform: "uppercase" as const };
  const buildCell = (row: PipelineRow, docId: number, dim: string) => {
    const c = row.cells[dim];
    if (!c) return <div key={dim} data-testid="cell-empty" style={{ textAlign: "center", color: "var(--ink-faint)" }}>-</div>;
    return (
      <div key={dim} style={{ textAlign: "center", cursor: "pointer" }} role="button"
        onClick={() => onCellClick(docId, dim, c)}>
        <SegmentScore value={c.score} />
      </div>
    );
  };
  const group = (g: DocGroup) => (
    <div key={g.document_id} data-testid="doc-group"
      style={{ marginTop: 22, border: "1px solid var(--frame-rule)", borderRadius: 10, overflow: "hidden" }}>
      {/* Document header band + per-document retrieval strip */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "13px 16px",
        background: "rgba(156,121,32,0.10)", borderBottom: "1px solid var(--frame-rule)" }}>
        <span style={{ fontFamily: "var(--font-serif)", fontWeight: 600, fontSize: 15, color: "var(--ink)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{docName(g.document_id)}</span>
        <span style={{ flex: 1 }} />
        <span style={{ ...mono(9, "var(--ink-faint)"), letterSpacing: "0.07em", textTransform: "uppercase" }}>
          Retrieval (whole document)</span>
        {RETR_DIMS.map((d) => {
          const c = g.retrieval[d.key];
          return (
            <span key={d.key} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
              <span style={{ ...mono(8.5, "var(--ink-faint)"), textTransform: "uppercase", letterSpacing: "0.05em" }}>{d.abbr}</span>
              {c ? (
                <span role="button" style={{ cursor: "pointer" }} onClick={() => onCellClick(g.document_id, d.key, c)}>
                  <SegmentScore value={c.score} /></span>
              ) : <span style={mono(13, "var(--ink-faint)")}>-</span>}
            </span>
          );
        })}
      </div>
      {/* Column header for the pipeline rows */}
      <div style={{ display: "grid", gridTemplateColumns: PGRID, gap: 8, alignItems: "end",
        padding: "9px 16px 8px", borderBottom: "1px solid rgba(120,95,40,0.18)", ...head }}>
        <div>Pipeline</div>
        {BUILD_DIMS.map((d) => <div key={d.key} style={{ textAlign: "center" }}>{d.label}</div>)}
        <div style={{ textAlign: "center" }}>Build</div>
      </div>
      {/* One row per pipeline */}
      {g.pipelines.length === 0 ? (
        <div style={{ padding: "14px 16px", ...mono(11.5, "var(--ink-muted)") }}>No pipelines built yet.</div>
      ) : g.pipelines.map((p, i) => (
        <div key={p.pipeline_id} style={{ display: "grid", gridTemplateColumns: PGRID, gap: 8, alignItems: "center",
          padding: "13px 16px",
          ...(i < g.pipelines.length - 1 ? { borderBottom: "1px solid rgba(120,95,40,0.12)" } : {}),
          ...(p.effective ? { background: "rgba(156,121,32,0.05)" } : {}) }}>
          <span style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
            <span style={{ ...mono(12.5, "var(--ink)"), fontWeight: 500, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
            {p.effective && (
              <span style={{ ...mono(8.5, "var(--amber-text)"), background: "var(--amber-grad)",
                padding: "1.5px 6px", borderRadius: 5, letterSpacing: "0.04em", whiteSpace: "nowrap" }}>EFFECTIVE</span>
            )}
          </span>
          {BUILD_DIMS.map((d) => buildCell(p, g.document_id, d.key))}
          <div style={{ textAlign: "center" }}>
            <span style={{ ...mono(14, "var(--ink)"), fontWeight: 600 }}>{p.build_total}</span>
            <span style={mono(9.5, "var(--ink-faint)")}>/5</span></div>
        </div>
      ))}
    </div>
  );
  return (
    <div data-testid="scoreboard">
      {cube.documents.map(group)}
      <div style={{ display: "flex", gap: 16, marginTop: 16, paddingLeft: 4, flexWrap: "wrap",
        ...mono(10.5, "var(--ink-muted)") }}>
        <span>Filled dots = score (0-5).</span>
        <span>EFFECTIVE = the pipeline this document answers through by default.</span>
      </div>
    </div>
  );
}

const field = (label: string, control: React.ReactNode) => (
  <label style={{ display: "flex", alignItems: "center", gap: 10,
    fontSize: 13, color: "var(--ink)", fontFamily: "var(--font-ui)" }}>
    <span style={{ minWidth: 130, color: "var(--ink-muted)" }}>{label}</span>
    {control}
  </label>
);

const inputStyle: React.CSSProperties = {
  fontSize: 13, fontFamily: "var(--font-ui)", padding: "5px 9px",
  border: "1px solid var(--frame-rule)", borderRadius: 6,
  background: "var(--parchment-panel)", color: "var(--ink)", width: 130,
};

export function Quality() {
  const navigate = useNavigate();
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [params, setParams] = useSearchParams();
  const corpusId = Number(params.get("corpus")) || null;
  const [cube, setCube] = useState<Cube | null>(null);
  const [docs, setDocs] = useState<Document[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ documentId: number | null; dim: string; cell: CubeCell } | null>(null);
  const openCell = (documentId: number | null, dim: string, cell: CubeCell) => setSelected({ documentId, dim, cell });
  const dimLabel = (k: string) => ALL_DIMS.find((d) => d.key === k)?.label ?? k;

  // Measure section state
  const [models, setModels] = useState<VirtualModel[]>([]);
  const [model, setModel] = useState("");
  const [nDocs, setNDocs] = useState(8);
  const [qPerDoc, setQPerDoc] = useState(3);
  const [budget, setBudget] = useState("");
  const [launching, setLaunching] = useState(false);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const loadRuns = () => { if (corpusId != null) api.listEvals(corpusId).then(setRuns).catch(() => setRuns([])); };
  useEffect(loadRuns, [corpusId]); // eslint-disable-line react-hooks/exhaustive-deps
  const anyActive = runs.some((r) => r.status === "pending" || r.status === "running");
  usePolling(loadRuns, 2500, anyActive);
  const [evalCancelTarget, setEvalCancelTarget] = useState<EvalRun | null>(null);
  const [evalCancelling, setEvalCancelling] = useState(false);
  const handleEvalCancel = async () => {
    if (evalCancelTarget == null) return;
    setEvalCancelling(true);
    try {
      await api.cancelEval(evalCancelTarget.id);
      loadRuns();
      setEvalCancelTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
      setEvalCancelTarget(null);  // close the dialog so the error banner isn't hidden behind its backdrop
    } finally {
      setEvalCancelling(false);
    }
  };

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const loadProposal = () => { if (corpusId != null) api.getProposal(corpusId).then(setProposal).catch(() => setProposal(null)); };
  useEffect(loadProposal, [corpusId]); // eslint-disable-line react-hooks/exhaustive-deps
  const onDismiss = async () => { if (proposal) { await dismissProposalAction(proposal); setProposal(null); } };
  const lift = proposal?.evidence.lifts?.[0];

  const delta = (r: EvalRun) => {
    const g = r.results?.greedy;
    if (!g) return null;
    const d = g.final_score - g.baseline_score;
    return `${d >= 0 ? "+" : ""}${d.toFixed(2)}`;
  };

  useEffect(() => {
    api.listVirtualModels().then((vms) => {
      setModels(vms);
      setModel((m) => m || (vms[0] ? `${vms[0].provider}:${vms[0].model}` : ""));
    }).catch(() => setModels([]));
  }, []);

  const launch = async () => {
    if (corpusId == null) return;
    setLaunching(true);
    try {
      const [provider, ...rest] = model.split(":");
      const llm = model ? { provider, model: rest.join(":") } : undefined;
      const run = await api.launchEval(corpusId, {
        sampling: { n_docs: nDocs, questions_per_doc: qPerDoc, ...(llm ? { llm } : {}) },
        token_budget: budget ? Number(budget) : null,
      });
      navigate(`/quality/eval/${run.id}`);
    } finally { setLaunching(false); }
  };

  // Pick the corpus list once; if ?corpus is missing/invalid, default to the first.
  useEffect(() => {
    api.listCorpora().then((cs) => {
      setCorpora(cs);
      if (corpusId == null && cs[0]) setParams({ corpus: String(cs[0].id) }, { replace: true });
    }).catch(() => setCorpora([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // (Re)load ratings + document names whenever the scoped corpus changes.
  useEffect(() => {
    if (corpusId == null) return;
    setError(null); setCube(null);
    api.getRatings(corpusId).then(setCube).catch((e) => setError(e instanceof Error ? e.message : "Load failed"));
    api.listDocuments(corpusId).then(setDocs).catch(() => setDocs([]));
  }, [corpusId]);

  // docName is forwarded to the scoreboard in Task 2; computed here so the
  // effect/memo topology is stable before the slot is filled.
  const docName = useMemo(() => {
    const m = new Map(docs.map((d) => [d.id, d.filename]));
    return (id: number | null) => (id != null ? m.get(id) ?? `#${id}` : "");
  }, [docs]);

  const empty = cube != null && cube.documents.length === 0;

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 1080 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Heading level={1} style={{ margin: 0 }}>Quality</Heading>
        <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em", textTransform: "uppercase" }}>Corpus</span>
          <select aria-label="Corpus" value={corpusId ?? ""} onChange={(e) => setParams({ corpus: e.target.value })}
            style={{ fontSize: 13, fontFamily: "var(--font-ui)", padding: "6px 10px",
              border: "1px solid var(--frame-rule)", borderRadius: 7, background: "var(--parchment-panel)" }}>
            {corpora.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 22px", maxWidth: 640, lineHeight: 1.55 }}>
        How each pipeline on a document is rated, 0-5. Build steps (Extract / Chunk / Embed) vary per
        pipeline; retrieval (Keyword / Semantic / Rerank) is rated per document. Click a cell to see the
        evidence.</p>

      {proposal && proposal.status === "proposed" && (
        <div style={{ marginTop: 4, marginBottom: 22, background: "var(--amber-grad)",
          border: "1px solid rgba(138,109,42,0.45)", borderRadius: 11, padding: "15px 18px",
          display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontSize: 22 }}>{"✦"}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink)" }}>An eval run found a stronger recipe.</div>
            <div style={{ fontSize: 12.5, color: "var(--ink-muted)", marginTop: 3, lineHeight: 1.5 }}>
              {lift ? `${lift.stage} -> ${lift.label} lifted retrieval by +${lift.lift.toFixed(2)}. ` : ""}
              To use it, build this recipe as a pipeline on the document and set it effective.</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onDismiss} style={{ background: "transparent", border: "1px solid var(--frame-rule)",
              color: "var(--ink-muted)", borderRadius: 7, padding: "9px 14px", fontSize: 12.5, cursor: "pointer" }}>Dismiss</button>
          </div>
        </div>
      )}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {empty && <EmptyState title="No rated documents" hint="Add indexed documents to this corpus, then run an eval." />}
      {cube && !empty && <Scoreboard cube={cube} docName={docName} onCellClick={openCell} />}

      <div style={{ marginTop: 36, borderTop: "1px solid var(--frame-rule)", paddingTop: 24 }}>
        <Heading level={2} style={{ margin: "0 0 6px" }}>Measure</Heading>
        <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "0 0 18px", maxWidth: 600, lineHeight: 1.55 }}>
          Samples documents, has a model write grounded questions, then scores retrieval mechanically
          (hit@k / MRR / nDCG). No LLM judges the answers.</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 500 }}>
          {field("Question model",
            <select aria-label="Question model" value={model} onChange={(e) => setModel(e.target.value)}
              style={inputStyle}>
              {models.map((vm) => (
                <option key={vm.id} value={`${vm.provider}:${vm.model}`}>{vm.name}</option>
              ))}
            </select>
          )}
          {field("Sample size",
            <input aria-label="Sample size" type="number" min={1} value={nDocs}
              onChange={(e) => setNDocs(Number(e.target.value))} style={inputStyle} />
          )}
          {field("Questions per doc",
            <input aria-label="Questions per doc" type="number" min={1} value={qPerDoc}
              onChange={(e) => setQPerDoc(Number(e.target.value))} style={inputStyle} />
          )}
          {field("Token budget",
            <input aria-label="Token budget" type="number" min={1} value={budget}
              onChange={(e) => setBudget(e.target.value)} placeholder="unlimited"
              style={inputStyle} />
          )}
          <div style={{ marginTop: 6 }}>
            <Button onClick={launch} disabled={launching || corpusId == null}>
              {launching ? "Launching..." : "Launch run"}
            </Button>
          </div>
        </div>
      </div>

      {anyActive && (
        <div style={{ marginTop: 32, borderTop: "1px solid var(--frame-rule)", paddingTop: 22 }}>
          <Heading level={2} style={{ margin: "0 0 14px" }}>Active runs</Heading>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {runs.filter((r) => r.status === "pending" || r.status === "running").map((r) => (
              <div key={r.id}
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                  borderRadius: 7, border: "1px solid var(--frame-rule)",
                  background: "var(--parchment-panel)" }}>
                <StatusDot status={r.status} />
                <span style={{ ...mono(13, "var(--ink)"), fontWeight: 500 }}>run #{r.id}</span>
                <span style={{ flex: 1 }} />
                <button type="button" onClick={() => setEvalCancelTarget(r)}
                  style={{ background: "transparent", border: "1px solid var(--oxblood)",
                    color: "var(--oxblood)", fontSize: 12, padding: "4px 10px",
                    borderRadius: 6, cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                  Cancel
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {runs.length > 0 && (
        <div style={{ marginTop: 32, borderTop: "1px solid var(--frame-rule)", paddingTop: 22 }}>
          <Heading level={2} style={{ margin: "0 0 14px" }}>Run history</Heading>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {runs.map((r) => {
              const sampling = r.sampling;
              const summaryParts: string[] = [];
              if (sampling?.n_docs != null) summaryParts.push(`${sampling.n_docs} docs`);
              if (sampling?.llm) summaryParts.push(`${sampling.llm.provider}:${sampling.llm.model}`);
              const summary = summaryParts.join(" - ");
              const d = delta(r);
              return (
                <Link
                  key={r.id}
                  to={`/quality/eval/${r.id}`}
                  style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                    borderRadius: 7, border: "1px solid var(--frame-rule)",
                    background: "var(--parchment-panel)", textDecoration: "none",
                    color: "var(--ink)" }}
                >
                  <StatusDot status={r.status} />
                  <span style={{ ...mono(13, "var(--ink)"), fontWeight: 500 }}>run #{r.id}</span>
                  {summary && (
                    <span style={mono(11.5, "var(--ink-muted)")}>{summary}</span>
                  )}
                  {d != null && (
                    <span style={{ ...mono(11.5, "var(--ink-muted)"), marginLeft: "auto" }}>{d}</span>
                  )}
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <ConfirmDialog open={evalCancelTarget != null} title="Cancel this eval run?"
        confirmLabel="Cancel run" danger busy={evalCancelling}
        onConfirm={handleEvalCancel} onClose={() => setEvalCancelTarget(null)}>
        Cancel this eval run? Eval cancels cooperatively at its next checkpoint.
      </ConfirmDialog>

      <Modal open={selected != null} onClose={() => setSelected(null)} labelledBy="cell-title">
        {selected && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Heading level={2} style={{ margin: 0 }}><span id="cell-title">{dimLabel(selected.dim)}</span></Heading>
              <SegmentScore value={selected.cell.score} />
            </div>
            <p style={{ ...mono(11, "var(--gilt)"), marginTop: 10 }}>
              {SOURCE_LABEL[selected.cell.source] ?? selected.cell.source}</p>
            <p style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink)" }}>
              {selected.cell.rationale ?? "No rationale recorded."}</p>
            {selected.cell.suggestion && (
              <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-muted)",
                borderTop: "1px solid var(--frame-rule)", paddingTop: 12 }}>
                <strong>Suggestion: </strong>{selected.cell.suggestion}</p>
            )}
          </div>
        )}
      </Modal>
    </Panel>
  );
}

export default Quality;
