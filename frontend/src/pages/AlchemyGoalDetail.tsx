import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AlchemyGoal, AlchemyRunSummary } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { Panel, Heading, StatusDot, EmptyState } from "../design/primitives";
import { BackLink } from "../design/Frame";

const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });
const ACTIVE = (s: string) => s === "pending" || s === "running";
const GRID = "0.55fr 0.95fr 0.75fr 1.7fr 0.55fr 0.55fr 0.85fr 0.9fr 1.05fr";
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{"\u2014"}</span>;

const finalPill = { fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: "0.08em",
  textTransform: "uppercase", background: "rgba(95,138,63,0.18)", color: "#4a7a3c",
  border: "1px solid rgba(95,138,63,0.4)", borderRadius: 20, padding: "2px 8px" } as const;

export function AlchemyGoalDetail() {
  const { goalRef } = useParams<{ goalRef: string }>();
  const [goal, setGoal] = useState<AlchemyGoal | null>(null);
  const [runs, setRuns] = useState<AlchemyRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!goalRef) return;
    api.getAlchemyGoal(goalRef).then(setGoal)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load goal"));
  }, [goalRef]);

  const loadRuns = () => {
    if (!goalRef) return;
    api.listAlchemyRuns(goalRef).then(setRuns).catch(() => setRuns([]));
  };
  useEffect(loadRuns, [goalRef]);
  usePolling(loadRuns, 2500, (runs ?? []).some((r) => ACTIVE(r.status)));

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
            {list.map((r) => <RunRow key={r.id} run={r} goalId={goal.id} />)}
          </div>
        )}
      </div>
    </Panel>
  );
}

function RunRow({ run, goalId }: { run: AlchemyRunSummary; goalId: number }) {
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
      <span />
    </Link>
  );
}

export default AlchemyGoalDetail;
