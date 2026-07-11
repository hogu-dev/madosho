import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { AlchemyGoal, AlchemyRun } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { Panel, Heading, StatusDot, Button } from "../design/primitives";
import { BackLink } from "../design/Frame";

const mono = (size = 12, color = "var(--ink-muted)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

const serif = { fontFamily: "var(--font-serif)" as const };

const SECTION_GRID = "1.6fr 0.5fr 1.4fr 1.8fr";
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{"\u2014"}</span>;

// Same markdown component map as ResearchRun.tsx (copied, not imported) so the
// draft reads like a report, not literal ### and **.
const reportMd = {
  p: (p: any) => <p style={{ ...serif, fontSize: 15, lineHeight: 1.65, margin: "0 0 11px" }} {...p} />,
  h1: (p: any) => <h2 style={{ ...serif, fontSize: 20, fontWeight: 700, margin: "20px 0 10px" }} {...p} />,
  h2: (p: any) => <h3 style={{ ...serif, fontSize: 17, fontWeight: 700, margin: "16px 0 8px" }} {...p} />,
  h3: (p: any) => <h4 style={{ ...serif, fontSize: 15.5, fontWeight: 700, margin: "13px 0 7px" }} {...p} />,
  ul: (p: any) => <ul style={{ ...serif, fontSize: 15, lineHeight: 1.65, margin: "0 0 11px", paddingLeft: 22 }} {...p} />,
  ol: (p: any) => <ol style={{ ...serif, fontSize: 15, lineHeight: 1.65, margin: "0 0 11px", paddingLeft: 22 }} {...p} />,
  li: (p: any) => <li style={{ marginBottom: 4 }} {...p} />,
  strong: (p: any) => <strong style={{ fontWeight: 700 }} {...p} />,
  em: (p: any) => <em style={{ fontStyle: "italic" }} {...p} />,
  a: (p: any) => <a style={{ color: "var(--gilt)" }} {...p} />,
  code: (p: any) => <code style={{ fontFamily: "var(--font-mono)", fontSize: 13,
    background: "rgba(120,95,40,0.10)", borderRadius: 4, padding: "1px 5px" }} {...p} />,
} as const;

// Confidence level -> pill color (matches the STATUS_COLORS red/amber/green ramp).
const CONF_COLORS: Record<string, string> = {
  low: "#a4442e", medium: "#a9711a", high: "#4a7a3c",
};

const finalPill = { fontSize: 10, fontFamily: "var(--font-mono)", letterSpacing: "0.08em",
  textTransform: "uppercase", background: "rgba(95,138,63,0.18)", color: "#4a7a3c",
  border: "1px solid rgba(95,138,63,0.4)", borderRadius: 20, padding: "2px 8px" } as const;

// Citation `source` is the stored chunk path; show just the filename.
export function basename(s: string | null): string | null {
  return s ? s.split("/").filter(Boolean).pop() ?? s : s;
}

// Save the draft markdown as a .md file, dependency-free (Blob + object URL).
function downloadDraft(run: AlchemyRun, goalName: string) {
  const blob = new Blob([run.draft_markdown ?? ""], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${goalName || "alchemy"}-v${run.version}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

// Pure viewer: draft, sections, coverage ledger, citations. All actions
// (run/cancel/finalize) live on the goal detail page.
export function AlchemyRunView() {
  const { goalRef, version } = useParams<{ goalRef: string; version: string }>();
  const v = Number(version);

  const [goal, setGoal] = useState<AlchemyGoal | null>(null);
  const [run, setRun] = useState<AlchemyRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!goalRef) return;
    api.getAlchemyGoal(goalRef).then(setGoal).catch(() => setGoal(null));
  }, [goalRef]);

  const load = () => {
    if (!goalRef || !Number.isFinite(v)) return;
    api.getAlchemyRun(goalRef, v).then(setRun).catch((e) => setError(String(e)));
  };
  useEffect(load, [goalRef, v]);
  usePolling(load, 2500, run?.status === "pending" || run?.status === "running");

  if (error)
    return <Panel style={{ padding: 28 }}><p style={{ color: "var(--oxblood)" }}>{error}</p></Panel>;
  if (!run)
    return <Panel style={{ padding: 28 }}><p style={mono()}>Loading run...</p></Panel>;

  const active = run.status === "pending" || run.status === "running";
  const sections = run.sections ?? [];
  const cites = run.citations ?? [];
  const ledger = run.ledger;
  const consultedCount = ledger ? Object.keys(ledger.consulted ?? {}).length : 0;

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 940 }}>
      <BackLink to={`/alchemy/${goalRef}`}>{goal?.name ?? "Goal"}</BackLink>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
        <Heading level={1} style={{ margin: 0, fontFamily: "var(--font-mono)" }}>
          {goal?.name ?? "alchemy"} v{run.version}</Heading>
        <StatusDot status={run.status} />
        {run.is_final && <span style={finalPill}>final</span>}
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap", ...mono(12) }}>
        <span>coverage {run.coverage}</span>
        {run.stop_reason && <span>stopped: {run.stop_reason}</span>}
        {run.based_on_version != null && <span>based on v{run.based_on_version}</span>}
        {run.usage?.llm_calls != null && <span>{run.usage.llm_calls} calls</span>}
        {run.usage?.total_tokens != null && <span>{run.usage.total_tokens} tokens</span>}
        {run.finished_at && <span>finished {new Date(run.finished_at).toLocaleString()}</span>}
      </div>

      {run.guidance && (
        <blockquote style={{ margin: "16px 0 0", padding: "10px 14px",
          borderLeft: "3px solid var(--gilt)", background: "rgba(156,121,32,0.07)",
          fontSize: 13.5, color: "var(--ink-muted)", fontStyle: "italic", lineHeight: 1.55 }}>
          {run.guidance}
        </blockquote>
      )}

      {active && (
        <p style={{ ...mono(12.5), marginTop: 20 }}>
          {run.progress?.phase ? `Working... ${run.progress.phase}` : "Working..."}</p>
      )}
      {run.status === "failed" && run.error && (
        <p style={{ color: "var(--oxblood)", fontSize: 13.5, marginTop: 20 }}>{run.error}</p>
      )}

      {ledger && (
        <div style={{ marginTop: 22, background: "var(--card)", border: "1px solid var(--frame-rule)",
          borderRadius: 10, padding: "13px 16px" }}>
          <div style={{ ...mono(10), letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 7 }}>Coverage ledger</div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", ...mono(12, "var(--ink)") }}>
            <span>consulted {consultedCount} / {ledger.total_docs} docs</span>
            {(ledger.from_prior?.length ?? 0) > 0 && <span>{ledger.from_prior.length} from prior</span>}
            <span style={{ color: ledger.complete ? "#4a7a3c" : "var(--oxblood)" }}>
              {ledger.complete ? "complete" : "incomplete"}</span>
          </div>
          {ledger.summary && <p style={{ fontSize: 12.5, color: "var(--ink-muted)",
            margin: "8px 0 0", lineHeight: 1.5 }}>{ledger.summary}</p>}
          {ledger.shortfall && <p style={{ fontSize: 12.5, color: "var(--oxblood)",
            margin: "8px 0 0", lineHeight: 1.5 }}>{ledger.shortfall}</p>}
        </div>
      )}

      {sections.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ ...mono(10), letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 10 }}>Sections</div>
          <div style={{ display: "grid", gridTemplateColumns: SECTION_GRID, gap: 12,
            padding: "9px 14px", fontFamily: "var(--font-mono)", fontSize: 10,
            letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--ink-faint)",
            borderBottom: "1px solid var(--frame-rule)" }}>
            <div>Section</div><div>Filled</div><div>Confidence</div><div>Note</div>
          </div>
          {sections.map((s) => (
            <div key={s.key} style={{ display: "grid", gridTemplateColumns: SECTION_GRID, gap: 12,
              alignItems: "center", padding: "11px 14px",
              borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
              <span style={{ fontSize: 13, color: "var(--ink)" }}>{s.title}</span>
              <span style={mono(12, s.filled ? "#4a7a3c" : "var(--oxblood)")}>
                {s.filled ? "yes" : "no"}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {s.confidence ? (
                  <>
                    <span style={{ fontSize: 10, fontFamily: "var(--font-mono)",
                      letterSpacing: "0.08em", textTransform: "uppercase", borderRadius: 20,
                      padding: "2px 8px", color: "#fff",
                      background: CONF_COLORS[s.confidence.level] ?? "var(--ink-faint)" }}>
                      {s.confidence.level}</span>
                    <span style={mono(11, "var(--ink-faint)")}>
                      {s.confidence.distinct_docs ?? 0} docs / {s.confidence.citations ?? 0} cites</span>
                  </>
                ) : DASH}
              </span>
              <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>
                {!s.filled && s.note ? s.note : ""}</span>
            </div>
          ))}
        </div>
      )}

      {run.draft_markdown && (
        <div style={{ marginTop: 26 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 10 }}>
            <div style={{ ...mono(10), letterSpacing: "0.12em", textTransform: "uppercase" }}>Draft</div>
            <Button variant="ghost" onClick={() => downloadDraft(run, goal?.name ?? "")}>
              Download .md</Button>
          </div>
          <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)",
            borderRadius: 12, padding: 22, color: "var(--ink)" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={reportMd}>
              {run.draft_markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {cites.length > 0 && (
        <div style={{ marginTop: 26 }}>
          <div style={{ ...mono(10), letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 10 }}>Citations {"\u00b7"} {cites.length}</div>
          {cites.map((c, i) => (
            <div key={i} style={{ background: "var(--card)", border: "1px solid var(--frame-rule)",
              borderRadius: 10, padding: "13px 16px", marginBottom: 9 }}>
              <p style={{ fontSize: 13.5, lineHeight: 1.55, margin: 0, color: "var(--ink)",
                fontStyle: "italic" }}>{c.quote}</p>
              <div style={{ marginTop: 9, display: "flex", alignItems: "center", gap: 10,
                flexWrap: "wrap" }}>
                {c.document_id != null
                  ? <Link to={`/documents/${c.document_id}`} style={{ ...mono(11, "var(--gilt)"),
                      textDecoration: "none" }}>
                      {[basename(c.source), c.pipeline].filter(Boolean).join(" \u00b7 ")
                        || `document ${c.document_id}`}</Link>
                  : <span style={mono(11, "var(--ink-faint)")}>{basename(c.source) ?? c.citation}</span>}
                {c.score != null && <span style={mono(11, "var(--ink-faint)")}>
                  score {c.score.toFixed(2)}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default AlchemyRunView;
