import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AlchemyRunView } from "../AlchemyRunView";
import { api } from "../../api/client";

const GOAL = { id: 3, name: "sota-watch", corpus_id: 1, goal_type: "living-research",
  spec: {}, coverage: "full", include_generated: false, created_at: null };

const DONE_RUN = {
  id: 22, goal_id: 3, version: 2, status: "done", coverage: "full",
  guidance: "focus on tables", based_on_version: 1, stop_reason: "final",
  usage: { llm_calls: 12, prompt_tokens: 80000, completion_tokens: 10210, total_tokens: 90210 },
  is_final: true, ingested_document_id: null, error: null,
  created_at: "2026-07-07T10:00:00Z", finished_at: "2026-07-07T11:00:00Z",
  draft_markdown: "## Findings\nFive F-1 engines.",
  citations: [{ document_id: 9, pipeline_id: 10, pipeline: "docling_v2", position: 0,
    citation: "saturnv p.4", source: "/data/filestore/abc/saturnv_press_kit.pdf",
    score: 0.91, quote: "five F-1 engines" }],
  run_log: [],
  sections: [
    { key: "overview", title: "Overview", content: "filled text", filled: true, note: null,
      confidence: { level: "high", self_grade: 5, distinct_docs: 3, citations: 7 },
      stop_reason: "final", llm_calls: 5 },
    { key: "gaps", title: "Open gaps", content: "", filled: false, note: "no sources found",
      confidence: { level: "low", self_grade: 1, distinct_docs: 0, citations: 0 },
      stop_reason: "no_tools_used", llm_calls: 1 },
  ],
  ledger: { mode: "full", total_docs: 5,
    consulted: { "9": "search", "10": "forced", "11": "read", "12": "search" },
    from_prior: [], unconsulted: [13], failures: {}, complete: false,
    shortfall: "1 document could not be consulted", summary: "consulted 4 of 5" },
  artifact_counts: { note: 3 },
  progress: {},
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getAlchemyGoal").mockResolvedValue(GOAL as any);
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue(DONE_RUN as any);
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/alchemy/3/runs/2"]}>
      <Routes>
        <Route path="/alchemy/:goalRef/runs/:version" element={<AlchemyRunView />} />
      </Routes>
    </MemoryRouter>);
}

test("renders heading, final pill and the meta row", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: /sota-watch v2/ })).toBeInTheDocument();
  expect(screen.getByText("final")).toBeInTheDocument();            // is_final pill (exact)
  expect(screen.getByText("stopped: final")).toBeInTheDocument();
  expect(screen.getByText("based on v1")).toBeInTheDocument();
  expect(screen.getByText("12 calls")).toBeInTheDocument();
  expect(screen.getByText("90210 tokens")).toBeInTheDocument();
});

test("shows the guidance blockquote", async () => {
  renderPage();
  expect(await screen.findByText("focus on tables")).toBeInTheDocument();
});

test("ledger shows coverage numbers, completeness and shortfall", async () => {
  renderPage();
  expect(await screen.findByText(/consulted 4 \/ 5 docs/)).toBeInTheDocument();
  expect(screen.getByText("incomplete")).toBeInTheDocument();
  expect(screen.getByText(/could not be consulted/)).toBeInTheDocument();
  expect(screen.getByText("consulted 4 of 5")).toBeInTheDocument(); // summary line
});

test("sections table shows confidence pills, counts and unfilled notes", async () => {
  renderPage();
  expect(await screen.findByText("Overview")).toBeInTheDocument();
  expect(screen.getByText("high")).toBeInTheDocument();
  expect(screen.getByText(/3 docs \/ 7 cites/)).toBeInTheDocument();
  expect(screen.getByText("no")).toBeInTheDocument();               // unfilled flag on "Open gaps"
  expect(screen.getByText("no sources found")).toBeInTheDocument();
});

test("renders the draft as markdown, citations as document links, and a download button", async () => {
  renderPage();
  expect(await screen.findByText(/Five F-1 engines/)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
  expect(screen.getByText(/five F-1 engines/)).toBeInTheDocument(); // citation quote
  const link = screen.getByText(/saturnv_press_kit\.pdf/).closest("a");
  expect(link).toHaveAttribute("href", "/documents/9");
  expect(screen.getByRole("button", { name: /Download/ })).toBeInTheDocument();
});

test("a running run shows the working phase and no download", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN, status: "running",
    is_final: false, stop_reason: null, finished_at: null, draft_markdown: null,
    sections: [], citations: [], ledger: null,
    progress: { phase: "coverage pass" } } as any);
  renderPage();
  expect(await screen.findByText(/coverage pass/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();
});
