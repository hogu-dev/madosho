// frontend/src/features/compare/__tests__/DocumentComparison.test.tsx
// The per-document comparison body: a read-only scoreboard, the recommended-test
// and not-yet-built nudges, and the shared <Comparator> for every stage. It takes
// docId as a prop (the Compare page supplies it from the picker / ?document link),
// so these tests render it directly at a fixed document.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { DocumentComparison } from "../DocumentComparison";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({ api: {
  getDocumentPipelines: vi.fn(), getRecommendedPipeline: vi.fn(), components: vi.fn(),
  getExtractDivergence: vi.fn(), getPipelineArtifacts: vi.fn(), query: vi.fn(),
  fileUrl: (id: number) => `/documents/${id}/file`,
} }));

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRecommendedPipeline as any).mockResolvedValue(null);
  (api.components as any).mockResolvedValue({ parser: [], chunker: [], embedder: [] });
  // Benign defaults so every stacked stage body can mount without exploding; each
  // test overrides the stage it actually exercises.
  (api.getExtractDivergence as any).mockResolvedValue({ document_id: 5, pipelines: [], pages: [] });
  (api.getPipelineArtifacts as any).mockResolvedValue({ document_id: 5, chunks: [], tables: [] });
  (api.query as any).mockResolvedValue({ hits: [] });
});

const PIPES = [
  { id: 11, name: "a_docling", slots: { extract: "docling", chunk: "hybrid", index: "granite" },
    steps: { extract: 4.0, chunk: 2.0, index: 2.0 }, rating: 8.0, status: "indexed",
    is_default: true, effective: true },
  { id: 12, name: "a_fast", slots: { extract: "pypdfium2", chunk: "late", index: "nomic" },
    steps: { extract: 3.0, chunk: 3.5, index: 2.5 }, rating: 9.0, status: "indexed",
    is_default: false, effective: false },
];

function renderAt(id: number) {
  return render(
    <MemoryRouter><DocumentComparison docId={id} /></MemoryRouter>);
}

test("collapses to a single empty state when there are no pipelines", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue([]);
  renderAt(5);
  expect(await screen.findByText(/nothing to compare yet/i)).toBeInTheDocument();
});

test("lays pipelines out step-by-step with per-step ratings and the effective column", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  renderAt(5);
  expect(await screen.findByText("Total")).toBeInTheDocument();
  // the three step rows
  expect(screen.getByText("Index")).toBeInTheDocument();
  // tools and the effective badge
  expect(screen.getByText("pypdfium2")).toBeInTheDocument();
  expect(screen.getByText(/effective/i)).toBeInTheDocument();
  // one winner cell per step row (docling wins extract; a_fast wins chunk + index)
  expect(screen.getAllByTitle(/highest-rated for this step/i)).toHaveLength(3);
});

test("surfaces a recommended test when the server suggests an unbuilt combo", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  (api.getRecommendedPipeline as any).mockResolvedValue({
    slots: { extract: "docling", chunk: "late", index: "nomic" },
    steps: { extract: 4, chunk: 3.5, index: 2.5 }, projected_rating: 10,
    already_built: false, matches: null });
  renderAt(5);
  expect(await screen.findByText(/recommended test/i)).toBeInTheDocument();
  expect(screen.getByText(/projected 10/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /build/i })).not.toBeInTheDocument();
});

test("surfaces registry tools no pipeline has built as a 'not yet built' nudge", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  // registry offers a parser (gemma-vision) that no pipeline on this doc uses
  (api.components as any).mockResolvedValue({
    parser: [{ name: "docling" }, { name: "pypdfium2" }, { name: "gemma-vision" }],
    chunker: [{ name: "hybrid" }, { name: "late" }], embedder: [{ name: "granite" }, { name: "nomic" }] });
  renderAt(5);
  expect(await screen.findByText(/not yet built/i)).toBeInTheDocument();
  expect(screen.getByText("gemma-vision")).toBeInTheDocument();
});

test("Extract stage flags divergence across the picked pipelines, from stored artifacts", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  (api.getExtractDivergence as any).mockResolvedValue({
    document_id: 5, pipelines: [{ id: 11, name: "a_docling" }, { id: 12, name: "a_fast" }],
    pages: [{ page: 1, change: 9, columns: [
      { pipeline_id: 11, name: "a_docling", text: "the quick fox", spans: [[4, 9]] },
      { pipeline_id: 12, name: "a_fast", text: "the slow fox", spans: [[4, 8]] },
    ] }] });
  renderAt(5);
  await screen.findByText("Total");
  // body is opt-in: nothing fetched until the reviewer presses Compare
  expect(api.getExtractDivergence).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));
  // default pickers select the first two indexed pipelines
  await waitFor(() => expect(api.getExtractDivergence).toHaveBeenCalledWith(5, [11, 12]));
  expect(await screen.findByText(/quick/)).toBeInTheDocument();
  expect(screen.getByText(/slow/)).toBeInTheDocument();
  // the original PDF page stays pinned beside every extraction as the source of truth
  expect(screen.getByTitle("original")).toBeInTheDocument();
});

test("Chunk stage lists each pipeline's stored chunks with counts", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  (api.getPipelineArtifacts as any).mockImplementation((pid: number) => Promise.resolve({
    document_id: 5, tables: [],
    chunks: pid === 11
      ? [{ id: "c1", text: "docling chunk one", position: 0, page: 1 }]
      : [{ id: "c2", text: "fast chunk A", position: 0, page: 1 },
         { id: "c3", text: "fast chunk B", position: 1, page: 1 }] }));
  renderAt(5);
  await screen.findByText("Total");
  await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));
  await waitFor(() => expect(api.getPipelineArtifacts).toHaveBeenCalledWith(11));
  expect(await screen.findByText(/docling chunk one/)).toBeInTheDocument();
  expect(screen.getByText(/fast chunk A/)).toBeInTheDocument();
  // the second column reports 2 chunks
  expect(screen.getByText(/2 chunks/)).toBeInTheDocument();
});

test("Retrieve stage runs a query per pipeline and shows ranked-hit lists", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  (api.query as any).mockImplementation((p: any) => Promise.resolve({
    hits: p.pipelines[0] === "a_docling"
      ? [{ text: "docling hit", score: 0.9, page: 1, citation: "", source: null }]
      : [{ text: "fast hit", score: 0.7, page: 2, citation: "", source: null }] }));
  renderAt(5);
  await screen.findByText("Total");
  await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));
  await userEvent.type(screen.getByLabelText("query"), "what is the notice period?");
  await userEvent.click(screen.getByRole("button", { name: /run query/i }));
  await waitFor(() => expect(api.query).toHaveBeenCalledWith(
    { document_id: 5, prompt: "what is the notice period?", pipelines: ["a_docling"] }));
  expect(await screen.findByText(/docling hit/)).toBeInTheDocument();
  expect(screen.getByText(/fast hit/)).toBeInTheDocument();
});

test("compare section asks for a second pipeline when only one is indexed", async () => {
  (api.getDocumentPipelines as any).mockResolvedValue([PIPES[0]]);
  renderAt(5);
  expect(await screen.findByText(/need two built pipelines/i)).toBeInTheDocument();
  // no extract fetch when there is nothing to compare against
  expect(api.getExtractDivergence).not.toHaveBeenCalled();
});
