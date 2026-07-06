import "./tokens.css";
import type { CSSProperties, ReactNode } from "react";
import { STATUS_COLORS, scoreColor } from "./tokens";

export function Heading(
  { level = 1, children, style }:
  { level?: 1 | 2 | 3; children: ReactNode; style?: CSSProperties },
) {
  const Tag = (["h1", "h2", "h3"] as const)[level - 1];
  const size = { 1: 29, 2: 19, 3: 15 }[level];
  return (
    <Tag style={{
      fontFamily: "var(--font-serif)", fontWeight: 600, color: "var(--ink)",
      fontSize: size, letterSpacing: level === 1 ? "-0.01em" : undefined,
      margin: "0 0 12px", ...style,
    }}>{children}</Tag>
  );
}

export function Button(
  { children, onClick, type = "button", variant = "primary", disabled }:
  { children: ReactNode; onClick?: () => void; type?: "button" | "submit";
    variant?: "primary" | "ghost"; disabled?: boolean },
) {
  const base: CSSProperties = {
    padding: "8px 16px", borderRadius: 8, cursor: disabled ? "default" : "pointer",
    fontFamily: "var(--font-ui)", fontSize: 13.5, fontWeight: 600,
    opacity: disabled ? 0.5 : 1,
  };
  const variantStyle: CSSProperties = variant === "primary"
    ? { background: "var(--amber-grad)", color: "var(--amber-text)", border: "none" }
    : { background: "transparent", color: "var(--ink)", border: "1px solid var(--frame-rule)" };
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      data-variant={variant} style={{ ...base, ...variantStyle }}>{children}</button>
  );
}

export function Panel({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{
      background: "var(--parchment-panel)", borderRadius: 8, padding: 32, ...style,
    }}>{children}</div>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div style={{
      background: "var(--card)", borderRadius: 12, padding: 20,
      boxShadow: "0 3px 14px rgba(18,11,4,0.22), inset 0 1px 0 rgba(255,251,240,0.55)",
      ...style,
    }}>{children}</div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div style={{ textAlign: "center", padding: 48, color: "var(--ink-muted)" }}>
      <p style={{ fontFamily: "var(--font-serif)", fontSize: 18, margin: "0 0 6px" }}>{title}</p>
      {hint && <p style={{ margin: 0 }}>{hint}</p>}
    </div>
  );
}

export function StatusDot({ status, label }: { status: string; label?: string }) {
  const color = STATUS_COLORS[status] ?? "var(--ink-faint)";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6,
      fontFamily: "var(--font-mono)", fontSize: 11.5, color }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: color }} />
      {label ?? status}
    </span>
  );
}

export function MeterBar({ value, max }: { value: number; max: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const color = scoreColor((value / max) * 5);
  return (
    <div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color }}>
        {value}<span style={{ color: "var(--ink-faint)", fontSize: 11 }}>/{max}</span>
      </span>
      <div style={{ height: 4, borderRadius: 2, background: "rgba(43,33,23,0.12)",
        marginTop: 4, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
      </div>
    </div>
  );
}

function fmtScore(value: number): string | number {
  return Number.isInteger(value) ? value : value.toFixed(1);
}

export function SegmentScore({ value, max = 5 }: { value: number; max?: number }) {
  const rounded = Math.round(value);
  const color = scoreColor(rounded);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 600, color }}>{fmtScore(value)}</span>
      <span data-testid="segments" aria-hidden style={{ display: "inline-flex", gap: 2 }}>
        {Array.from({ length: max }, (_, i) => (
          <span key={i} style={{ width: 9, height: 5, borderRadius: 1,
            background: i < rounded ? color : "rgba(43,33,23,0.14)" }} />
        ))}
      </span>
    </span>
  );
}

export function SegmentedToggle(
  { options, value, onChange }:
  { options: { value: string; label: string }[]; value: string; onChange: (v: string) => void },
) {
  return (
    <span style={{ display: "inline-flex", gap: 0, background: "var(--parchment-panel)",
      border: "1px solid var(--frame-rule)", borderRadius: 8, padding: 3 }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button key={o.value} type="button" aria-pressed={active} onClick={() => onChange(o.value)}
            style={{ fontFamily: "var(--font-ui)", fontSize: 12.5, fontWeight: 600,
              border: "none", borderRadius: 6, padding: "6px 13px", cursor: "pointer",
              background: active ? "var(--amber-grad)" : "transparent",
              color: active ? "var(--amber-text)" : "var(--ink-muted)" }}>{o.label}</button>
        );
      })}
    </span>
  );
}

export function RelevanceBar({ value, max }: { value: number; max: number }) {
  const filled = max > 0 ? Math.round((value / max) * 5) : 0;
  const color = scoreColor(filled);
  const label = Number.isInteger(value) ? value : value.toFixed(2);
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 17, fontWeight: 600, color, lineHeight: 1 }}>
        {label}</span>
      <span aria-hidden style={{ display: "inline-flex", gap: 2 }}>
        {Array.from({ length: 5 }, (_, i) => (
          <span key={i} data-testid="rel-seg" data-filled={i < filled ? "true" : "false"}
            style={{ width: 5, height: 5, borderRadius: "50%",
              background: i < filled ? color : "rgba(43,33,23,0.18)" }} />
        ))}
      </span>
    </span>
  );
}

export function CodeBlock({ children }: { children: ReactNode }) {
  return (
    <pre style={{ background: "#272016", color: "#e6dabd", borderRadius: 8, padding: "14px 16px",
      fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.7, margin: 0,
      whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflowY: "auto" }}>
      {children}</pre>
  );
}
