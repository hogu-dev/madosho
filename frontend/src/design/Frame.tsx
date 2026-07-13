import "./tokens.css";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useRunningJobsCount } from "../hooks/useRunningJobsCount";

export function NavItem(
  { to, label, subtitle, active, badge }:
  { to: string; label: string; subtitle?: string; active: boolean; badge?: number },
) {
  return (
    <Link to={to} data-active={active ? "true" : "false"} style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "7px 10px", borderRadius: 6, textDecoration: "none",
      fontFamily: "var(--font-ui)", fontSize: 14,
      color: active ? "var(--parchment-text)" : "var(--nav-inactive)",
      fontWeight: active ? 600 : 400,
      borderLeft: active ? "3px solid var(--gilt-bright)" : "3px solid transparent",
      background: active ? "rgba(200,162,74,0.1)" : "transparent",
    }}>
      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {active && <span aria-hidden style={{ width: 5, height: 5, borderRadius: 999,
            background: "var(--gilt-bright)" }} />}
          {label}
        </span>
        {/* Plain-language descriptor under the thematic name, so newcomers know
            what each surface is without having to open it. */}
        {subtitle && <span style={{ fontFamily: "var(--font-ui)", fontSize: 10.5,
          fontWeight: 400, lineHeight: 1.3, color: "var(--nav-label)", whiteSpace: "nowrap",
          overflow: "hidden", textOverflow: "ellipsis" }}>{subtitle}</span>}
      </span>
      {badge != null && <span style={{ fontFamily: "var(--font-mono)", fontSize: 11,
        color: "var(--nav-label)", flex: "0 0 auto" }}>{badge}</span>}
    </Link>
  );
}

function GroupLabel({ children }: { children: ReactNode }) {
  return <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.12em",
    textTransform: "uppercase", color: "var(--nav-label)", padding: "0 10px",
    margin: "14px 0 6px" }}>{children}</div>;
}

function AccountFooter() {
  const { authRequired, name, scope, logout } = useAuth();
  // Only meaningful when auth is on and a principal is signed in. With auth off
  // there is no session to end, so the footer stays hidden.
  if (!authRequired || !name) return null;
  return (
    <div style={{ marginTop: 10, paddingTop: 12, borderTop: "1px solid rgba(0,0,0,0.35)",
      display: "flex", alignItems: "center", gap: 10, padding: "12px 10px 2px" }}>
      <span aria-hidden style={{ width: 28, height: 28, borderRadius: 999, flex: "0 0 28px",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(200,162,74,0.16)", color: "var(--gilt-bright)",
        fontFamily: "var(--font-serif)", fontSize: 14, fontWeight: 600,
        border: "1px solid rgba(156,121,32,0.4)" }}>
        {name.charAt(0).toUpperCase()}
      </span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--parchment-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{name}</div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--nav-label)" }}>{scope}</div>
      </div>
      <button onClick={logout} title="Sign out" style={{ background: "transparent",
        border: "1px solid rgba(156,121,32,0.4)", borderRadius: 6, cursor: "pointer",
        color: "var(--nav-inactive)", fontFamily: "var(--font-ui)", fontSize: 12,
        padding: "5px 9px" }}>Sign out</button>
    </div>
  );
}

function isActive(pathname: string, to: string): boolean {
  if (to === "/documents" && pathname === "/") return true;
  return pathname === to || pathname.startsWith(to + "/");
}

export function Sidebar() {
  const { pathname } = useLocation();
  const { scope } = useAuth();
  const running = useRunningJobsCount();   // live "N building" badge on Jobs
  const item = (to: string, label: string, subtitle?: string, badge?: number) =>
    <NavItem key={to} to={to} label={label} subtitle={subtitle}
      active={isActive(pathname, to)} badge={badge} />;
  return (
    <aside style={{ width: 248, flex: "0 0 248px", background: "var(--leather)",
      borderRight: "1px solid #000", padding: "16px 8px", display: "flex",
      flexDirection: "column", minHeight: "100vh" }}>
      <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600,
        color: "var(--gilt-bright)", padding: "0 10px 8px" }}>madosho</div>
      <GroupLabel>Library</GroupLabel>
      {item("/documents", "Documents", "Source files, indexed once")}
      {item("/corpora", "Corpora", "Document collections")}
      {item("/jobs", "Jobs", "Background builds", running > 0 ? running : undefined)}
      <GroupLabel>Measure &amp; use</GroupLabel>
      {item("/scrying", "Scrying", "Query & cited answer")}
      {item("/compare", "Compare", "Pipelines side by side")}
      {item("/quality", "Quality", "Ratings scoreboard")}
      {item("/research", "Research", "Agentic cited reports")}
      {item("/alchemy", "Alchemy", "Autonomous multi-agent")}
      <div style={{ flex: 1 }} />
      {item("/settings", "Settings", "Endpoints & config")}
      {scope === "admin" && item("/users", "Users", "Accounts")}
      {item("/keys", "Keys", "API keys")}
      <AccountFooter />
    </aside>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--crumb-link)",
      display: "flex", gap: 6, alignItems: "center" }}>
      {items.map((it, i) => (
        <span key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {i > 0 && <span aria-hidden style={{ opacity: 0.5 }}>/</span>}
          {it.to
            ? <Link to={it.to} style={{ color: "var(--crumb-link)" }}>{it.label}</Link>
            : <span style={{ color: "var(--parchment-text)" }}>{it.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link to={to} style={{ fontFamily: "var(--font-mono)", fontSize: 12,
    color: "var(--crumb-link)" }}>&larr; {children}</Link>;
}

export function Frame({ children, topbar }: { children: ReactNode; topbar?: ReactNode }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* gilt spine pinned to the sidebar's right edge */}
      <div style={{ position: "relative" }}>
        <Sidebar />
        <div aria-hidden style={{ position: "absolute", top: 0, right: 0, width: 11, height: "100%",
          background: "linear-gradient(90deg, #6f561b, var(--gilt-bright), #4a3a12)" }} />
      </div>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <header style={{ height: 54, flex: "0 0 54px", background: "var(--leather)",
          borderBottom: "1px solid #000", display: "flex", alignItems: "center",
          padding: "0 24px" }}>{topbar}</header>
        <div style={{ flex: 1, padding: 24 }}>
          {/* Full-width frame, filled with parchment so no page background shows
              through to the right of a narrower content panel. Each page caps its
              own content maxWidth and left-aligns within this filled frame. */}
          <div style={{ position: "relative", borderRadius: 8,
            background: "var(--parchment-panel)",
            border: "1px solid var(--frame-rule)",
            boxShadow: "0 12px 40px rgba(18,11,4,0.34), inset 0 0 0 4px #e6dabd, inset 0 0 0 5px rgba(156,121,32,0.45)" }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
