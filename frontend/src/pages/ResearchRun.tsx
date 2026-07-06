import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { ResearchRun as Run } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { Panel, Heading, StatusDot, Button } from "../design/primitives";

const mono = (size = 12, color = "var(--ink-muted)") =>
  ({ fontFamily: "var(--font-mono)" as const, fontSize: size, color });

const serif = { fontFamily: "var(--font-serif)" as const };

// Render the report's markdown the same way the Scrying answer does (commit
// 61010e9), tuned to this page's denser report scale -- headings, lists and
// bold show as formatting instead of literal ### and ** in the text.
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

// Citation `source` is the stored chunk path (e.g. /data/filestore/<hash>/contract.pdf).
// Keep the full value in the data for provenance, but show just the filename here.
export function basename(s: string | null): string | null {
  return s ? s.split("/").filter(Boolean).pop() ?? s : s;
}

// Save the report markdown as a .md file, dependency-free (Blob + object URL).
function downloadReport(run: Run) {
  const blob = new Blob([run.report_markdown ?? ""], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `research-${run.id}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ResearchRun() {
  const { runId } = useParams<{ runId: string }>();
  const id = Number(runId);
  const [params] = useSearchParams();
  const rawCorpus = params.get("corpus");
  const corpusId = rawCorpus && Number.isFinite(Number(rawCorpus)) ? Number(rawCorpus) : null;

  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (corpusId == null || !Number.isFinite(id)) return;
    api.getResearch(corpusId, id).then(setRun).catch((e) => setError(String(e)));
  };
  useEffect(load, [corpusId, id]);
  usePolling(load, 2500, run?.status === "pending" || run?.status === "running");

  if (corpusId == null)
    return <Panel style={{ padding: 28 }}><p style={{ color: "var(--oxblood)" }}>
      No corpus in the link — open this run from the Research page.</p></Panel>;
  if (error) return <Panel style={{ padding: 28 }}><p style={{ color: "var(--oxblood)" }}>{error}</p></Panel>;
  if (!run) return <Panel style={{ padding: 28 }}><p style={mono()}>Loading run…</p></Panel>;

  const cfg = run.config;
  const cites = run.citations ?? [];
  const active = run.status === "pending" || run.status === "running";

  return (
    <Panel style={{ padding: "28px 32px", maxWidth: 900 }}>
      <Link to="/research" style={{ ...mono(11, "var(--gilt)"), textDecoration: "none" }}>{"←"} Back to Research</Link>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
        <Heading level={1} style={{ margin: 0, fontFamily: "var(--font-mono)" }}>research #{run.id}</Heading>
        <StatusDot status={run.status} />
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap", ...mono(12, "var(--ink-muted)") }}>
        <span>corpus {run.corpus_id}</span>
        <span>{cfg.source === "whole-text" ? "whole text" : "RAG retrieval"}</span>
        {cfg.llm?.model && <span>{[cfg.llm.provider, cfg.llm.model].filter(Boolean).join(":")}</span>}
        <span>max {cfg.max_rounds} rounds</span>
        {run.stop_reason && <span>stopped: {run.stop_reason}</span>}
      </div>

      <p style={{ fontSize: 15, color: "var(--ink)", margin: "18px 0 0", lineHeight: 1.5,
        fontFamily: "var(--font-serif)" }}>{run.prompt}</p>

      {active && (
        <p style={{ ...mono(12.5, "var(--ink-muted)"), marginTop: 20 }}>
          {run.progress?.phase ? `Working… ${run.progress.phase}` : "Working…"}</p>
      )}

      {run.status === "failed" && run.error && (
        <p style={{ color: "var(--oxblood)", fontSize: 13.5, marginTop: 20 }}>{run.error}</p>
      )}

      {run.report_markdown && (
        <div style={{ marginTop: 26 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase" }}>
              Report</div>
            <Button variant="ghost" onClick={() => downloadReport(run)}>Download .md</Button>
          </div>
          <div style={{ background: "var(--card)", border: "1px solid var(--frame-rule)", borderRadius: 12,
            padding: 22, color: "var(--ink)" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={reportMd}>
              {run.report_markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {cites.length > 0 && (
        <div style={{ marginTop: 26 }}>
          <div style={{ ...mono(10, "var(--ink-muted)"), letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 10 }}>Citations · {cites.length}</div>
          {cites.map((c, i) => (
            <div key={i} style={{ background: "var(--card)", border: "1px solid var(--frame-rule)",
              borderRadius: 10, padding: "13px 16px", marginBottom: 9 }}>
              <p style={{ fontSize: 13.5, lineHeight: 1.55, margin: 0, color: "var(--ink)",
                fontStyle: "italic" }}>{c.quote}</p>
              <div style={{ marginTop: 9, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {c.document_id != null
                  ? <Link to={`/documents/${c.document_id}`} style={{ ...mono(11, "var(--gilt)"),
                      textDecoration: "none" }}>
                      {[basename(c.source), c.pipeline].filter(Boolean).join(" · ") || `document ${c.document_id}`}</Link>
                  : <span style={mono(11, "var(--ink-faint)")}>{basename(c.source) ?? c.citation}</span>}
                {c.score != null && <span style={mono(11, "var(--ink-faint)")}>score {c.score.toFixed(2)}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default ResearchRun;
