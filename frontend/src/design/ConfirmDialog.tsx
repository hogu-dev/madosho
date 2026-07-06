import "./tokens.css";
import type { ReactNode } from "react";
import { Modal } from "./Modal";
import { Heading } from "./primitives";

// A small confirm/deny dialog on top of Modal: title, an explanatory body, and a
// Cancel/Confirm pair. `danger` paints the confirm button oxblood for destructive
// actions (deletes). `busy` disables both buttons and relabels confirm while the
// action runs, so a slow delete can't be double-fired.
export function ConfirmDialog(
  { open, title, confirmLabel = "Confirm", danger, busy, onConfirm, onClose, children }:
  { open: boolean; title: string; confirmLabel?: string; danger?: boolean; busy?: boolean;
    onConfirm: () => void; onClose: () => void; children?: ReactNode },
) {
  const confirmStyle = {
    padding: "8px 16px", borderRadius: 8, fontFamily: "var(--font-ui)", fontSize: 13.5,
    fontWeight: 600, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
    border: "none", color: "#fff",
    background: danger ? "var(--oxblood)" : "var(--amber-grad)",
  } as const;
  const cancelStyle = {
    padding: "8px 16px", borderRadius: 8, fontFamily: "var(--font-ui)", fontSize: 13.5,
    fontWeight: 600, cursor: busy ? "default" : "pointer", background: "transparent",
    color: "var(--ink)", border: "1px solid var(--frame-rule)",
  } as const;
  return (
    <Modal open={open} onClose={onClose} labelledBy="confirm-title">
      <Heading level={2} style={{ margin: 0 }}><span id="confirm-title">{title}</span></Heading>
      {children && (
        <div style={{ fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.55,
          margin: "12px 0 0" }}>{children}</div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
        <button type="button" style={cancelStyle} disabled={busy} onClick={onClose}>Cancel</button>
        <button type="button" style={confirmStyle} disabled={busy} onClick={onConfirm}>
          {busy ? "Working…" : confirmLabel}</button>
      </div>
    </Modal>
  );
}
