// frontend/src/api/__tests__/eval.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../client";

describe("eval api", () => {
  beforeEach(() => { vi.restoreAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  function mockFetch(status: number, body: unknown) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: status < 400, status, statusText: "x", json: async () => body,
    } as Response));
  }

  it("launchEval POSTs sampling + budget", async () => {
    mockFetch(201, { id: 3, corpus_id: 7, status: "pending", progress: {} });
    const run = await api.launchEval(7, { sampling: { n_docs: 5,
      llm: { provider: "openai", model: "gemma-e4b" } }, token_budget: 50000 });
    expect(run.id).toBe(3);
    expect(fetch).toHaveBeenCalledWith("/api/corpora/7/evals", expect.objectContaining({ method: "POST" }));
  });

  it("listEvals GETs the run list", async () => {
    mockFetch(200, [{ id: 1, corpus_id: 7, status: "done", progress: {} }]);
    const runs = await api.listEvals(7);
    expect(runs[0].status).toBe("done");
    expect(fetch).toHaveBeenCalledWith("/api/corpora/7/evals", expect.objectContaining({ method: "GET" }));
  });

  it("getEval GETs run detail", async () => {
    mockFetch(200, { id: 2, corpus_id: 7, status: "running", progress: { phase: "scan" } });
    const run = await api.getEval(2);
    expect(run.progress.phase).toBe("scan");
  });

  it("cancelEval POSTs cancel", async () => {
    mockFetch(200, { status: "cancelled" });
    await api.cancelEval(2);
    expect(fetch).toHaveBeenCalledWith("/api/evals/2/cancel", expect.objectContaining({ method: "POST" }));
  });

  it("getProposal GETs the active proposal", async () => {
    mockFetch(200, { id: 1, corpus_id: 7, eval_run_id: 2,
      proposed_config: {}, evidence: { baseline: 0.4, projected: 0.6, lifts: [] }, status: "proposed" });
    const p = await api.getProposal(7);
    expect(p?.evidence.projected).toBe(0.6);
  });

  it("getProposal returns null on 404", async () => {
    mockFetch(404, { detail: "no active proposal" });
    const p = await api.getProposal(7);
    expect(p).toBeNull();
  });

  it("dismissProposal POSTs", async () => {
    mockFetch(200, { status: "dismissed" });
    await api.dismissProposal(1);
    expect(fetch).toHaveBeenCalledWith("/api/proposals/1/dismiss", expect.objectContaining({ method: "POST" }));
  });
});
