// frontend/src/api/__tests__/ratings.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "../client";

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    { ok: status < 400, status, json: async () => body, statusText: "" } as Response);
}

describe("ratings api", () => {
  it("getRatings hits the cube route", async () => {
    const f = mockFetch({ documents: [], weights: {} });
    const cube = await api.getRatings(7);
    expect(f).toHaveBeenCalledWith("/api/corpora/7/ratings", expect.anything());
    expect(cube.documents).toEqual([]);
  });

  it("runRatings posts", async () => {
    const f = mockFetch({ running: 3 });
    expect(await api.runRatings(7)).toEqual({ running: 3 });
    expect(f).toHaveBeenCalledWith("/api/corpora/7/ratings/run", expect.objectContaining({ method: "POST" }));
  });

  it("postVerdict posts the chosen side", async () => {
    const f = mockFetch({ verdict: "a" });
    await api.postVerdict(4, "a");
    expect(f).toHaveBeenCalledWith("/api/documents/4/comparison/verdict",
      expect.objectContaining({ method: "POST" }));
  });
});
