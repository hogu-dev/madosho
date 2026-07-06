// frontend/src/pages/__tests__/EvalRun.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { EvalRun } from "../EvalRun";
import { api } from "../../api/client";

const RUN = {
  id: 77, corpus_id: 1, status: "done", progress: { phase: "done" },
  sampling: { n_docs: 24, llm: { provider: "openai", model: "gpt-4o-mini" } },
  tokens_spent: 812000,
  results: { baseline: { mrr: 0.58, "ndcg@5": 0.69 },
             greedy: { baseline_score: 0.64, final_score: 0.82,
               path: [{ stage: "chunk", label: "late-chunking", score: 0.75, lift: 0.11 }] } },
};

beforeEach(() => { vi.restoreAllMocks(); vi.spyOn(api, "getProposal").mockResolvedValue(null); });

function renderRun(run = RUN) {
  vi.spyOn(api, "getEval").mockResolvedValue(run as any);
  return render(
    <MemoryRouter initialEntries={["/quality/eval/77"]}>
      <Routes><Route path="/quality/eval/:runId" element={<EvalRun />} /></Routes>
    </MemoryRouter>);
}

test("renders the run header, status, and sampling meta", async () => {
  renderRun();
  expect(await screen.findByText(/run #77/i)).toBeInTheDocument();
  expect(screen.getByText("done")).toBeInTheDocument();
  expect(screen.getByText(/24 docs/i)).toBeInTheDocument();
  expect(screen.getByText(/gpt-4o-mini/)).toBeInTheDocument();
});

test("tolerates a run with no results (early exit)", async () => {
  renderRun({ ...RUN, results: { note: "no golden questions generated" } } as any);
  expect(await screen.findByText(/run #77/i)).toBeInTheDocument();
  expect(screen.getByText(/no golden questions/i)).toBeInTheDocument();
});

test("metric cards show the greedy before/after and baseline values", async () => {
  renderRun();
  await screen.findByText(/run #77/i);
  // headline retrieval score before -> after
  expect(screen.getByText("0.82")).toBeInTheDocument();
  expect(screen.getByText(/0\.64/)).toBeInTheDocument();
  expect(screen.getByText(/\+0\.18/)).toBeInTheDocument();
  // a baseline metric key card
  expect(screen.getByText(/mrr/i)).toBeInTheDocument();
});

test("greedy path renders each step with kept/reverted and lift", async () => {
  renderRun();
  await screen.findByText(/run #77/i);
  expect(screen.getByText(/Greedy search path/i)).toBeInTheDocument();
  expect(screen.getByText(/late-chunking/)).toBeInTheDocument();
  expect(screen.getAllByText((_, el) => el?.tagName === "SPAN" && el?.textContent?.replace(/\s+/g, " ").trim() === "kept - +0.11").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText(/\+0\.11/)).toBeInTheDocument();
});

test("proposed recipe block is read-only: shows the recipe and dismisses, no Build action", async () => {
  vi.spyOn(api, "getProposal").mockResolvedValue({
    id: 5, corpus_id: 1, eval_run_id: 77, proposed_config: {}, status: "proposed",
    evidence: { baseline: 0.64, projected: 0.82, lifts: [{ stage: "chunk", label: "late-chunking", lift: 0.18 }] },
  } as any);
  const dismiss = vi.spyOn(api, "dismissProposal").mockResolvedValue({ status: "dismissed" });
  renderRun();
  expect(await screen.findByText(/Proposed recipe/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Build pipeline/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
  await waitFor(() => expect(dismiss).toHaveBeenCalledWith(5));
});
