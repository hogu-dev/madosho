import { useEffect, useState } from "react";
import { Modal } from "../design/Modal";
import { Button, Heading, SegmentedToggle } from "../design/primitives";
import { api } from "../api/client";
import type { Corpus } from "../api/types";

// A whole llmkb KB packs into ONE madosho document. The browser can't read a
// disk path, so it must send the KB's files: either a .zip, or the folder's
// files via the directory picker. For the folder route we send only what the
// packer needs - kb.yaml + the wiki pages - not .git or the search index.
const kbFile = (rel: string) =>
  rel === "kb.yaml" || rel.endsWith("/kb.yaml") ||
  (rel.includes("/wiki/") && rel.toLowerCase().endsWith(".md"));

const inputStyle = {
  fontSize: 13, fontFamily: "var(--font-ui)", padding: "7px 10px",
  border: "1px solid var(--frame-rule)", borderRadius: 7,
  background: "var(--parchment-panel)", color: "var(--ink)",
} as const;

export function ImportKbModal(
  { open, onClose, onImported }:
  { open: boolean; onClose: () => void; onImported: () => void },
) {
  const [mode, setMode] = useState("folder");
  const [folder, setFolder] = useState<{ file: File; path: string }[]>([]);
  const [zip, setZip] = useState<File | null>(null);
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [corpus, setCorpus] = useState("");            // "" = library only
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode("folder"); setFolder([]); setZip(null); setCorpus(""); setError(null); setBusy(false);
    api.listCorpora().then(setCorpora).catch(() => setCorpora([]));
  }, [open]);

  const pickFolder = (list: FileList | null) => {
    const kept = Array.from(list ?? [])
      .map((f) => ({ file: f, path: (f as any).webkitRelativePath || f.name }))
      .filter((x) => kbFile(x.path));
    setFolder(kept);
    setError(kept.some((x) => x.path.endsWith("kb.yaml")) ? null
      : "That folder has no kb.yaml - pick an llmkb KB directory.");
  };

  const ready = mode === "zip" ? zip !== null
    : folder.length > 0 && folder.some((x) => x.path.endsWith("kb.yaml"));

  async function submit() {
    setBusy(true); setError(null);
    try {
      const opts = mode === "zip"
        ? { archive: zip!, corpus: corpus || undefined }
        : { folder, corpus: corpus || undefined };
      await api.importKb(opts);
      onImported();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} labelledBy="import-kb-title">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <Heading level={2} style={{ margin: 0 }}>
            <span id="import-kb-title">Import a knowledge base</span></Heading>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "6px 0 0", lineHeight: 1.5 }}>
            Bring an existing llmkb KB in as one document - its pages become searchable
            corpus content. Choose the KB folder, or upload a .zip of it.</p>
        </div>
        <button aria-label="Close" onClick={onClose} style={{ background: "none", border: "none",
          fontSize: 18, color: "var(--ink-muted)", cursor: "pointer" }}>✕</button>
      </div>

      <div style={{ margin: "20px 0 14px" }}>
        <SegmentedToggle value={mode} onChange={setMode}
          options={[{ value: "folder", label: "KB folder" }, { value: "zip", label: "Zip file" }]} />
      </div>

      {mode === "folder" ? (
        <label style={{ display: "block", textAlign: "center",
          border: "1.5px dashed rgba(120,95,40,0.4)", borderRadius: 9, padding: 13,
          fontSize: 12.5, color: "var(--ink-muted)", cursor: "pointer" }}>
          <input data-testid="kb-folder-input" type="file" multiple
            {...({ webkitdirectory: "", directory: "" } as any)}
            onChange={(e) => pickFolder(e.target.files)} style={{ display: "none" }} />
          <span style={{ color: "var(--gilt)" }}>⧉</span>{" "}
          {folder.length > 0
            ? `${folder.length} KB file${folder.length === 1 ? "" : "s"} selected`
            : "Choose the KB folder"}
        </label>
      ) : (
        <label style={{ display: "block", textAlign: "center",
          border: "1.5px dashed rgba(120,95,40,0.4)", borderRadius: 9, padding: 13,
          fontSize: 12.5, color: "var(--ink-muted)", cursor: "pointer" }}>
          <input data-testid="kb-zip-input" type="file" accept=".zip,application/zip"
            onChange={(e) => setZip(e.target.files?.[0] ?? null)} style={{ display: "none" }} />
          <span style={{ color: "var(--gilt)" }}>⧉</span>{" "}
          {zip ? zip.name : "Choose a .zip of the KB"}
        </label>
      )}

      <div style={{ marginTop: 18 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
          textTransform: "uppercase", color: "var(--ink-faint)", display: "block", marginBottom: 6 }}>
          Add to corpus <span style={{ textTransform: "none", letterSpacing: 0 }}>(optional)</span></span>
        <select aria-label="Add to corpus" value={corpus}
          onChange={(e) => setCorpus(e.target.value)} style={{ ...inputStyle, minWidth: 220 }}>
          <option value="">— library only —</option>
          {corpora.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
        </select>
      </div>

      {error && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 12.5, marginTop: 14 }}>{error}</p>}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24,
        paddingTop: 18, borderTop: "1px solid rgba(156,121,32,0.25)" }}>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} disabled={busy || !ready}>
          {busy ? "Importing…" : "Import KB"}</Button>
      </div>
    </Modal>
  );
}
