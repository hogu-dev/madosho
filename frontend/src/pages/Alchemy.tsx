import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AlchemyGoal, Corpus } from "../api/types";
import { Panel, Heading, Button, SegmentedToggle, EmptyState } from "../design/primitives";
import { useAuth } from "../auth/AuthContext";

const GRID = "2fr 1.1fr 0.7fr 0.9fr 1.1fr";
const mono = (size = 11, color = "var(--ink-faint)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{"—"}</span>;

const fieldLabel = { ...mono(10, "var(--ink-muted)"), letterSpacing: "0.08em",
  textTransform: "uppercase" as const, marginBottom: 5, display: "block" };
const inputStyle = {
  width: "100%", boxSizing: "border-box" as const, fontSize: 13.5,
  fontFamily: "var(--font-ui)", padding: "8px 11px", border: "1px solid var(--frame-rule)",
  borderRadius: 7, background: "var(--parchment-panel)", color: "var(--ink)",
} as const;

function fmtDate(iso: string | null): string | null {
  return iso ? new Date(iso).toLocaleDateString() : null;
}

// Goals are authored either from this page's New-goal form or the CLI
// (madosho alchemy create ...); both POST /alchemy/goals. The list below is a
// read-only index - row links open a goal's detail page, where runs are launched.
export function Alchemy() {
  const { canWrite } = useAuth();
  const nav = useNavigate();
  const [goals, setGoals] = useState<AlchemyGoal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // New-goal form state.
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [name, setName] = useState("");
  const [corpusId, setCorpusId] = useState<number | "">("");
  const [goalType, setGoalType] = useState("living-research");
  const [goalText, setGoalText] = useState("");
  const [template, setTemplate] = useState("");
  const [coverage, setCoverage] = useState("search");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadGoals = () => {
    api.listAlchemyGoals().then(setGoals)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load goals"));
  };
  useEffect(loadGoals, []);
  useEffect(() => {
    if (!canWrite) return;
    api.listCorpora().then(setCorpora).catch(() => setCorpora([]));
  }, [canWrite]);
  useEffect(() => {
    if (corpusId === "" && corpora.length > 0) setCorpusId(corpora[0].id);
  }, [corpora, corpusId]);

  // report needs a template (markdown headings become sections); living-research
  // needs the goal text. Mirror the server's compile rules so we do not POST a
  // spec the API will 400.
  const specReady = goalType === "report" ? template.trim() !== "" : goalText.trim() !== "";
  const canCreate = canWrite && name.trim() !== "" && corpusId !== "" && specReady && !creating;

  const create = async () => {
    if (corpusId === "") return;
    setCreating(true); setFormError(null);
    const spec = goalType === "report"
      ? { ...(goalText.trim() ? { goal: goalText.trim() } : {}), template: template.trim() }
      : { goal: goalText.trim() };
    try {
      const g = await api.createAlchemyGoal({
        name: name.trim(), corpus_id: corpusId, goal_type: goalType,
        spec, coverage: coverage as AlchemyGoal["coverage"],
      });
      nav(`/alchemy/${g.id}`);   // straight to the goal's page to launch the first run
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Create failed");
    } finally { setCreating(false); }
  };

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

      {/* NEW GOAL FORM (write scope only) */}
      {canWrite && (
        <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
          padding: 18, marginBottom: 26 }}>
          <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em",
            textTransform: "uppercase", marginBottom: 14 }}>New goal</div>

          <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 14, marginBottom: 14 }}>
            <div>
              <label style={fieldLabel} htmlFor="goal-name">Name</label>
              <input id="goal-name" aria-label="Name" value={name} placeholder="aero-flight-control-brief"
                onChange={(e) => setName(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={fieldLabel} htmlFor="goal-corpus">Corpus</label>
              <select id="goal-corpus" aria-label="Corpus" value={corpusId}
                onChange={(e) => setCorpusId(e.target.value === "" ? "" : Number(e.target.value))}
                style={inputStyle}>
                {corpora.length === 0 && <option value="">no corpora</option>}
                {corpora.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>

          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 14 }}>
            <div>
              <span style={fieldLabel}>Type</span>
              <SegmentedToggle value={goalType} onChange={setGoalType}
                options={[{ value: "living-research", label: "Living research" },
                  { value: "report", label: "Report" }]} />
            </div>
            <div>
              <span style={fieldLabel}>Coverage</span>
              <SegmentedToggle value={coverage} onChange={setCoverage}
                options={[{ value: "search", label: "Search" }, { value: "full", label: "Full" },
                  { value: "exhaustive", label: "Exhaustive" }]} />
            </div>
          </div>

          <div style={{ marginBottom: goalType === "report" ? 14 : 0 }}>
            <label style={fieldLabel} htmlFor="goal-text">
              {goalType === "report" ? "Preamble (optional)" : "Goal"}</label>
            <textarea id="goal-text" aria-label="Goal" value={goalText}
              onChange={(e) => setGoalText(e.target.value)}
              placeholder={goalType === "report"
                ? "Optional framing for the whole report"
                : "What should the agent pursue over this corpus? (e.g. Summarize how photosynthesis stores energy, using only the corpus.)"}
              style={{ ...inputStyle, minHeight: 62, resize: "vertical", lineHeight: 1.5 }} />
          </div>

          {goalType === "report" && (
            <div>
              <label style={fieldLabel} htmlFor="goal-template">Template (markdown headings become sections)</label>
              <textarea id="goal-template" aria-label="Template" value={template}
                onChange={(e) => setTemplate(e.target.value)}
                placeholder={"## Flight control approach\n## Notable risks or failures\n## Program status"}
                style={{ ...inputStyle, minHeight: 84, resize: "vertical", lineHeight: 1.5,
                  fontFamily: "var(--font-mono)", fontSize: 12.5 }} />
            </div>
          )}

          {formError && <p style={{ color: "var(--oxblood)", fontSize: 13, margin: "12px 0 0" }}>{formError}</p>}

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 15 }}>
            <Button onClick={create} disabled={!canCreate}>
              {creating ? "Creating..." : "Create goal"}</Button>
          </div>
        </div>
      )}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {goals === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading...</p>}

      {goals !== null && goals.length === 0 && !error && (
        <EmptyState title="No alchemy goals yet"
          hint={canWrite
            ? "Create your first goal with the form above (or the CLI: madosho alchemy create <name> --corpus <corpus>)."
            : "Goals are created from the CLI: madosho alchemy create <name> --corpus <corpus>"} />
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
