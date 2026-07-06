import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Documents } from "../Documents";
import { api } from "../../api/client";

// Documents now calls useAuth() for canWrite gating; mock it so tests run without a real provider.
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

const DOCS = [
  { id: 1, filename: "saturnv_press_kit.pdf", status: "indexed",
    selected_pipeline_id: null, corpora: [{ id: 7, name: "aerospace" }], rating: 11 },
  { id: 2, filename: "orbital_mechanics_notes.pdf", status: "indexing",
    selected_pipeline_id: null, corpora: [], rating: null },
  { id: 3, filename: "corrupted_scan.pdf", status: "failed",
    selected_pipeline_id: null, corpora: [], rating: null },
];

beforeEach(() => { vi.restoreAllMocks(); });

function renderPage() {
  return render(<MemoryRouter><Documents /></MemoryRouter>);
}

test("renders the heading immediately even before data loads", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue([] as any);
  renderPage();
  expect(screen.getByRole("heading", { name: "Documents" })).toBeInTheDocument();
});

test("renders the empty state when the library is empty", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue([] as any);
  renderPage();
  expect(await screen.findByText(/library is empty/i)).toBeInTheDocument();
});

test("lists documents with status and links rows to the workbench", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue(DOCS as any);
  renderPage();
  expect(await screen.findByText("saturnv_press_kit.pdf")).toBeInTheDocument();
  expect(screen.getByText("aerospace")).toBeInTheDocument();
  expect(screen.getByText("11")).toBeInTheDocument();   // effective /15
  const link = screen.getByText("saturnv_press_kit.pdf").closest("a");
  expect(link).toHaveAttribute("href", "/documents/1");
});

test("filter chips show counts and filter the rows", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue(DOCS as any);
  renderPage();
  await screen.findByText("saturnv_press_kit.pdf");
  expect(screen.getByText("All 3")).toBeInTheDocument();
  fireEvent.click(screen.getByText(/Failed 1/));
  expect(screen.getByText("corrupted_scan.pdf")).toBeInTheDocument();
  expect(screen.queryByText("saturnv_press_kit.pdf")).not.toBeInTheDocument();
});

test("the Upload PDF button opens the modal", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockResolvedValue([] as any);
  vi.spyOn(api, "components").mockResolvedValue({ parser: [], chunker: [], embedder: [], reranker: [] } as any);
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: /Upload PDF/i }));
  expect(await screen.findByText("Upload & index")).toBeInTheDocument();
});

test("shows an error line when the load fails", async () => {
  vi.spyOn(api, "listLibraryDocuments").mockRejectedValue(new Error("boom"));
  renderPage();
  expect(await screen.findByText(/boom/i)).toBeInTheDocument();
});
