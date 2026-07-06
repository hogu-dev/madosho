// frontend/src/pages/__tests__/Quality.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Quality } from "../Quality";
import { api } from "../../api/client";

const CORPORA = [{ id: 1, name: "aerospace", config: {} }, { id: 2, name: "law", config: {} }];
const DOCS = [{ id: 9, filename: "saturnv.pdf" }, { id: 10, filename: "falcon9.pdf" }];
const CUBE = {
  documents: [
    { document_id: 9,
      retrieval: { semantic: { score: 3.8, source: "static", rationale: "dense recall", suggestion: null } },
      retrieval_total: 3.6,
      pipelines: [
        { name: "saturnv_docling", pipeline_id: 1, effective: true, build_total: 3.5,
          cells: { extraction: { score: 4, source: "measured", rationale: "clean text", suggestion: null } } },
      ] },
  ],
  weights: {},
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listCorpora").mockResolvedValue(CORPORA as any);
  vi.spyOn(api, "listDocuments").mockResolvedValue(DOCS as any);
  vi.spyOn(api, "getRatings").mockResolvedValue(CUBE as any);
  vi.spyOn(api, "getProposal").mockResolvedValue(null);
});

function renderPage(entry = "/quality?corpus=1") {
  return render(<MemoryRouter initialEntries={[entry]}><Quality /></MemoryRouter>);
}

test("loads ratings for the corpus in ?corpus and shows the header", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "Quality" })).toBeInTheDocument();
  await waitFor(() => expect(api.getRatings).toHaveBeenCalledWith(1));
  expect(screen.getByLabelText("Corpus")).toHaveValue("1");
});

test("switching the corpus picker reloads ratings for that corpus", async () => {
  renderPage();
  await waitFor(() => expect(api.getRatings).toHaveBeenCalledWith(1));
  fireEvent.change(screen.getByLabelText("Corpus"), { target: { value: "2" } });
  await waitFor(() => expect(api.getRatings).toHaveBeenCalledWith(2));
});

test("empty corpus renders an empty state", async () => {
  vi.spyOn(api, "getRatings").mockResolvedValue({ documents: [], weights: {} } as any);
  renderPage();
  expect(await screen.findByText(/No rated documents/i)).toBeInTheDocument();
});

test("renders a document group with its pipeline row, build score, and effective tag", async () => {
  renderPage();
  expect(await screen.findByText("saturnv.pdf")).toBeInTheDocument();
  const grid = screen.getByTestId("scoreboard");
  expect(grid).toHaveTextContent("saturnv_docling");   // the pipeline row
  expect(grid).toHaveTextContent("EFFECTIVE");          // effective pipeline flagged
  expect(grid).toHaveTextContent("4");                  // extraction cell score
  expect(grid).toHaveTextContent("3.5");                // build_total, rendered "<n>/5"
  // the per-document rollup row is gone
  expect(screen.queryByText(/Corpus rollup/i)).not.toBeInTheDocument();
});

test("a build dimension with no cell renders a muted dash", async () => {
  renderPage();
  await screen.findByText("saturnv.pdf");
  // the pipeline has only an `extraction` cell; chunk + embed render placeholders
  expect(screen.getAllByTestId("cell-empty").length).toBe(2);
});

test("clicking a scored cell opens a drawer with source + rationale", async () => {
  renderPage();
  await screen.findByText("saturnv.pdf");
  fireEvent.click(screen.getByText("4").closest("[role=button]")!);
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText(/Measured eval/i)).toBeInTheDocument();   // source label
  expect(screen.getByText(/clean text/)).toBeInTheDocument();       // rationale
});

const VMODELS = [{ id: 1, name: "m", corpus_id: 1, provider: "openai", model: "gpt-4o-mini", template: null }];

test("launching an eval posts sampling + navigates to the run", async () => {
  vi.spyOn(api, "listVirtualModels").mockResolvedValue(VMODELS as any);
  const launch = vi.spyOn(api, "launchEval").mockResolvedValue({ id: 77, corpus_id: 1, status: "pending", progress: {} } as any);
  renderPage();
  await screen.findByText("saturnv.pdf");
  fireEvent.change(screen.getByLabelText(/Sample size/i), { target: { value: "12" } });
  fireEvent.click(screen.getByRole("button", { name: /Launch run/i }));
  await waitFor(() => expect(launch).toHaveBeenCalled());
  const [cid, body] = launch.mock.calls[0];
  expect(cid).toBe(1);
  expect(body.sampling).toMatchObject({ n_docs: 12, llm: { provider: "openai", model: "gpt-4o-mini" } });
});

test("run history lists past runs and links to the run detail", async () => {
  vi.spyOn(api, "listEvals").mockResolvedValue([
    { id: 77, corpus_id: 1, status: "done", progress: {}, sampling: { n_docs: 24, llm: { provider: "openai", model: "gpt-4o-mini" } },
      results: { greedy: { baseline_score: 0.64, final_score: 0.82, path: [] } } },
  ] as any);
  renderPage();
  expect(await screen.findByText(/run #77/i)).toBeInTheDocument();
  expect(screen.getByText("done")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /run #77/i })).toHaveAttribute("href", "/quality/eval/77");
});

const PROPOSAL = {
  id: 5, corpus_id: 1, eval_run_id: 77, proposed_config: {}, status: "proposed",
  evidence: { baseline: 0.64, projected: 0.82, lifts: [{ stage: "chunk", label: "late-chunking", lift: 0.18 }] },
};

test("proposal banner is read-only: shows when present and Dismiss clears it, no Build action", async () => {
  vi.spyOn(api, "getProposal").mockResolvedValue(PROPOSAL as any);
  const dismiss = vi.spyOn(api, "dismissProposal").mockResolvedValue({ status: "dismissed" });
  renderPage();
  expect(await screen.findByText(/stronger recipe/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Build pipeline/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
  await waitFor(() => expect(dismiss).toHaveBeenCalledWith(5));
});

test("no banner when getProposal returns null", async () => {
  vi.spyOn(api, "getProposal").mockResolvedValue(null);
  renderPage();
  await screen.findByText("saturnv.pdf");
  expect(screen.queryByText(/stronger recipe/i)).not.toBeInTheDocument();
});
