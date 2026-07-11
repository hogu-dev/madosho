import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AlchemyGoalDetail } from "../AlchemyGoalDetail";
import { api } from "../../api/client";

let canWrite = true;
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite }) }));

const GOAL = { id: 3, name: "sota-watch", corpus_id: 1, goal_type: "living-research",
  spec: {}, coverage: "full", include_generated: false, created_at: "2026-07-01T10:00:00Z" };

const ENDPOINTS = [
  { id: 1, name: "granite-local", provider: "openai", model: "granite-4.1",
    api_base: "http://h:8099/v1", key_env_var: null, is_default: true, key_present: false },
  { id: 2, name: "qwen-local", provider: "openai", model: "qwen3-14b",
    api_base: "http://h:8099/v1", key_env_var: null, is_default: false, key_present: false },
];

const RUNS = [
  { id: 23, goal_id: 3, version: 3, status: "running", coverage: "full",
    guidance: "focus on tables", based_on_version: 2, stop_reason: null,
    usage: { llm_calls: 4 }, is_final: false, ingested_document_id: null, error: null,
    created_at: "2026-07-08T10:00:00Z", finished_at: null },
  { id: 22, goal_id: 3, version: 2, status: "done", coverage: "full", guidance: null,
    based_on_version: 1, stop_reason: "round_cap", usage: { llm_calls: 12, total_tokens: 90210 },
    is_final: false, ingested_document_id: null, error: null,
    created_at: "2026-07-07T10:00:00Z", finished_at: "2026-07-07T11:00:00Z" },
  { id: 21, goal_id: 3, version: 1, status: "done", coverage: "search", guidance: null,
    based_on_version: null, stop_reason: "final", usage: { llm_calls: 9 }, is_final: true,
    ingested_document_id: 44, error: null, created_at: "2026-07-06T10:00:00Z",
    finished_at: "2026-07-06T11:00:00Z" },
];

beforeEach(() => {
  canWrite = true;
  vi.restoreAllMocks();
  vi.spyOn(api, "getAlchemyGoal").mockResolvedValue(GOAL as any);
  vi.spyOn(api, "listAlchemyRuns").mockResolvedValue(RUNS as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue(ENDPOINTS as any);
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/alchemy/3"]}>
      <Routes>
        <Route path="/alchemy/:goalRef" element={<AlchemyGoalDetail />} />
        <Route path="/alchemy/:goalRef/runs/:version" element={<div>run detail stub</div>} />
      </Routes>
    </MemoryRouter>);
}

test("renders the goal header (name, type, coverage, corpus)", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "sota-watch" })).toBeInTheDocument();
  expect(screen.getByText("living-research")).toBeInTheDocument();
  expect(screen.getByText("corpus 1")).toBeInTheDocument();
  expect(screen.getByText("coverage full")).toBeInTheDocument();
});

test("runs table shows version, guidance, calls, stop reason and the final pill", async () => {
  renderPage();
  expect(await screen.findByText("v3")).toBeInTheDocument();
  expect(screen.getByText("v2")).toBeInTheDocument();
  expect(screen.getByText("focus on tables")).toBeInTheDocument();  // guidance (truncated cell)
  expect(screen.getByText("12")).toBeInTheDocument();               // v2 llm_calls
  expect(screen.getByText("round_cap")).toBeInTheDocument();        // stop reason column
  // "final" appears once as v1's stop_reason text and once as its is_final pill.
  expect(screen.getAllByText("final")).toHaveLength(2);
});

test("run rows link to the run detail by version", async () => {
  renderPage();
  const v3 = await screen.findByText("v3");
  expect(v3.closest("a")).toHaveAttribute("href", "/alchemy/3/runs/3");
});
