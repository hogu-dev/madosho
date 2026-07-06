import { useEffect, useState } from "react";
import { Modal } from "../design/Modal";
import { Button, Heading } from "../design/primitives";
import { api } from "../api/client";
import type { Components, LlmEndpoint } from "../api/types";
import { recipeErrors, defaultRecipe } from "../lib/recipe";
import { RecipePicker, type RecipeState } from "./RecipePicker";

// Text-extraction lane (docling): PDF plus office, web, markup, csv, email,
// epub, latex. Mirrors the backend's supported_suffixes() -- keep the two in sync.
const DOC_EXT =
  /\.(pdf|docx|docm|dotx|dotm|pptx|pptm|potx|potm|ppsx|ppsm|xlsx|xlsm|html|htm|xhtml|md|rmd|qmd|text|txt|csv|adoc|asc|asciidoc|eml|epub|tex|latex)$/i;
const isDocument = (f: File) => DOC_EXT.test(f.name);
// Images are ingestable too, but ONLY through the vision extractor (the text
// parsers read embedded text, which an image has none of).
const IMAGE_EXT = /\.(png|jpe?g|webp|gif|tiff?|bmp)$/i;
const isImage = (f: File) => f.type.startsWith("image/") || IMAGE_EXT.test(f.name);
const isSupported = (f: File) => isDocument(f) || isImage(f);

export function UploadModal(
  { open, onClose, onUploaded }:
  { open: boolean; onClose: () => void; onUploaded: () => void },
) {
  const [files, setFiles] = useState<File[]>([]);
  const [components, setComponents] = useState<Components | null>(null);
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const [recipe, setRecipe] = useState<RecipeState>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFiles([]); setError(null); setBusy(false);
    api.components().then((c) => {
      setComponents(c);
      setRecipe(defaultRecipe(c));            // canonical docling + docling-hybrid stack
    }).catch(() => setComponents({}));
    api.listLlmEndpoints().then(setEndpoints).catch(() => setEndpoints([]));
  }, [open]);

  const valid = files.filter(isSupported);
  const slotErrors = recipeErrors(recipe, components, endpoints.length,
    endpoints.filter((e) => e.supports_vision).length);   // re-validated every render
  // The upload recipe carries no per-option form, so the docling lane's OCR
  // (ocr: true) can't be enabled here -- with default options only the vision
  // extractor reads an image. OCR pipelines can be added later on the Workbench.
  const needsVision = valid.some(isImage) && recipe.parser !== "vision";
  const recipeOk = Object.keys(slotErrors).length === 0 && !needsVision;
  const addFiles = (list: FileList | null) => {
    if (list) setFiles((prev) => [...prev, ...Array.from(list)]);
  };
  const removeFile = (i: number) => setFiles((prev) => prev.filter((_, idx) => idx !== i));

  async function submit() {
    setBusy(true); setError(null);
    try {
      for (const f of valid) await api.createDocument(f, recipe);
      onUploaded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} labelledBy="upload-title">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <Heading level={2} style={{ margin: 0 }}><span id="upload-title">Upload &amp; index</span></Heading>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "6px 0 0", lineHeight: 1.5 }}>
            Choose your PDFs or images and how they get indexed — in one step. The recipe you
            pick is the first pipeline that gets built.</p>
        </div>
        <button aria-label="Close" onClick={onClose} style={{ background: "none", border: "none",
          fontSize: 18, color: "var(--ink-muted)", cursor: "pointer" }}>✕</button>
      </div>

      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
        textTransform: "uppercase", color: "var(--ink-faint)", margin: "22px 0 9px" }}>
        Files · {files.length} selected</div>

      {files.map((f, i) => {
        const ok = isSupported(f);
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 14px",
            marginBottom: 8, borderRadius: 9,
            background: ok ? "var(--card)" : "rgba(164,68,46,0.08)",
            border: ok ? "1px solid var(--frame-rule)" : "1px solid rgba(164,68,46,0.45)" }}>
            <span aria-hidden>📄</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</div>
              {!ok && <div style={{ fontSize: 11, color: "var(--oxblood)" }}>
                Unsupported format — madosho indexes PDFs and images</div>}
            </div>
            {ok && <span style={{ fontFamily: "var(--font-mono)", fontSize: 11,
              color: "#4a7a3c" }}>ready</span>}
            <button aria-label={`Remove ${f.name}`} onClick={() => removeFile(i)}
              style={{ background: "none", border: "none", cursor: "pointer",
                color: "var(--ink-faint)" }}>✕</button>
          </div>
        );
      })}

      <label style={{ display: "block", textAlign: "center", border: "1.5px dashed rgba(120,95,40,0.4)",
        borderRadius: 9, padding: 13, fontSize: 12.5, color: "var(--ink-muted)", cursor: "pointer" }}>
        <input data-testid="upload-input" type="file"
          accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.txt,.csv,.adoc,.eml,.epub,.tex,image/*" multiple
          onChange={(e) => addFiles(e.target.files)} style={{ display: "none" }} />
        <span style={{ color: "var(--gilt)" }}>+</span> Add PDFs or images, or click to choose
      </label>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
        margin: "22px 0 4px" }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
          textTransform: "uppercase", color: "var(--ink-faint)" }}>Indexing recipe</div>
        <div style={{ fontSize: 11.5, color: "var(--ink-faint)" }}>
          One recipe, applied to all {valid.length} file{valid.length === 1 ? "" : "s"}</div>
      </div>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "0 0 12px", lineHeight: 1.5 }}>
        Rename or add more pipelines per document later, on the Workbench.</p>
      <RecipePicker components={components} endpoints={endpoints} recipe={recipe} setRecipe={setRecipe} />

      {needsVision && <p role="alert" style={{ color: "var(--oxblood)", fontSize: 12, marginTop: 10 }}>
        You selected an image — pick the Vision extractor to index it (an OCR
        pipeline can be added on the Workbench afterwards).</p>}

      {error && <p style={{ color: "var(--oxblood)", fontSize: 12.5, marginTop: 14 }}>{error}</p>}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24,
        paddingTop: 18, borderTop: "1px solid rgba(156,121,32,0.25)" }}>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} disabled={busy || valid.length === 0 || !recipeOk}>
          {busy ? "Uploading…" : `Upload & index ${valid.length} file${valid.length === 1 ? "" : "s"}`}
        </Button>
      </div>
    </Modal>
  );
}
