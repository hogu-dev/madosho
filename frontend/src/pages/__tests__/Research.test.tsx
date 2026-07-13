import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Research } from "../Research";
import { ResearchRun, basename } from "../ResearchRun";
import { api } from "../../api/client";

const CORPORA = [{ id: 1, name: "aerospace", config: {} }, { id: 2, name: "law", config: {} }];
const ENDPOINTS = [
  { id: 1, name: "gemma4-local", provider: "openai", model: "gemma-4-e4b",
    api_base: "http://h:8081/v1", key_env_var: null, is_default: true, key_present: false },
  { id: 2, name: "qwen3-local", provider: "openai", model: "qwen3-14b",
    api_base: "http://h:8081/v1", key_env_var: null, is_default: false, key_present: false },
];
const DOCS = [
  { id: 9, filename: "saturnv_press_kit.pdf" },
  { id: 10, filename: "apollo_guidance.pdf" },
];
const RUNS = [
  { id: 5, corpus_id: 1, status: "running", progress: { phase: "searching" }, prompt: "How many engines?",
    config: { source: "rag", document_ids: [], budget_chars: 100000, max_rounds: 8, llm: {} } },
];

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listCorpora").mockResolvedValue(CORPORA as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue(ENDPOINTS as any);
  vi.spyOn(api, "listDocuments").mockResolvedValue(DOCS as any);
  vi.spyOn(api, "listResearch").mockResolvedValue(RUNS as any);
});

function renderList() {
  return render(<MemoryRouter initialEntries={["/research"]}><Research /></MemoryRouter>);
}

test("renders the launch form with corpus + model options after load", async () => {
  renderList();
  expect(await screen.findByRole("option", { name: "aerospace" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "gemma4-local" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Launch/ })).toBeInTheDocument();
});

test("Launch is disabled until a question is typed", async () => {
  renderList();
  await screen.findByRole("option", { name: "aerospace" });
  expect(screen.getByRole("button", { name: /Launch/ })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "engines?" } });
  expect(screen.getByRole("button", { name: /Launch/ })).toBeEnabled();
});

test("the document multi-select only appears in whole-text mode", async () => {
  renderList();
  await screen.findByRole("option", { name: "aerospace" });
  expect(screen.queryByLabelText("Documents")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Whole extracted text" }));
  expect(await screen.findByLabelText("Documents")).toBeInTheDocument();
});

test("launching sends the chosen endpoint's provider/model and the typed prompt", async () => {
  const launch = vi.spyOn(api, "launchResearch")
    .mockResolvedValue({ id: 7, corpus_id: 1 } as any);
  renderList();
  await screen.findByRole("option", { name: "aerospace" });
  fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "thrust?" } });
  fireEvent.click(screen.getByRole("button", { name: /Launch/ }));
  await waitFor(() => expect(launch).toHaveBeenCalled());
  const [cid, body] = launch.mock.calls[0];
  expect(cid).toBe(1);
  expect(body).toMatchObject({
    prompt: "thrust?", source: "rag", document_ids: [], max_rounds: 8,
    llm: { provider: "openai", model: "gemma-4-e4b" },
  });
  expect(body.reasoning_effort).toBeUndefined();
});

test("sends reasoning_effort when a preset is picked", async () => {
  const launch = vi.spyOn(api, "launchResearch")
    .mockResolvedValue({ id: 8, corpus_id: 1 } as any);
  renderList();
  await screen.findByRole("option", { name: "gemma4-local" });
  await screen.findByLabelText(/reasoning effort/i);
  fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "thrust?" } });
  fireEvent.change(screen.getByLabelText(/reasoning effort/i), { target: { value: "medium" } });
  fireEvent.click(screen.getByRole("button", { name: /Launch/ }));
  await waitFor(() => expect(launch).toHaveBeenCalled());
  const [, body] = launch.mock.calls.at(-1)!;
  expect((body as any).reasoning_effort).toBe("medium");
});

test("run history links carry the corpus id for the detail fetch", async () => {
  renderList();
  // The run also appears in the Active Runs section (without a link), so use
  // findAllByText and grab the one inside an anchor.
  const spans = await screen.findAllByText("How many engines?");
  const link = spans.map((s) => s.closest("a")).find(Boolean);
  expect(link).toHaveAttribute("href", "/research/5?corpus=1");
});

test("active run shows Cancel button; confirming calls cancelResearch and reloads", async () => {
  const cancelMock = vi.spyOn(api, "cancelResearch").mockResolvedValue({ status: "cancelled" });
  // After cancel, list returns the run as cancelled so polling stops.
  vi.spyOn(api, "listResearch")
    .mockResolvedValueOnce(RUNS as any)
    .mockResolvedValue([{ ...RUNS[0], status: "cancelled" }] as any);

  renderList();

  // The active run renders a Cancel button in the "Active runs" section.
  const cancelBtn = await screen.findByRole("button", { name: "Cancel" });
  expect(cancelBtn).toBeInTheDocument();

  // Click opens the confirm dialog.
  fireEvent.click(cancelBtn);
  expect(await screen.findByText("Cancel this run?")).toBeInTheDocument();

  // Confirm triggers the API call.
  fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
  await waitFor(() => expect(cancelMock).toHaveBeenCalledWith(5));
});

// ---- detail page ----------------------------------------------------------

function renderDetail(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes><Route path="/research/:runId" element={<ResearchRun />} /></Routes>
    </MemoryRouter>,
  );
}

test("detail renders the report and citations once done", async () => {
  vi.spyOn(api, "getResearch").mockResolvedValue({
    id: 5, corpus_id: 1, status: "done", progress: {}, prompt: "How many engines?",
    config: { source: "rag", document_ids: [], budget_chars: 100000, max_rounds: 8,
      llm: { provider: "openai", model: "qwen3-14b" } },
    report_markdown: "## Findings\nFive F-1 engines.",
    citations: [{ document_id: 9, pipeline_id: 10, pipeline: "docling_v2", position: 0,
      citation: "saturnv p.4", source: "saturnv_press_kit.pdf", score: 0.91, quote: "five F-1 engines" }],
  } as any);
  renderDetail("/research/5?corpus=1");
  expect(await screen.findByText(/Five F-1 engines/)).toBeInTheDocument();
  expect(screen.getByText(/five F-1 engines/)).toBeInTheDocument(); // citation quote
  expect(screen.getByRole("button", { name: /Download/ })).toBeInTheDocument();
});

test("basename strips a stored filestore path to just the filename", () => {
  expect(basename("/data/filestore/abc123/contract.pdf")).toBe("contract.pdf");
  expect(basename("contract.pdf")).toBe("contract.pdf");
  expect(basename(null)).toBe(null);
});

test("detail shows the citation source as a filename, not the full filestore path", async () => {
  vi.spyOn(api, "getResearch").mockResolvedValue({
    id: 6, corpus_id: 1, status: "done", progress: {}, prompt: "terms?",
    config: { source: "rag", document_ids: [], budget_chars: 100000, max_rounds: 8, llm: {} },
    report_markdown: "Two-year term.",
    citations: [{ document_id: 1, pipeline_id: 10, pipeline: "docling", position: 0,
      citation: "contract.pdf p.1",
      source: "/data/filestore/6cc7d92f/contract.pdf", score: 0.79, quote: "two years" }],
  } as any);
  renderDetail("/research/6?corpus=1");
  expect(await screen.findByText(/contract\.pdf · docling/)).toBeInTheDocument();
  expect(screen.queryByText(/filestore/)).not.toBeInTheDocument();
});

test("detail without a corpus in the URL fails loudly instead of fetching", async () => {
  const get = vi.spyOn(api, "getResearch").mockResolvedValue({} as any);
  renderDetail("/research/5");
  expect(await screen.findByText(/open this run from the Research page/)).toBeInTheDocument();
  expect(get).not.toHaveBeenCalled();
});
