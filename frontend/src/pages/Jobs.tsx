import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { Heading, Panel, StatusDot } from "../design/primitives";
import { usePolling } from "../hooks/usePolling";
import { BuildConsole } from "./BuildConsole";

type Filter = "all" | "running" | "failed";

const GRID = "2.4fr 0.8fr 1fr 0.9fr";
const DASH = <span style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>—</span>;

// "5m ago" style stamp for the Started column. Best-effort: a missing or unparseable
// timestamp just renders a dash. Kept loose on purpose -- the value is glanceable
// recency, not an exact clock.
function timeAgo(iso?: string | null): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function Jobs() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    try { setJobs(await api.listJobs()); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load jobs"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const list = jobs ?? [];
  const running = list.some((j) => j.status === "building");
  usePolling(load, 2500, running);   // only poll while something is still building

  const counts = {
    all: list.length,
    running: list.filter((j) => j.status === "building").length,
    failed: list.filter((j) => j.status === "failed").length,
  };
  const rows = list.filter((j) =>
    filter === "all" ? true
      : filter === "running" ? j.status === "building"
        : j.status === "failed");

  const chip = (key: Filter, text: string) => (
    <span onClick={() => setFilter(key)} data-active={filter === key ? "true" : "false"}
      style={{ fontSize: 12, cursor: "pointer", borderRadius: 20, padding: "5px 13px",
        fontWeight: filter === key ? 600 : 400,
        color: filter === key ? "var(--ink)" : "#473c29",
        background: filter === key ? "#d3c4a3" : "transparent",
        border: "1px solid rgba(120,95,40,0.28)" }}>{text}</span>
  );

  return (
    <Panel style={{ padding: "30px 32px" }}>
      <Heading level={1} style={{ margin: 0 }}>Jobs</Heading>
      <p style={{ fontSize: 13.5, color: "var(--ink-muted)", margin: "9px 0 0", maxWidth: 560,
        lineHeight: 1.55 }}>
        Every build happening across the library — document ingests and the pipelines you build on
        them. Start a build, leave the page, and watch it finish here. Live while anything is running.
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "22px 0 4px",
        flexWrap: "wrap" }}>
        {chip("all", `All ${counts.all}`)}
        {chip("running", `Running ${counts.running}`)}
        {chip("failed", `Failed ${counts.failed}`)}
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 13 }}>{error}</p>}
      {jobs === null && !error &&
        <p style={{ color: "var(--ink-faint)", fontSize: 13 }}>Loading…</p>}

      {jobs !== null && rows.length === 0 && !error && (
        <div style={{ marginTop: 28, border: "1.5px dashed rgba(120,95,40,0.42)", borderRadius: 14,
          padding: "48px 40px", textAlign: "center", background: "rgba(252,247,237,0.25)" }}>
          <div style={{ fontSize: 36, opacity: 0.7 }} aria-hidden>⚙️</div>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 500,
            marginTop: 14 }}>
            {filter === "all" ? "Nothing building right now" : `No ${filter} jobs`}</div>
          <p style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.6,
            margin: "10px auto 0", maxWidth: 380 }}>
            Upload a document or build a pipeline and it'll show up here while it indexes.</p>
        </div>
      )}

      {jobs !== null && rows.length > 0 && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 12, padding: "12px 14px",
            fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-faint)",
            borderBottom: "1px solid var(--frame-rule)" }}>
            <div>Job</div><div>Kind</div><div>Status</div>
            <div style={{ textAlign: "right" }}>Started</div>
          </div>
          {rows.map((j) => <Row key={j.pipeline_id} job={j} />)}
        </div>
      )}
    </Panel>
  );
}

function Row({ job }: { job: Job }) {
  const cells = (
    <>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 13.5, fontWeight: 500,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{job.name}</div>
        <div style={{ fontSize: 11, color: "var(--ink-faint)", whiteSpace: "nowrap",
          overflow: "hidden", textOverflow: "ellipsis" }}>{job.document_filename}</div>
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-muted)" }}>
        {job.kind === "ingest" ? "ingest" : "build"}</div>
      <StatusDot status={job.status} />
      <div style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontSize: 11.5,
        color: "var(--ink-muted)" }}>{timeAgo(job.created_at) || DASH}</div>
    </>
  );
  const style = { display: "grid", gridTemplateColumns: GRID, gap: 12, alignItems: "center",
    padding: "15px 14px", color: "var(--ink)", textDecoration: "none" } as const;
  return (
    <div style={{ borderBottom: "1px solid rgba(120,95,40,0.13)" }}>
      <Link to={`/documents/${job.document_id}`} style={style}>{cells}</Link>
      {/* Live console while building, so you can watch it without opening the doc. */}
      {job.status === "building" && (
        <div style={{ padding: "0 14px 14px" }}><BuildConsole progress={job.progress} compact /></div>
      )}
      {job.status === "failed" && job.error && (
        <div style={{ padding: "0 14px 14px" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--oxblood)",
            background: "rgba(132,48,31,0.08)", border: "1px solid rgba(132,48,31,0.25)",
            borderRadius: 6, padding: "8px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: 120, overflowY: "auto" }}>{job.error}</div>
        </div>
      )}
    </div>
  );
}

export default Jobs;
