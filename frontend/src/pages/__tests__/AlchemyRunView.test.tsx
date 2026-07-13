import { render, screen, fireEvent } from "@testing-library/react";
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

test("search-mode ledger with complete: null shows no red incomplete indicator", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN,
    ledger: { ...DONE_RUN.ledger, mode: "search", complete: null, shortfall: null } } as any);
  renderPage();
  expect(await screen.findByText(/consulted 4 \/ 5 docs/)).toBeInTheDocument();
  expect(screen.queryByText("incomplete")).not.toBeInTheDocument();
  expect(screen.queryByText("complete")).not.toBeInTheDocument();
});

test("ledger with an unknown corpus size renders '?' not a blank or 'null'", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN,
    ledger: { ...DONE_RUN.ledger, total_docs: null } } as any);
  renderPage();
  expect(await screen.findByText(/consulted 4 \/ \? docs/)).toBeInTheDocument();
});

test("download button creates a blob url, removes its anchor, and revokes on the next tick", async () => {
  const createURL = vi.fn(() => "blob:xyz");
  const revokeURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL: createURL, revokeObjectURL: revokeURL });
  renderPage();
  const btn = await screen.findByRole("button", { name: /Download/ });
  vi.useFakeTimers();
  fireEvent.click(btn);
  expect(createURL).toHaveBeenCalledTimes(1);
  expect(document.querySelector("a[download]")).toBeNull();   // appended for the click, then removed
  expect(revokeURL).not.toHaveBeenCalled();                   // deferred, not synchronous
  vi.runAllTimers();
  expect(revokeURL).toHaveBeenCalledWith("blob:xyz");
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("activity log lists the agents' tool calls with args and result, and counts them", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN, run_log: [
    { round: 1, section: "overview", kind: "llm", has_tool_calls: true, text_chars: 40 },
    { round: 1, section: "overview", kind: "tool_call", name: "search",
      args: { corpus: "aerospace", query: "F-1 engines" }, ok: true, chars: 4200 },
    { round: 2, section: "overview", kind: "tool_call", name: "get-doc",
      args: { document_id: 9 }, ok: false, error: "not found", chars: 0 },
  ] } as any);
  renderPage();
  expect(await screen.findByText(/2 tool calls/)).toBeInTheDocument();
  expect(screen.getByText("search")).toBeInTheDocument();
  expect(screen.getByText("F-1 engines")).toBeInTheDocument();       // arg summary (the query)
  expect(screen.getByText("get-doc")).toBeInTheDocument();
  expect(screen.getByText(/not found/)).toBeInTheDocument();         // failed call surfaces its error
});

test("activity log shows the model's prose (with an ellipsis when the preview was capped)", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN, run_log: [
    // full text preserved (text_chars == text.length): no ellipsis
    { round: 1, kind: "llm", has_tool_calls: false, text: "I have enough to write.", text_chars: 23 },
    // capped preview (text_chars > text.length): trailing ellipsis
    { round: 2, kind: "llm", has_tool_calls: false, text: "The corpus shows that", text_chars: 640 },
  ] } as any);
  renderPage();
  expect(await screen.findByText("I have enough to write.")).toBeInTheDocument();
  expect(screen.getByText(/^The corpus shows that…$/)).toBeInTheDocument();
});

test("no activity panel when the run has no log", async () => {
  renderPage();   // DONE_RUN.run_log is []
  expect(await screen.findByText("Overview")).toBeInTheDocument();
  expect(screen.queryByText(/tool calls?/)).not.toBeInTheDocument();
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

test("surfaces the goal's prompt text on the run view", async () => {
  vi.spyOn(api, "getAlchemyGoal").mockResolvedValue({ ...GOAL,
    spec: { goal: "Summarize how photosynthesis stores energy, using only the corpus." } } as any);
  renderPage();
  expect(await screen.findByText(/how photosynthesis stores energy/)).toBeInTheDocument();
});

test("a running run streams a LIVE activity console with its tool calls", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN, status: "running",
    is_final: false, stop_reason: null, finished_at: null, draft_markdown: null,
    sections: [], citations: [], ledger: null, progress: { phase: "running" },
    run_log: [
      { round: 1, kind: "llm", has_tool_calls: true, text_chars: 12 },
      { round: 1, kind: "tool_call", name: "search",
        args: { query: "photosynthesis energy" }, ok: true, chars: 3100 },
    ] } as any);
  renderPage();
  // the live marker shows while the run is active, and the streamed call renders
  expect(await screen.findByText("live")).toBeInTheDocument();
  expect(screen.getByText("search")).toBeInTheDocument();
  expect(screen.getByText("photosynthesis energy")).toBeInTheDocument();
});

test("a resolved run's activity log shows no LIVE marker", async () => {
  vi.spyOn(api, "getAlchemyRun").mockResolvedValue({ ...DONE_RUN, run_log: [
    { round: 1, kind: "tool_call", name: "search", args: { query: "x" }, ok: true, chars: 10 },
  ] } as any);
  renderPage();
  expect(await screen.findByText(/1 tool call/)).toBeInTheDocument();
  expect(screen.queryByText("live")).not.toBeInTheDocument();
});
