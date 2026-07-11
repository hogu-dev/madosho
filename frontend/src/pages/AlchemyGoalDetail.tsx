import { useEffect, useState } from "react";
import type { MouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AlchemyGoal, AlchemyRunLaunch, AlchemyRunSummary, LlmEndpoint } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { Panel, Heading, Button, SegmentedToggle, StatusDot, EmptyState } from "../design/primitives";
import { ConfirmDialog } from "../design/ConfirmDialog";
import { BackLink } from "../design/Frame";
import { useAuth } from "../auth/AuthContext";

const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });
const ACTIVE = (s: string) => s === "pending" || s === "running";
const GRID = "0.55fr 0.95fr 0.75fr 1.7fr 0.55fr 0.55fr 0.85fr 0.9fr 1.05fr";
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{"\u2014"}</span>;

const selectStyle = {
  fontSize: 13, fontFamily: "var(--font-ui)", padding: "6px 10px",
  border: "1px solid var(--frame-rule)", borderRadius: 7, background: "var(--parchment-panel)",
} as const;

const finalPill = { fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: "0.08em",
  textTransform: "uppercase", background: "rgba(95,138,63,0.18)", color: "#4a7a3c",
  border: "1px solid rgba(95,138,63,0.4)", borderRadius: 20, padding: "2px 8px" } as const;

// A goal's home: the launch form (guidance is the steering wheel) plus the runs
// history. Goals themselves are created via the CLI; this page only runs them.
export function AlchemyGoalDetail() {
  const { goalRef } = useParams<{ goalRef: string }>();
  const nav = useNavigate();
  const { canWrite } = useAuth();

  const [goal, setGoal] = useState<AlchemyGoal | null>(null);
  const [runs, setRuns] = useState<AlchemyRunSummary[] | null>(null);
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const [model, setModel] = useState("");            // an endpoint name
  const [coverage, setCoverage] = useState("search");
  const [guidance, setGuidance] = useState("");
  const [maxCalls, setMaxCalls] = useState("");      // empty = no cap
  const [concurrency, setConcurrency] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<AlchemyRunSummary | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [finalizeTarget, setFinalizeTarget] = useState<AlchemyRunSummary | null>(null);
  const [finalizing, setFinalizing] = useState(false);

  useEffect(() => {
    if (!goalRef) return;
    api.getAlchemyGoal(goalRef).then((g) => { setGoal(g); setCoverage(g.coverage); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load goal"));
    api.listLlmEndpoints().then((eps) => {
      setEndpoints(eps);
      setModel((m) => m || ((eps.find((e) => e.is_default) ?? eps[0])?.name ?? ""));
    }).catch(() => setEndpoints([]));
  }, [goalRef]);

  const loadRuns = () => {
    if (!goalRef) return;
    api.listAlchemyRuns(goalRef).then(setRuns).catch(() => setRuns([]));
  };
  useEffect(loadRuns, [goalRef]);
  usePolling(loadRuns, 2500, (runs ?? []).some((r) => ACTIVE(r.status)));

  const ep = endpoints.find((e) => e.name === model) ?? null;
  const canLaunch = goal != null && ep != null && !busy && canWrite;

  const launch = async () => {
    if (goal == null || ep == null) return;
    setBusy(true); setError(null);
    try {
      const body: AlchemyRunLaunch = {
        coverage: coverage as AlchemyRunLaunch["coverage"],
        llm: { provider: ep.provider, model: ep.model },
        concurrency,
      };
      if (guidance.trim()) body.guidance = guidance.trim();
      const cap = Number.parseInt(maxCalls, 10);
      if (Number.isFinite(cap) && cap >= 1) body.max_llm_calls = cap;
      const run = await api.launchAlchemyRun(goal.id, body);
      setGuidance("");
      nav(`/alchemy/${goal.id}/runs/${run.version}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Launch failed");
    } finally { setBusy(false); }
  };

  const handleCancel = async () => {
    if (cancelTarget == null) return;
    setCancelling(true);
    try {
      await api.cancelAlchemyRun(cancelTarget.id);   // DB id, not the version
      loadRuns();
      setCancelTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
      setCancelTarget(null);  // close so the error banner isn't hidden behind the backdrop
    } finally { setCancelling(false); }
  };

  const handleFinalize = async () => {
    if (finalizeTarget == null || !goalRef) return;
    setFinalizing(true);
    try {
      await api.finalizeAlchemyRun(goalRef, finalizeTarget.version);
      loadRuns();
      setFinalizeTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Finalize failed");
      setFinalizeTarget(null);
    } finally { setFinalizing(false); }
  };

  if (error && goal == null)
    return <Panel style={{ padding: 28 }}><p style={{ color: "var(--oxblood)" }}>{error}</p></Panel>;
  if (goal == null)
    return <Panel style={{ padding: 28 }}><p style={mono(12, "var(--ink-muted)")}>Loading goal...</p></Panel>;

  const list = runs ?? [];

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 1080 }}>
      <BackLink to="/alchemy">Alchemy</BackLink>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
        <Heading level={1} style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{goal.name}</Heading>
        <span style={{ fontSize: 11, background: "rgba(156,121,32,0.16)", borderRadius: 5,
          padding: "2px 8px", color: "var(--ink-muted)" }}>{goal.goal_type}</span>
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap", ...mono(12, "var(--ink-muted)") }}>
        <span>corpus {goal.corpus_id}</span>
        <span>coverage {goal.coverage}</span>
        {goal.include_generated && <span>includes generated docs</span>}
      </div>

      {/* LAUNCH FORM */}
      <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
        padding: 18, marginTop: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 14 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
              textTransform: "uppercase" }}>Coverage</span>
            <SegmentedToggle value={coverage} onChange={setCoverage}
              options={[{ value: "search", label: "Search" }, { value: "full", label: "Full" },
                { value: "exhaustive", label: "Exhaustive" }]} />
          </label>
          {endpoints.length === 0 ? (
            <span style={{ fontSize: 12.5, color: "var(--oxblood)" }}>
              needs an LLM endpoint - add one in Settings</span>
          ) : (
            <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
                textTransform: "uppercase" }}>Model</span>
              <select aria-label="Model" value={model} onChange={(e) => setModel(e.target.value)}
                style={selectStyle}>
                {endpoints.map((e) => <option key={e.id} value={e.name}>{e.name}</option>)}
              </select>
            </label>
          )}
        </div>

        <textarea aria-label="Guidance" placeholder="Optional guidance for this run (steer, correct, focus)"
          value={guidance} onChange={(e) => setGuidance(e.target.value)}
          style={{ width: "100%", minHeight: 68, resize: "vertical", background: "var(--parchment-panel)",
            border: "1px solid var(--frame-rule)", borderRadius: 9, padding: "13px 14px",
            fontFamily: "var(--font-ui)", fontSize: 14, color: "var(--ink)", lineHeight: 1.5,
            boxSizing: "border-box" }} />

        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", marginTop: 13 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={mono(11, "var(--ink-muted)")}>Max LLM calls</span>
            <input aria-label="Max LLM calls" type="number" min={1} value={maxCalls} placeholder="none"
              onChange={(e) => setMaxCalls(e.target.value)}
              style={{ ...selectStyle, width: 80 }} />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={mono(11, "var(--ink-muted)")}>Concurrency</span>
            <input aria-label="Concurrency" type="number" min={1} max={8} value={concurrency}
              onChange={(e) => setConcurrency(
                Math.min(8, Math.max(1, Number.parseInt(e.target.value, 10) || 1)))}
              style={{ ...selectStyle, width: 60 }} />
          </label>
          <span style={{ marginLeft: "auto" }}>
            <Button onClick={launch} disabled={!canLaunch}>
              {busy ? "Launching..." : "Run"}</Button>
          </span>
        </div>
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13, marginTop: 16 }}>{error}</p>}

      {/* RUNS */}
      <div style={{ marginTop: 28 }}>
        <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase",
          marginBottom: 10 }}>Runs</div>
        {runs !== null && list.length === 0 ? (
          <EmptyState title="No runs yet" hint="Launch the first run above." />
        ) : (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, padding: "10px 14px",
              fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
              textTransform: "uppercase", color: "var(--ink-faint)",
              borderBottom: "1px solid var(--frame-rule)" }}>
              <div>Ver</div><div>Status</div><div>Coverage</div><div>Guidance</div>
              <div>Calls</div><div>Final</div><div>Stopped</div><div>Created</div>
              <div style={{ textAlign: "right" }}>Actions</div>
            </div>
            {list.map((r) => <RunRow key={r.id} run={r} goalId={goal.id} canWrite={canWrite}
              onCancel={() => setCancelTarget(r)} onFinalize={() => setFinalizeTarget(r)} />)}
          </div>
        )}
      </div>

      <ConfirmDialog open={cancelTarget != null} title={`Cancel v${cancelTarget?.version}?`}
        confirmLabel="Cancel run" danger busy={cancelling}
        onConfirm={handleCancel} onClose={() => setCancelTarget(null)}>
        The agent stops as soon as it can; the draft stays as far as it got.
      </ConfirmDialog>
      <ConfirmDialog open={finalizeTarget != null} title="Finalize this version?"
        confirmLabel={`Finalize v${finalizeTarget?.version ?? ""}`} busy={finalizing}
        onConfirm={handleFinalize} onClose={() => setFinalizeTarget(null)}>
        Marks this draft as the goal's final version.
      </ConfirmDialog>
    </Panel>
  );
}

function RunRow({ run, goalId, canWrite, onCancel, onFinalize }:
  { run: AlchemyRunSummary; goalId: number; canWrite: boolean;
    onCancel: () => void; onFinalize: () => void }) {
  const actBtn = { fontSize: 12, padding: "4px 10px", borderRadius: 6,
    cursor: canWrite ? "pointer" : "default", fontFamily: "var(--font-ui)",
    background: "transparent", opacity: canWrite ? 1 : 0.5 } as const;
  // Buttons live inside the row Link; stop the click from navigating.
  const act = (fn: () => void) => (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault(); e.stopPropagation(); fn();
  };
  return (
    <Link to={`/alchemy/${goalId}/runs/${run.version}`}
      style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center",
        padding: "13px 14px", color: "var(--ink)", textDecoration: "none",
        borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600 }}>v{run.version}</span>
      <StatusDot status={run.status} />
      <span style={mono(12, "var(--ink-muted)")}>{run.coverage}</span>
      <span style={{ fontSize: 12.5, color: "var(--ink-muted)", overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{run.guidance || DASH}</span>
      <span style={mono(12, "var(--ink-muted)")}>{run.usage?.llm_calls ?? DASH}</span>
      <span>{run.is_final ? <span style={finalPill}>final</span> : DASH}</span>
      <span style={mono(11)}>{run.stop_reason ?? DASH}</span>
      <span style={mono(11)}>{run.created_at ? new Date(run.created_at).toLocaleDateString() : DASH}</span>
      <span style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        {ACTIVE(run.status) && (
          <button type="button" disabled={!canWrite} onClick={act(onCancel)}
            style={{ ...actBtn, border: "1px solid var(--oxblood)", color: "var(--oxblood)" }}>
            Cancel</button>
        )}
        {run.status === "done" && !run.is_final && (
          <button type="button" disabled={!canWrite} onClick={act(onFinalize)}
            style={{ ...actBtn, border: "1px solid var(--frame-rule)", color: "var(--ink)" }}>
            Finalize</button>
        )}
      </span>
    </Link>
  );
}

export default AlchemyGoalDetail;
