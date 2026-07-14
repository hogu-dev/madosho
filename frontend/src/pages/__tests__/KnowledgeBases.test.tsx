import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { KnowledgeBases } from "../KnowledgeBases";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { listKbs: vi.fn(), createKb: vi.fn(), listCorpora: vi.fn() },
}));
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

beforeEach(() => {
  vi.restoreAllMocks();
  (api.listCorpora as any).mockResolvedValue([{ id: 1, name: "c1", config: {} }]);
  (api.listKbs as any).mockResolvedValue([
    { id: 3, name: "Notes", slug: "notes", corpus_id: 1, corpus_name: "c1" },
  ]);
});

const renderPage = () => render(<MemoryRouter><KnowledgeBases /></MemoryRouter>);

describe("KnowledgeBases", () => {
  it("lists KBs grouped by corpus", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Notes")).toBeInTheDocument());
    // "c1" appears both as the group header and as a <select> option, so allow either.
    expect(screen.getAllByText("c1").length).toBeGreaterThan(0);
  });

  it("shows an empty state when there are no knowledge bases", async () => {
    (api.listKbs as any).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/No knowledge bases yet/i)).toBeInTheDocument();
  });

  it("creating a KB calls createKb with the chosen corpus and typed name", async () => {
    (api.listKbs as any).mockResolvedValue([]);
    const create = (api.createKb as any).mockResolvedValue(
      { id: 9, name: "Wiki", slug: "wiki", corpus_id: 1, corpus_name: "c1" });
    renderPage();
    await screen.findByText(/No knowledge bases yet/i);
    fireEvent.change(screen.getByLabelText(/^Corpus$/i), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/New knowledge base name/i), { target: { value: "Wiki" } });
    fireEvent.click(screen.getByRole("button", { name: /Create KB/i }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(1, "Wiki"));
  });
});
