import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { KbDetail } from "../KbDetail";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { getKb: vi.fn(), getKbPage: vi.fn(), addKbPage: vi.fn(), editKbPage: vi.fn() },
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
});
