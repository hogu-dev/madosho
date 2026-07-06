import { Link } from "react-router-dom";
import { Panel, Heading } from "../design/primitives";

export function NotFound() {
  return (
    <Panel style={{ textAlign: "center", padding: 64 }}>
      <Heading level={1} style={{ fontSize: 56 }}>404</Heading>
      <p style={{ color: "var(--ink-muted)" }}>This page has slipped from the archive.</p>
      <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 20 }}>
        <Link to="/documents" style={{ padding: "8px 16px", borderRadius: 8,
          background: "var(--amber-grad)", color: "var(--amber-text)",
          fontWeight: 600, textDecoration: "none" }}>Return to Documents</Link>
        <Link to="/scrying" style={{ padding: "8px 16px", borderRadius: 8,
          border: "1px solid var(--frame-rule)", color: "var(--ink)",
          textDecoration: "none" }}>Open Scrying</Link>
      </div>
    </Panel>
  );
}
