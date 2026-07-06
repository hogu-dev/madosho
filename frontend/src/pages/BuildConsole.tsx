import type { IngestProgress } from "../api/types";

// The live build feed (phase + rolling log) the worker publishes while a pipeline
// indexes. Shared by the Workbench pipeline card and the Documents library row so
// both show the same console. `compact` trims the chrome for the dense list row.
export function BuildConsole({ progress, compact }:
  { progress?: IngestProgress; compact?: boolean }) {
  const log = progress?.log ?? [];
  const phase = progress?.phase;
  return (
    <div style={{ marginTop: compact ? 8 : 14 }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-muted)",
        marginBottom: 8 }}>building{phase ? ` · ${phase}` : ""}</div>
      <div style={{ background: "#241a10", color: "#e6dabd", borderRadius: 8, padding: "12px 14px",
        fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.7,
        maxHeight: compact ? 130 : 160, overflowY: "auto" }}>
        {log.length === 0
          ? <span style={{ opacity: 0.6 }}>
              {phase ? `${phase}…` : "starting…"} loading models and parsing — the first document
              can take a minute<BlinkingCursor />
            </span>
          : log.map((line, i) => <div key={i}>{line.msg}</div>)}
      </div>
    </div>
  );
}

function BlinkingCursor() {
  return (
    <span style={{ marginLeft: 4, animation: "madoshoBlink 1.1s step-start infinite" }}>
      ▌<style>{"@keyframes madoshoBlink{50%{opacity:0}}"}</style>
    </span>
  );
}
