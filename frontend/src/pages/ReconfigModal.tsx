import { useEffect, useState } from "react";
import { Modal } from "../design/Modal";
import { Button, Heading } from "../design/primitives";
import { api } from "../api/client";
import type { Components, LlmEndpoint, LibraryDocument } from "../api/types";
import { recipeIsValid } from "../lib/recipe";
import { RecipePicker, type RecipeState } from "./RecipePicker";

// Re-choose a document's default-pipeline recipe and rebuild in place. Seeds from
// the current recipe so you tweak rather than start over -- the fix for a failed
// build (e.g. swap contextual for docling-hybrid) without delete + re-upload.
export function ReconfigModal(
  { open, doc, onClose, onDone }:
  { open: boolean; doc: LibraryDocument | null; onClose: () => void; onDone: () => void },
) {
  const [components, setComponents] = useState<Components | null>(null);
  const [endpoints, setEndpoints] = useState<LlmEndpoint[]>([]);
  const [recipe, setRecipe] = useState<RecipeState>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !doc) return;
    setError(null); setBusy(false); setRecipe({});
    api.components().then(setComponents).catch(() => setComponents({}));
    api.listLlmEndpoints().then(setEndpoints).catch(() => setEndpoints([]));
    // Seed from the document's current default pipeline so the form opens on what
    // it's set to now (slots are {extract, chunk, index}).
    api.getDocumentPipelines(doc.id).then((ps) => {
      const def = ps.find((p) => p.is_default) ?? ps[0];
      if (def) setRecipe({ parser: def.slots.extract ?? undefined,
        chunker: def.slots.chunk ?? undefined, embedder: def.slots.index ?? undefined });
    }).catch(() => { /* leave empty; the pickers fall back to first option */ });
  }, [open, doc]);

  if (!doc) return null;
  const recipeOk = recipeIsValid(recipe, components, endpoints.length,
    endpoints.filter((e) => e.supports_vision).length);

  async function submit() {
    if (!doc) return;
    setBusy(true); setError(null);
    try {
      await api.reconfigureDocument(doc.id, recipe);
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reconfigure failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} labelledBy="reconfig-title">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <Heading level={2} style={{ margin: 0 }}>
            <span id="reconfig-title">Reconfigure pipeline</span></Heading>
          <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: "6px 0 0", lineHeight: 1.5,
            maxWidth: 460 }}>
            Re-choose how <strong>{doc.filename}</strong> is indexed, then rebuild its default
            pipeline. The same collection is reused.</p>
        </div>
        <button aria-label="Close" onClick={onClose} style={{ background: "none", border: "none",
          fontSize: 18, color: "var(--ink-muted)", cursor: "pointer" }}>✕</button>
      </div>

      <div style={{ margin: "20px 0 12px" }}>
        <RecipePicker components={components} endpoints={endpoints}
          recipe={recipe} setRecipe={setRecipe} />
      </div>

      {error && <p style={{ color: "var(--oxblood)", fontSize: 12.5, marginTop: 8 }}>{error}</p>}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20,
        paddingTop: 18, borderTop: "1px solid rgba(156,121,32,0.25)" }}>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={submit} disabled={busy || !recipeOk}>
          {busy ? "Rebuilding…" : "Rebuild with this recipe"}
        </Button>
      </div>
    </Modal>
  );
}
