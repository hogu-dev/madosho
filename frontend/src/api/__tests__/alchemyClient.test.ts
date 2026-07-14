import { api } from "../client";
import type { AlchemyRunLaunch } from "../types";

beforeEach(() => { vi.restoreAllMocks(); });

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), { status }));
}

test("listAlchemyGoals GETs /alchemy/goals", async () => {
  const fetchMock = mockFetch(200, [{ id: 3, name: "sota-watch", corpus_id: 1,
    goal_type: "living-research", spec: {}, coverage: "full", include_generated: false,
    created_at: null }]);
  const out = await api.listAlchemyGoals();
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals",
    expect.objectContaining({ method: "GET" }));
  expect(out[0].name).toBe("sota-watch");
});

test("getAlchemyGoal GETs /alchemy/goals/:ref", async () => {
  const fetchMock = mockFetch(200, { id: 3, name: "sota-watch" });
  await api.getAlchemyGoal(3);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals/3",
    expect.objectContaining({ method: "GET" }));
});

test("listAlchemyRuns GETs the goal's runs", async () => {
  const fetchMock = mockFetch(200, [{ id: 21, goal_id: 3, version: 1, status: "done" }]);
  const out = await api.listAlchemyRuns(3);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals/3/runs",
    expect.objectContaining({ method: "GET" }));
  expect(out[0].version).toBe(1);
});

test("getAlchemyRun GETs one run by version", async () => {
  const fetchMock = mockFetch(200, { id: 21, goal_id: 3, version: 2, status: "done" });
  await api.getAlchemyRun(3, 2);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals/3/runs/2",
    expect.objectContaining({ method: "GET" }));
});

test("launchAlchemyRun POSTs the launch body as-is", async () => {
  const fetchMock = mockFetch(201, { id: 30, goal_id: 3, version: 4, status: "pending" });
  const body: AlchemyRunLaunch = { coverage: "full", guidance: "focus on tables",
    max_llm_calls: 40, concurrency: 2, llm: { provider: "openai", model: "granite-4.1" } };
  await api.launchAlchemyRun(3, body);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals/3/runs",
    expect.objectContaining({ method: "POST" }));
  const sent = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
  expect(sent).toEqual(body);
});

test("cancelAlchemyRun POSTs the DB run id, not the version", async () => {
  const fetchMock = mockFetch(200, { status: "cancelled" });
  await api.cancelAlchemyRun(23);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/runs/23/cancel",
    expect.objectContaining({ method: "POST" }));
});

test("finalizeAlchemyRun POSTs version (ingest defaults false)", async () => {
  const fetchMock = mockFetch(200, { id: 22, goal_id: 3, version: 2, is_final: true });
  await api.finalizeAlchemyRun("3", 2);
  expect(fetchMock).toHaveBeenCalledWith("/api/alchemy/goals/3/finalize",
    expect.objectContaining({ method: "POST" }));
  const sent = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
  expect(sent).toEqual({ version: 2, ingest: false });
});
