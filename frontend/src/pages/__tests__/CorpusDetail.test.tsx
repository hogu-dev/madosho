import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { CorpusDetail } from "../CorpusDetail";
import { api } from "../../api/client";

vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

const MEMBERS = [
  { document_id: 5, filename: "f35.pdf", status: "indexed",
    selected_pipeline_ids: [22], default_pipeline_id: 21,
    pipelines: [
      { id: 21, name: "docling", status: "indexed", rating: 12, is_default: true },
      { id: 22, name: "vision", status: "indexed", rating: 10, is_default: false },
    ] },
  { document_id: 8, filename: "saturnv.pdf", status: "indexed",
    selected_pipeline_ids: [], default_pipeline_id: 31,
    pipelines: [{ id: 31, name: "docling", status: "indexed", rating: 11, is_default: true }] },
];

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listCorpora").mockResolvedValue([{ id: 7, name: "aerospace", config: {} }] as any);
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue([] as any);
});

function renderAt(id = "7") {
  return render(
    <MemoryRouter initialEntries={[`/corpora/${id}`]}>
      <Routes><Route path="/corpora/:corpusId" element={<CorpusDetail />} /></Routes>
    </MemoryRouter>);
}

test("documents start collapsed, showing a selection summary", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  renderAt();
  expect(await screen.findByText("f35.pdf")).toBeInTheDocument();
  // collapsed by default: f35 (vision only) and saturnv (nothing -> default) show summaries,
  // and the pipeline checkboxes are not rendered yet.
  expect(screen.getByText("1 pipeline selected")).toBeInTheDocument();
  expect(screen.getByText(/Default — docling/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("Pipeline vision for f35.pdf")).toBeNull();
});

test("expanding a document reveals its pipeline checkboxes", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getByText("1 pipeline selected"));   // expand f35
  expect((screen.getByLabelText("Pipeline vision for f35.pdf") as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText("Pipeline docling for f35.pdf") as HTMLInputElement).checked).toBe(false);
});

test("checking a pipeline persists the new selection set", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const setSel = vi.spyOn(api, "setCorpusDocumentPipelines").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getByText("1 pipeline selected"));   // expand f35
  // add docling (21) to f35 (doc 5), which already has vision (22)
  fireEvent.click(screen.getByLabelText("Pipeline docling for f35.pdf"));
  await waitFor(() => expect(setSel).toHaveBeenCalledWith(7, 5, [22, 21]));
});

test("unchecking the last pipeline clears the selection (falls back to default)", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const setSel = vi.spyOn(api, "setCorpusDocumentPipelines").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getByText("1 pipeline selected"));   // expand f35
  fireEvent.click(screen.getByLabelText("Pipeline vision for f35.pdf"));   // f35's only selected pipeline
  await waitFor(() => expect(setSel).toHaveBeenCalledWith(7, 5, []));
});

test("a failed save flags the document and retry re-sends the selection", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const setSel = vi.spyOn(api, "setCorpusDocumentPipelines")
    .mockRejectedValueOnce(new Error("boom")).mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getByText("1 pipeline selected"));        // expand f35
  fireEvent.click(screen.getByLabelText("Pipeline docling for f35.pdf"));  // add docling -> [22,21]
  // failure is surfaced and the optimistic check stays visible (not silently lost)
  const retry = await screen.findByText(/Not saved — retry/i);
  expect((screen.getByLabelText("Pipeline docling for f35.pdf") as HTMLInputElement).checked).toBe(true);
  expect(setSel).toHaveBeenCalledWith(7, 5, [22, 21]);
  // retry re-sends the same set
  setSel.mockClear();
  fireEvent.click(retry);
  await waitFor(() => expect(setSel).toHaveBeenCalledWith(7, 5, [22, 21]));
});

test("the per-document checkbox selects all of that document's pipelines", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const setSel = vi.spyOn(api, "setCorpusDocumentPipelines").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  // f35 is partially selected (vision only) -> toggling the doc box selects all
  fireEvent.click(screen.getByLabelText(/Select all pipelines for f35.pdf/i));
  await waitFor(() => expect(setSel).toHaveBeenCalledWith(7, 5, [21, 22]));
});

test("the master Select all checks every pipeline of every document", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const setSel = vi.spyOn(api, "setCorpusDocumentPipelines").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getByLabelText("Select all pipelines"));
  await waitFor(() => {
    expect(setSel).toHaveBeenCalledWith(7, 5, [21, 22]);
    expect(setSel).toHaveBeenCalledWith(7, 8, [31]);
  });
});

test("adding a library document calls addMembership", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue(
    [{ id: 99, filename: "new.pdf", status: "indexed", selected_pipeline_id: null,
       corpora: [], rating: null }] as any);
  const add = vi.spyOn(api, "addMembership").mockResolvedValue({} as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.change(await screen.findByLabelText(/Add document/i), { target: { value: "99" } });
  await waitFor(() => expect(add).toHaveBeenCalledWith(7, 99));
});

test("removing a member calls removeMembership", async () => {
  vi.spyOn(api, "listCorpusMembers").mockResolvedValue(MEMBERS as any);
  const rm = vi.spyOn(api, "removeMembership").mockResolvedValue(undefined as any);
  renderAt();
  await screen.findByText("f35.pdf");
  fireEvent.click(screen.getAllByTitle(/Remove from corpus/i)[0]);
  await waitFor(() => expect(rm).toHaveBeenCalledWith(7, 5));
});
