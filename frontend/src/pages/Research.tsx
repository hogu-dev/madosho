import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Corpus, Document, LlmEndpoint, ResearchLaunch, ResearchRun } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { useEndpointModels } from "../hooks/useEndpointModels";
import { Panel, Heading, Button, SegmentedToggle, StatusDot, EmptyState } from "../design/primitives";
import { ConfirmDialog } from "../design/ConfirmDialog";

const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

const ACTIVE = (s: string) => s === "pending" || s === "running";

const selectStyle = {
  fontSize: 13, fontFamily: "var(--font-ui)", padding: "6px 10px",
  border: "1px solid var(--frame-rule)", borderRadius: 7, background: "var(--parchment-panel)",
} as const;

// A research run names its model explicitly in the launch payload, but the worker
// talks to whatever endpoint MADOSHO_LLM_API_BASE points at. So the picker only
// needs to carry the provider/model NAME of the endpoint the user means to use.
export function Research() {
  const nav = useNavigate();
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpus, setCorpus] = useState("");
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const { ep, endpointName, setEndpointName, models, modelId, setModelId,
    ladder, effort, setEffort } = useEndpointModels(endpoints);
  const [prompt, setPrompt] = useState("");
  const [source, setSource] = useState<"rag" | "whole-text">("rag");
  const [docs, setDocs] = useState<Document[]>([]);
  const [docIds, setDocIds] = useState<number[]>([]);
  const [budget, setBudget] = useState(100000);
  const [rounds, setRounds] = useState(8);
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<ResearchRun | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    api.listCorpora().then((cs) => { setCorpora(cs); setCorpus((c) => c || cs[0]?.name || ""); })
      .catch(() => setCorpora([]));
    api.listLlmEndpoints().then(setEndpoints).catch(() => setEndpoints([]));
  }, []);

  const cid = corpora.find((c) => c.name === corpus)?.id ?? null;

  // Runs are corpus-scoped; reload them whenever the chosen corpus changes.
  const loadRuns = () => {
    if (cid == null) { setRuns([]); return; }
    api.listResearch(cid).then(setRuns).catch(() => setRuns([]));
  };
  useEffect(loadRuns, [cid]);
  usePolling(loadRuns, 2500, runs.some((r) => ACTIVE(r.status)));

  // Whole-text targets a chosen subset of the corpus's documents (empty = all).
  useEffect(() => {
    if (cid == null) { setDocs([]); return; }
    api.listDocuments(cid).then(setDocs).catch(() => setDocs([]));
    setDocIds([]);
  }, [cid]);

  const canLaunch = prompt.trim().length > 0 && cid != null && ep != null && !busy;

  const launch = async () => {
    if (cid == null || ep == null) return;
    setBusy(true); setError(null);
    try {
      const body: ResearchLaunch = {
        prompt: prompt.trim(), source, document_ids: source === "whole-text" ? docIds : [],
        budget_chars: budget, max_rounds: rounds,
        llm: { provider: ep.provider, model: modelId || ep.model },
      };
      if (effort) body.reasoning_effort = effort;
      const run = await api.launchResearch(cid, body);
      setPrompt("");
      nav(`/research/${run.id}?corpus=${cid}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Launch failed");
    } finally { setBusy(false); }
  };

  const handleCancel = async () => {
    if (cancelTarget == null) return;
    setCancelling(true);
    try {
      await api.cancelResearch(cancelTarget.id);
      loadRuns();
      setCancelTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
      setCancelTarget(null);  // close the dialog so the error banner isn't hidden behind its backdrop
    } finally {
      setCancelling(false);
    }
  };

  const activeRuns = runs.filter((r) => ACTIVE(r.status));

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 1360 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Heading level={1} style={{ margin: 0 }}>Research</Heading>
        <span style={{ ...mono(11, "var(--gilt)"), letterSpacing: "0.08em", textTransform: "uppercase",
          border: "1px solid var(--frame-rule)", borderRadius: 20, padding: "3px 10px" }}>agentic</span>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 22px", maxWidth: 620,
        lineHeight: 1.55 }}>
        Pose a question and let an agent work it over a corpus across several rounds — searching,
        reading, and citing as it goes — then read back a sourced report.</p>

      {/* LAUNCH FORM */}
      <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
        padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 14 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
              textTransform: "uppercase" }}>Corpus</span>
            <select aria-label="Corpus" value={corpus} onChange={(e) => setCorpus(e.target.value)}
              style={selectStyle}>
              {corpora.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
            </select>
          </label>

          <SegmentedToggle value={source} onChange={(v) => setSource(v as "rag" | "whole-text")}
            options={[{ value: "rag", label: "RAG retrieval" },
              { value: "whole-text", label: "Whole extracted text" }]} />

          {endpoints.length === 0 ? (
            <span style={{ fontSize: 12.5, color: "var(--oxblood)" }}>
              needs an LLM endpoint — add one in Settings</span>
          ) : (
            <>
              <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                  textTransform: "uppercase" }}>Endpoint</span>
                <select aria-label="Endpoint" value={endpointName}
                  onChange={(e) => setEndpointName(e.target.value)} style={selectStyle}>
                  {endpoints.map((e) => <option key={e.id} value={e.name}>{e.name}</option>)}
                </select>
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                  textTransform: "uppercase" }}>Model</span>
                <select aria-label="Model" value={modelId}
                  onChange={(e) => setModelId(e.target.value)} style={selectStyle}>
                  {models.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
                </select>
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                  textTransform: "uppercase" }}>Reasoning</span>
                <select aria-label="Reasoning effort" value={effort}
                  onChange={(e) => setEffort(e.target.value)} style={selectStyle}
                  disabled={ladder.length === 0}>
                  <option value="">Endpoint default</option>
                  {ladder.map((lvl) => <option key={lvl} value={lvl}>{lvl}</option>)}
                </select>
              </label>
            </>
          )}
        </div>

        {source === "whole-text" && (
          <label style={{ display: "block", marginBottom: 14 }}>
            <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
              textTransform: "uppercase", display: "block", marginBottom: 5 }}>
              Documents <span style={{ textTransform: "none", letterSpacing: 0 }}>(leave empty for the whole corpus)</span></span>
            <select aria-label="Documents" multiple value={docIds.map(String)}
              onChange={(e) => setDocIds(Array.from(e.target.selectedOptions, (o) => Number(o.value)))}
              style={{ ...selectStyle, width: "100%", minHeight: 92 }}>
              {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
          </label>
        )}

        <textarea aria-label="Research question" placeholder="What should the agent investigate?"
          value={prompt} onChange={(e) => setPrompt(e.target.value)}
          style={{ width: "100%", minHeight: 84, resize: "vertical", background: "var(--parchment-panel)",
            border: "1px solid var(--frame-rule)", borderRadius: 9, padding: "13px 14px",
            fontFamily: "var(--font-ui)", fontSize: 14, color: "var(--ink)", lineHeight: 1.5,
            boxSizing: "border-box" }} />

        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", marginTop: 13 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={mono(11, "var(--ink-muted)")}>Context budget</span>
            <input aria-label="Context budget" type="number" min={1000} step={1000} value={budget}
              onChange={(e) => setBudget(Number.parseInt(e.target.value, 10) || 100000)}
              style={{ ...selectStyle, width: 110 }} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={mono(11, "var(--ink-muted)")}>Max rounds</span>
            <input aria-label="Max rounds" type="number" min={1} max={20} value={rounds}
              onChange={(e) => setRounds(Number.parseInt(e.target.value, 10) || 8)}
              style={{ ...selectStyle, width: 70 }} />
          </label>
          <span style={{ marginLeft: "auto" }}>
            <Button onClick={launch} disabled={!canLaunch}>
              {busy ? "Launching…" : "Launch ✦"}</Button>
          </span>
        </div>
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13, marginTop: 16 }}>{error}</p>}

      {/* ACTIVE RUNS */}
      {activeRuns.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 10 }}>Active runs</div>
          {activeRuns.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 14,
              background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 10,
              padding: "13px 16px", marginBottom: 9 }}>
              <StatusDot status={r.status} />
              <span style={{ flex: 1, fontSize: 13.5, color: "var(--ink)", overflow: "hidden",
                textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.prompt}</span>
              <span style={mono(11, "var(--ink-faint)")}>#{r.id}</span>
              <button type="button" onClick={() => setCancelTarget(r)}
                style={{ background: "transparent", border: "1px solid var(--oxblood)",
                  color: "var(--oxblood)", fontSize: 12, padding: "4px 10px",
                  borderRadius: 6, cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                Cancel
              </button>
            </div>
          ))}
        </div>
      )}

      {/* RUN HISTORY */}
      <div style={{ marginTop: 28 }}>
        <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase",
          marginBottom: 10 }}>Runs</div>
        {runs.length === 0 ? (
          <EmptyState title="No research runs yet" hint="Launch one above to get started." />
        ) : runs.map((r) => (
          <Link key={r.id} to={`/research/${r.id}${cid != null ? `?corpus=${cid}` : ""}`}
            style={{ display: "flex", alignItems: "center", gap: 14, textDecoration: "none",
              background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 10,
              padding: "13px 16px", marginBottom: 9 }}>
            <StatusDot status={r.status} />
            <span style={{ flex: 1, fontSize: 13.5, color: "var(--ink)", overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.prompt}</span>
            <span style={mono(11, "var(--ink-faint)")}>#{r.id}</span>
          </Link>
        ))}
      </div>

      <ConfirmDialog open={cancelTarget != null} title="Cancel this run?" confirmLabel="Cancel run"
        danger busy={cancelling} onConfirm={handleCancel} onClose={() => setCancelTarget(null)}>
        The agent stops at the end of its current round.
      </ConfirmDialog>
    </Panel>
  );
}

export default Research;
