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

// Per-endpoint model lists for the launch form's Model dropdown; endpoint 1's
// first model keeps the pinned id so the default-model assertions hold.
const MODELS_BY_ENDPOINT: Record<number, any[]> = {
  1: [{ id: "granite-4.1", reasoning_efforts: ["low", "medium", "high"], default_effort: "medium" },
      { id: "granite-4.1-mini", reasoning_efforts: [], default_effort: null }],
  2: [{ id: "qwen3-14b", reasoning_efforts: [], default_effort: null }],
};

beforeEach(() => {
  canWrite = true;
  vi.restoreAllMocks();
  vi.spyOn(api, "getAlchemyGoal").mockResolvedValue(GOAL as any);
  vi.spyOn(api, "listAlchemyRuns").mockResolvedValue(RUNS as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue(ENDPOINTS as any);
  vi.spyOn(api, "listEndpointModels")
    .mockImplementation((id: number) => Promise.resolve((MODELS_BY_ENDPOINT[id] ?? []) as any));
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

test("coverage toggle defaults to the goal's coverage", async () => {
  renderPage();
  await screen.findByRole("heading", { name: "sota-watch" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Full" })).toHaveAttribute("aria-pressed", "true"));
});

test("Endpoint defaults to the default endpoint, Model to its pinned model; launch sends the payload and navigates", async () => {
  const launch = vi.spyOn(api, "launchAlchemyRun").mockResolvedValue(
    { id: 30, goal_id: 3, version: 4, status: "pending" } as any);
  renderPage();
  await screen.findByRole("option", { name: "granite-local" });
  expect((screen.getByLabelText("Endpoint") as HTMLSelectElement).value).toBe("granite-local");
  // Model defaults to the endpoint's pinned model once the model list loads
  // (poll: the default is applied a render after the options appear).
  await waitFor(() =>
    expect((screen.getByLabelText("Model") as HTMLSelectElement).value).toBe("granite-4.1"));
  fireEvent.change(screen.getByLabelText("Guidance"), { target: { value: "check the new PDFs" } });
  fireEvent.change(screen.getByLabelText("Max LLM calls"), { target: { value: "40" } });
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  await waitFor(() => expect(launch).toHaveBeenCalled());
  const [ref, body] = launch.mock.calls[0];
  expect(ref).toBe(3);
  expect(body).toEqual({ coverage: "full", guidance: "check the new PDFs", max_llm_calls: 40,
    concurrency: 1, llm: { provider: "openai", model: "granite-4.1" } });
  expect(await screen.findByText("run detail stub")).toBeInTheDocument();
});

test("sends reasoning_effort when a level from the model's ladder is picked", async () => {
  const launch = vi.spyOn(api, "launchAlchemyRun").mockResolvedValue(
    { id: 31, goal_id: 3, version: 5, status: "pending" } as any);
  renderPage();
  // await a ladder option (not just the model option): the ladder is populated
  // a render after the model default settles, so "low" appearing means it's ready.
  await screen.findByRole("option", { name: "low" });
  fireEvent.change(screen.getByLabelText(/reasoning effort/i), { target: { value: "low" } });
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  await waitFor(() => {
    const body = launch.mock.calls.at(-1)?.[1] as any;
    expect(body.reasoning_effort).toBe("low");
  });
});

test("the Model dropdown fans out the endpoint's models; picking one sends it and gates reasoning", async () => {
  const launch = vi.spyOn(api, "launchAlchemyRun").mockResolvedValue(
    { id: 32, goal_id: 3, version: 6, status: "pending" } as any);
  renderPage();
  await screen.findByRole("option", { name: "granite-4.1" });
  expect(screen.getByRole("option", { name: "granite-4.1-mini" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Model"), { target: { value: "granite-4.1-mini" } });
  // granite-4.1-mini has an empty ladder -> Reasoning select disabled
  expect(screen.getByLabelText(/reasoning effort/i)).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  await waitFor(() => expect(launch).toHaveBeenCalled());
  const body = launch.mock.calls.at(-1)?.[1] as any;
  expect(body.llm).toEqual({ provider: "openai", model: "granite-4.1-mini" });
});

test("cancel on a running run confirms then POSTs the DB id", async () => {
  const cancel = vi.spyOn(api, "cancelAlchemyRun").mockResolvedValue({ status: "cancelled" });
  renderPage();
  const btn = await screen.findByRole("button", { name: "Cancel" });
  fireEvent.click(btn);
  expect(await screen.findByText("Cancel v3?")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
  await waitFor(() => expect(cancel).toHaveBeenCalledWith(23));
});

test("finalize on a done non-final run confirms then finalizes that version", async () => {
  const fin = vi.spyOn(api, "finalizeAlchemyRun").mockResolvedValue({} as any);
  renderPage();
  const btn = await screen.findByRole("button", { name: "Finalize" });  // only v2 qualifies
  fireEvent.click(btn);
  fireEvent.click(await screen.findByRole("button", { name: "Finalize v2" }));
  await waitFor(() => expect(fin).toHaveBeenCalledWith("3", 2));
});

test("read-only scope disables all mutating buttons", async () => {
  canWrite = false;
  renderPage();
  expect(await screen.findByRole("button", { name: "Run" })).toBeDisabled();
  expect(await screen.findByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Finalize" })).toBeDisabled();
});
