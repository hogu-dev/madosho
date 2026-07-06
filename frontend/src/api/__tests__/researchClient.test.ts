import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../client";

describe("research client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("launchResearch POSTs the body to the corpus research route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 1, status: "pending" }),
        { status: 201, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await api.launchResearch(7, {
      prompt: "q?", source: "rag", document_ids: [], budget_chars: 100000,
      max_rounds: 8, llm: { provider: "openai", model: "m" },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/corpora/7/research");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).prompt).toBe("q?");
  });

  it("getResearch GETs the nested run route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 3, status: "done" }),
        { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await api.getResearch(7, 3);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/corpora/7/research/3");
  });

  it("cancelResearch POSTs to the run cancel route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "cancelled" }),
        { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await api.cancelResearch(5);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/research/5/cancel");
    expect(init.method).toBe("POST");
  });
});
