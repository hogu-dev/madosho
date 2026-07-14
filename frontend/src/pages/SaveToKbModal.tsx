import { useEffect, useState } from "react";
import { Modal } from "../design/Modal";
import { Button, Heading, SegmentedToggle } from "../design/primitives";
import { api } from "../api/client";
import type { Kb } from "../api/types";

const inputStyle = {
  fontSize: 13, fontFamily: "var(--font-ui)", padding: "7px 10px",
  border: "1px solid var(--frame-rule)", borderRadius: 7,
  background: "var(--parchment-panel)", color: "var(--ink)",
} as const;

const label = {
  fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
  textTransform: "uppercase" as const, color: "var(--ink-faint)",
  display: "block", marginBottom: 6,
} as const;

// Turn a finished Research report or Alchemy draft into a single KB page. The
// caller supplies the report `body`, the destination `corpusId`, and a default
// title; the user picks a new-or-existing KB and confirms. This IS the approval
// step - nothing is written until "Save".
export function SaveToKbModal(
  { open, onClose, corpusId, defaultTitle, body }:
  { open: boolean; onClose: () => void; corpusId: number;
    defaultTitle: string; body: string },
) {
  const [mode, setMode] = useState("new");         // "new" | "existing"
  const [kbs, setKbs] = useState<Kb[]>([]);
  const [kbName, setKbName] = useState("");
  const [kbId, setKbId] = useState<number | "">("");
  const [title, setTitle] = useState(defaultTitle);
  const [type, setType] = useState("concept");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode("new"); setKbName(defaultTitle); setKbId(""); setTitle(defaultTitle);
    setType("concept"); setBusy(false); setError(null); setDone(null);
    api.listKbs()
      .then((all) => setKbs(all.filter((k) => k.corpus_id === corpusId)))
      .catch(() => setKbs([]));
  }, [open, corpusId, defaultTitle]);

  const ready = title.trim() !== "" &&
    (mode === "new" ? kbName.trim() !== "" : kbId !== "");

  async function submit() {
    setBusy(true); setError(null);
    try {
      const target = mode === "new"
        ? { kb_name: kbName.trim() }
        : { kb_id: Number(kbId) };
      const r = await api.saveKbPage(corpusId, {
        ...target, type, title: title.trim(), body,
      });
      setDone(`${r.action === "updated" ? "Updated" : "Saved"} page “${r.slug}” `
        + `in ${r.kb_name}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} labelledBy="save-kb-title">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <Heading level={2} style={{ margin: 0 }}>
            <span id="save-kb-title">Save to a knowledge base</span></Heading>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "6px 0 0", lineHeight: 1.5 }}>
            Write this report into a KB as one page - start a new KB or add it to
            an existing one in this corpus.</p>
        </div>
        <button aria-label="Close" onClick={onClose} style={{ background: "none", border: "none",
          fontSize: 18, color: "var(--ink-muted)", cursor: "pointer" }}>✕</button>
      </div>

      {done ? (
        <>
          <p role="status" style={{ fontSize: 13.5, color: "var(--ink)", margin: "22px 0 0",
            lineHeight: 1.55 }}>{done}</p>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 24,
            paddingTop: 18, borderTop: "1px solid rgba(156,121,32,0.25)" }}>
            <Button onClick={onClose}>Done</Button>
          </div>
        </>
      ) : (
        <>
          <div style={{ margin: "20px 0 14px" }}>
            <SegmentedToggle value={mode} onChange={setMode}
              options={[{ value: "new", label: "New KB" },
                        { value: "existing", label: "Existing KB" }]} />
          </div>

          {mode === "new" ? (
            <div>
              <span style={label}>KB name</span>
              <input aria-label="KB name" value={kbName}
                onChange={(e) => setKbName(e.target.value)}
                style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
            </div>
          ) : (
            <div>
              <span style={label}>Knowledge base</span>
              {kbs.length === 0 ? (
                <p style={{ fontSize: 12.5, color: "var(--ink-muted)", margin: 0 }}>
                  No knowledge bases in this corpus yet - use “New KB”.</p>
              ) : (
                <select aria-label="Knowledge base" value={kbId}
                  onChange={(e) => setKbId(e.target.value === "" ? "" : Number(e.target.value))}
                  style={{ ...inputStyle, minWidth: 240 }}>
                  <option value="">- choose a KB -</option>
                  {kbs.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
                </select>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 14, marginTop: 18, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <span style={label}>Page title</span>
              <input aria-label="Page title" value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
            </div>
            <div>
              <span style={label}>Page type</span>
              <select aria-label="Page type" value={type}
                onChange={(e) => setType(e.target.value)} style={{ ...inputStyle }}>
                <option value="concept">concept</option>
                <option value="summary">summary</option>
                <option value="entity">entity</option>
              </select>
            </div>
          </div>

          {error && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 12.5, marginTop: 14 }}>{error}</p>}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24,
            paddingTop: 18, borderTop: "1px solid rgba(156,121,32,0.25)" }}>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={submit} disabled={busy || !ready}>
              {busy ? "Saving…" : "Save to KB"}</Button>
          </div>
        </>
      )}
    </Modal>
  );
}
