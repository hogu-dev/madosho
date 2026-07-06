import "./tokens.css";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),' +
  'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function Modal(
  { open, onClose, labelledBy, children }:
  { open: boolean; onClose: () => void; labelledBy?: string; children: ReactNode },
) {
  const panel = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    const node = panel.current;
    const focusables = () =>
      node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
    focusables()[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (f.length === 0) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      restoreTo.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div data-testid="modal-backdrop" onClick={onClose} style={{
      position: "fixed", inset: 0, zIndex: 50, background: "rgba(20,12,4,0.55)",
      backdropFilter: "blur(2px)", WebkitBackdropFilter: "blur(2px)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={labelledBy}
        onClick={(e) => e.stopPropagation()} style={{
          width: "100%", maxWidth: 660, maxHeight: "88vh", overflowY: "auto",
          background: "var(--parchment-panel)", borderRadius: 8, padding: "28px 30px",
          border: "1px solid var(--frame-rule)",
          boxShadow: "0 24px 60px rgba(10,6,2,0.6), inset 0 0 0 4px #e6dabd, " +
            "inset 0 0 0 5px rgba(156,121,32,0.45)" }}>
        {children}
      </div>
    </div>
  );
}
