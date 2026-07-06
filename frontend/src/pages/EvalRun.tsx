// frontend/src/pages/EvalRun.tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EvalRun as Run, Proposal } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { Panel, Heading, StatusDot, Button } from "../design/primitives";
import { dismissProposalAction } from "./proposalActions";

const mono = (size = 12, color = "var(--ink-muted)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

function MetricCard({ label, value, before, delta }:
  { label: string; value: string; before?: string; delta?: string }) {
  return (
    <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 11, padding: 16 }}>
      <div style={{ ...mono(10, "var(--ink-faint)"), letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 6 }}>
        <span style={{ ...mono(24, "var(--ink)"), fontWeight: 600 }}>{value}</span>
        {before && <span style={mono(12, "var(--ink-muted)")}>{"←"} {before}</span>}
        {delta && <span style={mono(12, "var(--gilt)")}>{delta}</span>}
      </div>
    </div>
  );
}

export function EvalRun() {
  const { runId } = useParams<{ runId: string }>();
  const id = Number(runId);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const load = () => { if (Number.isFinite(id)) api.getEval(id).then(setRun).catch((e) => setError(String(e))); };
  useEffect(load, [id]);
  usePolling(load, 2500, run?.status === "pending" || run?.status === "running");
  useEffect(() => { if (run?.corpus_id != null) api.getProposal(run.corpus_id).then(setProposal).catch(() => setProposal(null)); }, [run?.corpus_id]);
  const showProposal = proposal && proposal.status === "proposed" && proposal.eval_run_id === run?.id;
  const onDismiss = async () => { if (proposal) { await dismissProposalAction(proposal); setProposal(null); } };

  if (error) return <Panel style={{ padding: 28 }}><p style={{ color: "var(--oxblood)" }}>{error}</p></Panel>;
  if (!run) return <Panel style={{ padding: 28 }}><p style={mono()}>Loading run…</p></Panel>;

  const s = run.sampling;
  const note = run.results && !("greedy" in run.results) && ("note" in (run.results as Record<string, unknown>))
    ? (run.results as { note: string }).note : null;

  const g = run.results?.greedy;
  const baseline = run.results?.baseline;
  const fmt = (n: number) => n.toFixed(2);

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 900 }}>
      <Link to="/quality" style={{ ...mono(11, "var(--gilt)"), textDecoration: "none" }}>{"←"} Back to Quality</Link>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
        <Heading level={1} style={{ margin: 0, fontFamily: "var(--font-mono)" }}>run #{run.id}</Heading>
        <StatusDot status={run.status} />
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap", ...mono(12, "var(--ink-muted)") }}>
        <span>corpus {run.corpus_id}</span>
        {s?.n_docs != null && <span>{s.n_docs} docs sampled</span>}
        {s?.llm && <span>{s.llm.provider}:{s.llm.model}</span>}
        {run.tokens_spent != null && <span>{run.tokens_spent.toLocaleString("en-US")} tokens</span>}
      </div>
      {note && <p style={{ marginTop: 20, fontSize: 14, color: "var(--ink-muted)" }}>{note}</p>}
      <div data-testid="results-slot" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginTop: 24 }}>
        {g && <MetricCard label="Retrieval score" value={fmt(g.final_score)} before={fmt(g.baseline_score)}
          delta={`${g.final_score - g.baseline_score >= 0 ? "+" : ""}${fmt(g.final_score - g.baseline_score)}`} />}
        {baseline && Object.entries(baseline).filter(([k]) => k !== "n").map(([k, v]) =>
          <MetricCard key={k} label={`${k} (baseline)`} value={fmt(v)} />)}
      </div>
      {g && g.path.length > 0 && (
        <div style={{ marginTop: 30 }}>
          <Heading level={2} style={{ margin: "0 0 4px" }}>Greedy search path</Heading>
          <p style={{ fontSize: 12.5, color: "var(--ink-muted)", margin: "0 0 18px", maxWidth: 560, lineHeight: 1.5 }}>
            Each step changed one knob and kept it only if retrieval improved.</p>
          {g.path.map((step, i) => {
            const kept = step.lift >= 0;
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0",
                borderBottom: "1px solid rgba(120,95,40,0.12)" }}>
                <span style={{ ...mono(13, "var(--ink)"), fontWeight: 600 }}>{step.stage} {"→"} {step.label}</span>
                <span style={{ ...mono(11.5, kept ? "#3f6b2f" : "#8a6a3a"),
                  background: kept ? "rgba(95,138,63,0.18)" : "rgba(120,95,40,0.14)", borderRadius: 5, padding: "2px 8px" }}>
                  {kept ? "kept" : "reverted"} - {step.lift >= 0 ? "+" : ""}{step.lift.toFixed(2)}</span>
                <span style={{ marginLeft: "auto", ...mono(12, "var(--ink-muted)") }}>score {step.score.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      )}
      {showProposal && (
        <div style={{ marginTop: 30, background: "var(--parchment, #fdf8ee)", border: "1px solid var(--frame-rule)", borderRadius: 11, padding: "20px 24px" }}>
          <Heading level={2} style={{ margin: "0 0 14px" }}>Proposed recipe</Heading>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
            {proposal.evidence.lifts.map((l) => (
              <span key={l.label} style={{ ...mono(12, "var(--ink)"), background: "rgba(120,95,40,0.12)", borderRadius: 5, padding: "3px 10px" }}>{l.label}</span>
            ))}
          </div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "0 0 18px", lineHeight: 1.55 }}>
            To use this recipe, build it as a pipeline on the document and set it effective; your existing pipelines stay live and untouched.
          </p>
          <div style={{ display: "flex", gap: 10 }}>
            <Button variant="ghost" onClick={onDismiss}>Dismiss</Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

export default EvalRun;
