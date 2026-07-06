import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Scrying } from "../Scrying";
import { api } from "../../api/client";

const CORPORA = [{ id: 1, name: "aerospace", config: {} }, { id: 2, name: "law", config: {} }];
const ENDPOINTS = [
  { id: 1, name: "gemma4-local", provider: "openai", model: "gemma-4-e4b",
    api_base: "http://h:8081/v1", key_env_var: null, is_default: true, key_present: false },
  { id: 2, name: "qwen3-local", provider: "openai", model: "qwen3-14b",
    api_base: "http://h:8081/v1", key_env_var: null, is_default: false, key_present: false },
];
const HITS = {
  hits: [
    { text: "five F-1 engines, 7,500,000 pounds of thrust", score: 12, page: 4, citation: "saturnv p.4",
      source: "saturnv_press_kit.pdf", document_id: 9, position: 0, pipeline: "docling_v2", pipeline_id: 10 },
    { text: "RP-1 and liquid oxygen", score: 6, page: 5, citation: "saturnv p.5",
      source: "saturnv_press_kit.pdf", document_id: 9, position: 1, pipeline: "docling_v2", pipeline_id: 10 },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listCorpora").mockResolvedValue(CORPORA as any);
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue(ENDPOINTS as any);
});

function renderPage(entry = "/scrying") {
  return render(<MemoryRouter initialEntries={[entry]}><Scrying /></MemoryRouter>);
}

test("renders the composer with corpus options after load", async () => {
  renderPage();
  expect(await screen.findByRole("option", { name: "aerospace" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Cast/ })).toBeInTheDocument();
});

test("retrieval-only Cast omits llm and renders source chunks", async () => {
  const q = vi.spyOn(api, "query").mockResolvedValue(HITS as any);
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });
  fireEvent.click(screen.getByRole("button", { name: "Retrieval only" }));
  fireEvent.change(screen.getByPlaceholderText(/Ask the corpus/), { target: { value: "thrust?" } });
  fireEvent.click(screen.getByRole("button", { name: /Cast/ }));
  await waitFor(() => expect(q).toHaveBeenCalled());
  const params = q.mock.calls[0][0];
  expect(params).toMatchObject({ corpus: "aerospace", prompt: "thrust?" });
  expect(params).not.toHaveProperty("llm");
  expect(await screen.findByText(/five F-1 engines/)).toBeInTheDocument();
  expect(screen.getByText(/Source chunks/)).toBeInTheDocument();
});

test("Cast is disabled until a question is typed", async () => {
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });
  expect(screen.getByRole("button", { name: /Cast/ })).toBeDisabled();
});

import { splitSources, promptTokens } from "../Scrying";

const ANSWER = {
  answer: "The S-IC produced 7.5M lbf [1] from five F-1 engines [2].\n\nSources:\n[1] saturnv p.4\n[2] saturnv p.5",
  citations: [
    { text: "...", score: 12, page: 4, citation: "saturnv p.4", source: "saturnv_press_kit.pdf",
      document_id: 9, position: 0, pipeline: "docling_v2", pipeline_id: 10 },
    { text: "...", score: 6, page: 5, citation: "saturnv p.5", source: "saturnv_press_kit.pdf",
      document_id: 9, position: 1, pipeline: "docling_v2", pipeline_id: 10 },
  ],
  usage: { prompt_tokens: 3114, completion_tokens: 60, total_tokens: 3174 },
  messages: [{ role: "system", content: "You are a careful analyst. Context: ..." },
             { role: "user", content: "thrust?" }],
};

test("splitSources strips the appended Sources footer", () => {
  expect(splitSources("Body text [1].\n\nSources:\n[1] x p.1")).toBe("Body text [1].");
  expect(splitSources("No footer here")).toBe("No footer here");
});

test("promptTokens reads prompt_tokens or returns null", () => {
  expect(promptTokens({ prompt_tokens: 3114 })).toBe(3114);
  expect(promptTokens(null)).toBeNull();
  expect(promptTokens({ completion_tokens: 5 })).toBeNull();
});

test("document-scoped scry sends document_id and hides the corpus picker", async () => {
  vi.spyOn(api, "getDocument").mockResolvedValue({ id: 9, filename: "saturnv.pdf" } as any);
  const q = vi.spyOn(api, "query").mockResolvedValue(HITS as any);
  renderPage("/scrying?document=9");
  expect(await screen.findByText(/saturnv\.pdf/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Corpus")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retrieval only" }));
  fireEvent.change(screen.getByPlaceholderText(/Ask/), { target: { value: "thrust?" } });
  fireEvent.click(screen.getByRole("button", { name: /Cast/ }));
  await waitFor(() => expect(q).toHaveBeenCalled());
  expect(q.mock.calls[0][0]).toMatchObject({ document_id: 9, prompt: "thrust?" });
  expect(q.mock.calls[0][0]).not.toHaveProperty("corpus");
});

test("malformed ?document param falls back to corpus scope", async () => {
  renderPage("/scrying?document=abc");
  expect(await screen.findByLabelText("Corpus")).toBeInTheDocument();
});

test("changing corpus after a Cast clears the stale result", async () => {
  vi.spyOn(api, "query").mockResolvedValue(HITS as any);
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });
  fireEvent.click(screen.getByRole("button", { name: "Retrieval only" }));
  fireEvent.change(screen.getByPlaceholderText(/Ask the corpus/), { target: { value: "thrust?" } });
  fireEvent.click(screen.getByRole("button", { name: /Cast/ }));
  expect(await screen.findByText(/five F-1 engines/)).toBeInTheDocument();
  // switching corpus must drop the prior answer so it can't describe a different scope
  fireEvent.change(screen.getByLabelText("Corpus"), { target: { value: "law" } });
  await waitFor(() => expect(screen.queryByText(/five F-1 engines/)).not.toBeInTheDocument());
});

test("lists registry endpoints as Answer models", async () => {
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });
  // Answer mode is the default — endpoints appear as model options
  expect(await screen.findByRole("option", { name: "gemma4-local" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "qwen3-local" })).toBeInTheDocument();
});

test("warns when no LLM endpoint is configured and disables Cast", async () => {
  vi.spyOn(api, "listLlmEndpoints").mockResolvedValue([]);
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });
  expect(await screen.findByText(/needs an LLM endpoint/)).toBeInTheDocument();
  // Type a question — Cast should still be disabled (no endpoint)
  fireEvent.change(screen.getByPlaceholderText(/Ask the corpus/), { target: { value: "thrust?" } });
  expect(screen.getByRole("button", { name: /Cast/ })).toBeDisabled();
  // Retrieval mode must still work with no endpoints
  fireEvent.click(screen.getByRole("button", { name: "Retrieval only" }));
  expect(screen.getByRole("button", { name: /Cast/ })).not.toBeDisabled();
});

test("answer Cast sends llm and renders answer prose + Sources chips + assembled prompt", async () => {
  const q = vi.spyOn(api, "query").mockResolvedValue(ANSWER as any);
  renderPage();
  await screen.findByRole("option", { name: "aerospace" });   // Answer is the default mode
  // Wait for the model dropdown to appear with the default endpoint
  await screen.findByRole("option", { name: "gemma4-local" });
  fireEvent.change(screen.getByPlaceholderText(/Ask the corpus/), { target: { value: "thrust?" } });
  fireEvent.click(screen.getByRole("button", { name: /Cast/ }));
  await waitFor(() => expect(q).toHaveBeenCalled());
  expect(q.mock.calls[0][0]).toMatchObject({ corpus: "aerospace", prompt: "thrust?",
    llm: "gemma4-local" });
  // answer prose shown WITHOUT the duplicated Sources footer
  expect(await screen.findByText(/five F-1 engines/)).toBeInTheDocument();
  expect(screen.queryByText(/^Sources:$/)).not.toBeInTheDocument();
  // Sources chips (one per citation) link to the document
  const chips = screen.getAllByRole("link", { name: /saturnv_press_kit\.pdf/ });
  expect(chips.length).toBeGreaterThanOrEqual(2);
  // assembled prompt is collapsed; expanding reveals the messages + token count
  fireEvent.click(screen.getByText(/Assembled prompt/));
  expect(await screen.findByText(/You are a careful analyst/)).toBeInTheDocument();
  expect(screen.getByText(/3,114 tokens/)).toBeInTheDocument();
});
