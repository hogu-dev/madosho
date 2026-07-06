// frontend/src/pages/Compare.tsx
// The single "Compare" surface under Measure & use: pick any document, then see how
// its pipelines rate step by step and line up what each produced at every stage --
// no need to open the document first. The document may be preselected with a
// ?document=<id> deep-link (the Workbench "Compare steps" link uses this). The body
// itself is the shared <DocumentComparison> (scoreboard + recommended test + the
// stacked comparator), so there is exactly one comparison codebase.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Panel, Heading, EmptyState } from "../design/primitives";
import { api } from "../api/client";
import type { LibraryDocument } from "../api/types";
import { DocumentComparison } from "../features/compare";
import { micro, picker } from "../features/compare/styles";

export function Compare() {
  const [params, setParams] = useSearchParams();
  const [docs, setDocs] = useState<LibraryDocument[]>([]);

  const docParam = params.get("document");
  const docId = docParam ? Number(docParam) : null;

  // Only indexed documents can be compared (a still-indexing doc has no pipelines
  // with artifacts to line up).
  useEffect(() => {
    api.listLibraryDocuments()
      .then((d) => setDocs(d.filter((x) => x.status === "indexed")))
      .catch(() => setDocs([]));
  }, []);

  const selectDoc = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id == null) next.delete("document"); else next.set("document", String(id));
    setParams(next, { replace: true });
  };

  return (
    <Panel>
      <Heading level={2} style={{ margin: 0 }}>Compare</Heading>
      <p style={{ fontSize: 12.5, color: "var(--ink-muted)", margin: "8px 0 20px", maxWidth: 640,
        lineHeight: 1.55 }}>
        Line up any number of a document's pipelines: see how each step rates across them (the
        highest-rated tool per step is marked — a hint at a combo worth testing, not a verdict) and
        compare what each actually produced at every stage — extract, chunk, and retrieval. No need to
        open the document first.</p>

      <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 22 }}>
        <span style={micro}>Document</span>
        <select aria-label="document" style={{ ...picker, minWidth: 260 }} value={docId ?? ""}
          onChange={(e) => selectDoc(e.target.value ? Number(e.target.value) : null)}>
          <option value="">Select a document…</option>
          {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
        </select>
      </label>

      {docId == null ? (
        <EmptyState title="Pick a document"
          hint="Choose a document above to line up and compare its pipelines." />
      ) : (
        <DocumentComparison key={docId} docId={docId} />
      )}
    </Panel>
  );
}
