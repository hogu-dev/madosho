import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Jobs } from "../Jobs";
import { api } from "../../api/client";

const JOBS = [
  { kind: "build", pipeline_id: 11, document_id: 5, document_filename: "f35.pdf",
    name: "f35_vision", status: "building",
    progress: { phase: "embedding", log: [{ t: 1, msg: "chunking page 3" }] },
    created_at: new Date().toISOString() },
  { kind: "ingest", pipeline_id: 9, document_id: 5, document_filename: "f35.pdf",
    name: "f35", status: "indexed", created_at: new Date().toISOString() },
  { kind: "build", pipeline_id: 7, document_id: 2, document_filename: "notes.pdf",
    name: "notes_pymupdf", status: "failed", error: "boom: vision endpoint unreachable",
    created_at: new Date().toISOString() },
];

beforeEach(() => { vi.restoreAllMocks(); });

function renderPage() {
  return render(<MemoryRouter><Jobs /></MemoryRouter>);
}

test("renders the heading immediately, before data loads", () => {
  vi.spyOn(api, "listJobs").mockResolvedValue([] as any);
  renderPage();
  expect(screen.getByRole("heading", { name: "Jobs" })).toBeInTheDocument();
});

test("shows the empty state when nothing is building", async () => {
  vi.spyOn(api, "listJobs").mockResolvedValue([] as any);
  renderPage();
  expect(await screen.findByText(/nothing building right now/i)).toBeInTheDocument();
});

test("lists jobs, links each to its document, and shows the build console while building", async () => {
  vi.spyOn(api, "listJobs").mockResolvedValue(JOBS as any);
  renderPage();
  expect(await screen.findByText("f35_vision")).toBeInTheDocument();
  // the building job links back to its document workbench
  const link = screen.getByText("f35_vision").closest("a");
  expect(link).toHaveAttribute("href", "/documents/5");
  // live console for the building job
  expect(screen.getByText(/chunking page 3/)).toBeInTheDocument();
  // failed job surfaces its error
  expect(screen.getByText(/vision endpoint unreachable/)).toBeInTheDocument();
});

test("running filter narrows to in-flight jobs", async () => {
  vi.spyOn(api, "listJobs").mockResolvedValue(JOBS as any);
  renderPage();
  await screen.findByText("f35_vision");
  fireEvent.click(screen.getByText("Running 1"));
  expect(screen.getByText("f35_vision")).toBeInTheDocument();
  expect(screen.queryByText("notes_pymupdf")).not.toBeInTheDocument();   // failed hidden
});
