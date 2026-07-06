// frontend/src/pages/__tests__/Compare.test.tsx
// The standalone Compare page: pick a document, then line up its pipelines through
// the shared <Comparator>. Exercises the doc selector, the ?document deep-link, and
// the N-way (3+ column) extract comparison.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Compare } from "../Compare";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: {
  listLibraryDocuments: vi.fn(), getDocumentPipelines: vi.fn(),
  getRecommendedPipeline: vi.fn(), components: vi.fn(),
  getExtractDivergence: vi.fn(), getPipelineArtifacts: vi.fn(), query: vi.fn(),
  fileUrl: (id: number) => `/documents/${id}/file`,
} }));

const DOCS = [
  { id: 5, filename: "f-16.pdf", status: "indexed", selected_pipeline_id: null, corpora: [], rating: 9 },
  { id: 6, filename: "still-indexing.pdf", status: "indexing", selected_pipeline_id: null, corpora: [], rating: null },
];
const PIPES = [
  { id: 11, name: "docling", slots: {}, steps: {}, rating: 8, status: "indexed", is_default: true, effective: true },
  { id: 12, name: "ctx", slots: {}, steps: {}, rating: 8, status: "indexed", is_default: false, effective: false },
  { id: 13, name: "fast", slots: {}, steps: {}, rating: 8, status: "indexed", is_default: false, effective: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  (api.listLibraryDocuments as any).mockResolvedValue(DOCS);
  (api.getDocumentPipelines as any).mockResolvedValue(PIPES);
  (api.getRecommendedPipeline as any).mockResolvedValue(null);
  (api.components as any).mockResolvedValue({ parser: [], chunker: [], embedder: [] });
  (api.getExtractDivergence as any).mockResolvedValue({ document_id: 5, pipelines: [], pages: [] });
  (api.getPipelineArtifacts as any).mockResolvedValue({ document_id: 5, chunks: [], tables: [] });
  (api.query as any).mockResolvedValue({ hits: [] });
});

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes><Route path="/compare" element={<Compare />} /></Routes>
    </MemoryRouter>);
}

test("prompts to pick a document and only lists indexed ones", async () => {
  renderAt("/compare");
  expect(await screen.findByText(/pick a document/i)).toBeInTheDocument();
  const select = screen.getByLabelText("document") as HTMLSelectElement;
  // the still-indexing document is filtered out of the selector
  expect(within(select).queryByText("still-indexing.pdf")).not.toBeInTheDocument();
  expect(within(select).getByText("f-16.pdf")).toBeInTheDocument();
});

test("a ?document deep-link loads that document's pipelines straight away", async () => {
  renderAt("/compare?document=5");
  await waitFor(() => expect(api.getDocumentPipelines).toHaveBeenCalledWith(5));
  // the folded-in scoreboard renders (the in-doc compare page's body now lives here)
  expect(await screen.findByText("Total")).toBeInTheDocument();
  // the comparator's default two pipeline columns show up (labelled A / B)
  expect(await screen.findByLabelText("pipeline A")).toBeInTheDocument();
  expect(screen.getByLabelText("pipeline B")).toBeInTheDocument();
});

test("compares three pipelines at once on the extract stage", async () => {
  (api.getExtractDivergence as any).mockResolvedValue({
    document_id: 5,
    pipelines: [{ id: 11, name: "docling" }, { id: 12, name: "ctx" }, { id: 13, name: "fast" }],
    pages: [{ page: 1, change: 4, columns: [
      { pipeline_id: 11, name: "docling", text: "the quick brown fox", spans: [[4, 9]] },
      { pipeline_id: 12, name: "ctx", text: "the quick brown fox", spans: [[4, 9]] },
      { pipeline_id: 13, name: "fast", text: "the slow brown fox", spans: [[4, 8]] },
    ] }] });
  renderAt("/compare?document=5");
  await screen.findByLabelText("pipeline A");
  // add a third column, then compare -> all three ids go to the N-way endpoint
  await userEvent.click(screen.getByRole("button", { name: /\+ column/i }));
  await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));
  await waitFor(() => expect(api.getExtractDivergence).toHaveBeenCalledWith(5, [11, 12, 13]));
  expect(await screen.findByText(/slow/)).toBeInTheDocument();
});

test("picking a document from the selector deep-links it into the URL", async () => {
  renderAt("/compare");
  await screen.findByText(/pick a document/i);
  await userEvent.selectOptions(screen.getByLabelText("document"), "5");
  await waitFor(() => expect(api.getDocumentPipelines).toHaveBeenCalledWith(5));
});
