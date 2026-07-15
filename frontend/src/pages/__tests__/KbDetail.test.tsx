import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { KbDetail } from "../KbDetail";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getKb: vi.fn(), getKbPage: vi.fn(), addKbPage: vi.fn(), editKbPage: vi.fn(),
    listKbs: vi.fn(), moveKbPage: vi.fn() },
}));
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

const KB = {
  id: 3, name: "Notes", slug: "notes", corpus_id: 1, corpus_name: "c1",
  index_markdown: "# Index\n",
  pages: [{ type: "concept", title: "Reranking", slug: "reranking", description: "reorder" }],
};

beforeEach(() => {
  vi.restoreAllMocks();
  (api.getKb as any).mockResolvedValue(KB);
  (api.listKbs as any).mockResolvedValue([
    { id: 3, name: "Notes", slug: "notes", corpus_id: 1, corpus_name: "c1" },
    { id: 9, name: "Archive", slug: "archive", corpus_id: 1, corpus_name: "c1" },
  ]);
});

function renderAt(id = "3") {
  return render(
    <MemoryRouter initialEntries={[`/knowledge-bases/${id}`]}>
      <Routes><Route path="/knowledge-bases/:kbId" element={<KbDetail />} /></Routes>
    </MemoryRouter>);
}

describe("KbDetail", () => {
  it("shows the KB name and its pages", async () => {
    renderAt();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Notes" })).toBeInTheDocument());
    expect(screen.getByText("Reranking")).toBeInTheDocument();
  });

  it("opens a page and shows its body", async () => {
    (api.getKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder",
      tags: [], timestamp: "2026-07-14T00:00:00Z", sources: [], body: "Reranking reorders results.",
    });
    renderAt();
    await screen.findByText("Reranking");
    fireEvent.click(screen.getByText("Reranking"));
    expect(await screen.findByText("Reranking reorders results.")).toBeInTheDocument();
  });

  it("editing a page calls editKbPage with the draft description and body", async () => {
    (api.getKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder",
      tags: [], timestamp: "2026-07-14T00:00:00Z", sources: [], body: "old body",
    });
    const edit = (api.editKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder - updated",
      tags: [], timestamp: "2026-07-14T00:00:00Z", sources: [], body: "new body",
    });
    renderAt();
    await screen.findByText("Reranking");
    fireEvent.click(screen.getByText("Reranking"));
    await screen.findByText("old body");
    fireEvent.click(screen.getByRole("button", { name: /^Edit$/i }));
    const bodyBox = screen.getByDisplayValue("old body");
    fireEvent.change(bodyBox, { target: { value: "new body" } });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => expect(edit).toHaveBeenCalledWith(3, "reranking",
      expect.objectContaining({ body: "new body" })));
  });

  it("shows an error message (not a blank page) when the initial load fails", async () => {
    (api.getKb as any).mockRejectedValue(new Error("kb not found"));
    renderAt();
    expect(await screen.findByText("kb not found")).toBeInTheDocument();
  });

  it("adding a page calls addKbPage with the typed fields", async () => {
    const add = (api.addKbPage as any).mockResolvedValue({
      type: "concept", title: "New idea", slug: "new-idea", description: "d",
      tags: [], timestamp: "2026-07-14T00:00:00Z", sources: [], body: "b",
    });
    renderAt();
    await screen.findByText("Reranking");
    fireEvent.click(screen.getByRole("button", { name: /Add page/i }));
    fireEvent.change(screen.getByPlaceholderText(/Title/i), { target: { value: "New idea" } });
    fireEvent.click(screen.getByRole("button", { name: /Save page/i }));
    await waitFor(() => expect(add).toHaveBeenCalledWith(3,
      expect.objectContaining({ title: "New idea" })));
  });

  it("shows tags/sources and edits them into a tag list", async () => {
    (api.getKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder",
      tags: ["ir", "ranking"], timestamp: "t", sources: ["doc:3"], body: "the body",
    });
    const edit = (api.editKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder",
      tags: ["ir", "ranking", "nlp"], timestamp: "t", sources: ["doc:3"], body: "the body",
    });
    renderAt();
    await screen.findByText("Reranking");
    fireEvent.click(screen.getByText("Reranking"));
    // read-mode surfaces the existing tags + sources
    expect(await screen.findByText("ir")).toBeInTheDocument();
    expect(screen.getByText("doc:3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Edit$/i }));
    const tagsBox = screen.getByDisplayValue("ir, ranking");
    fireEvent.change(tagsBox, { target: { value: "ir, ranking, nlp" } });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    await waitFor(() => expect(edit).toHaveBeenCalledWith(3, "reranking",
      expect.objectContaining({ tags: ["ir", "ranking", "nlp"] })));
  });

  it("moving a page calls moveKbPage with the chosen KB and type", async () => {
    (api.getKbPage as any).mockResolvedValue({
      type: "concept", title: "Reranking", slug: "reranking", description: "reorder",
      tags: [], timestamp: "t", sources: [], body: "the body",
    });
    const move = (api.moveKbPage as any).mockResolvedValue({
      type: "summary", title: "Reranking", slug: "reranking", description: "reorder",
      tags: [], timestamp: "t", sources: [], body: "the body",
    });
    renderAt();
    await screen.findByText("Reranking");
    fireEvent.click(screen.getByText("Reranking"));
    await screen.findByText("the body");
    fireEvent.click(screen.getByRole("button", { name: /^Move$/i }));
    fireEvent.change(await screen.findByLabelText("Target knowledge base"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("Target type"), { target: { value: "summary" } });
    fireEvent.click(screen.getByRole("button", { name: /^Move$/i }));
    await waitFor(() => expect(move).toHaveBeenCalledWith(3, "reranking",
      { dest_kb_id: 9, type: "summary" }));
  });
});
