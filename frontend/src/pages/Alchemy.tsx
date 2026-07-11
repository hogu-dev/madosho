import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AlchemyGoal } from "../api/types";
import { Panel, Heading, EmptyState } from "../design/primitives";

const GRID = "2fr 1.1fr 0.7fr 0.9fr 1.1fr";
const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{"\u2014"}</span>;

function fmtDate(iso: string | null): string | null {
  return iso ? new Date(iso).toLocaleDateString() : null;
}

// Goals are authored from the CLI (madosho alchemy create ...); this page is a
// read-only index into them. Row links carry the numeric goal id, the name is
// only a label.
export function Alchemy() {
  const [goals, setGoals] = useState<AlchemyGoal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listAlchemyGoals().then(setGoals)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load goals"));
  }, []);

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 980 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Heading level={1} style={{ margin: 0 }}>Alchemy</Heading>
        <span style={{ ...mono(11, "var(--gilt)"), letterSpacing: "0.08em", textTransform: "uppercase",
          border: "1px solid var(--frame-rule)", borderRadius: 20, padding: "3px 10px" }}>autonomous</span>
      </div>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 22px", maxWidth: 620,
        lineHeight: 1.55 }}>
        Named, versioned goals an agent pursues over a corpus. Each run produces a new draft
        version; finalize the one you trust.</p>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {goals === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading...</p>}

      {goals !== null && goals.length === 0 && !error && (
        <EmptyState title="No alchemy goals yet"
          hint="Goals are created from the CLI: madosho alchemy create <name> --corpus <corpus>" />
      )}

      {goals !== null && goals.length > 0 && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, padding: "12px 14px",
            fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-faint)",
            borderBottom: "1px solid var(--frame-rule)" }}>
            <div>Goal</div><div>Type</div><div>Corpus</div><div>Coverage</div>
            <div style={{ textAlign: "right" }}>Created</div>
          </div>
          {goals.map((g) => (
            <Link key={g.id} to={`/alchemy/${g.id}`}
              style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center",
                padding: "15px 14px", color: "var(--ink)", textDecoration: "none",
                borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 13.5, fontWeight: 500,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{g.name}</span>
              <span><span style={{ fontSize: 11, background: "rgba(156,121,32,0.16)", borderRadius: 5,
                padding: "2px 8px", color: "var(--ink-muted)" }}>{g.goal_type}</span></span>
              <span style={mono(12, "var(--ink-muted)")}>#{g.corpus_id}</span>
              <span style={mono(12, "var(--ink-muted)")}>{g.coverage}</span>
              <span style={{ ...mono(11), textAlign: "right" }}>{fmtDate(g.created_at) ?? DASH}</span>
            </Link>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default Alchemy;
