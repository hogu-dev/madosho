import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Corpora } from "../Corpora";
import { api } from "../../api/client";

vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

beforeEach(() => { vi.restoreAllMocks(); });
const renderPage = () => render(<MemoryRouter><Corpora /></MemoryRouter>);

test("renders the heading and empty state", async () => {
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  renderPage();
  expect(screen.getByRole("heading", { name: "Corpora" })).toBeInTheDocument();
  expect(await screen.findByText(/No corpora yet/i)).toBeInTheDocument();
});

test("lists corpora and links each to its detail page", async () => {
  vi.spyOn(api, "listCorpora").mockResolvedValue(
    [{ id: 7, name: "aerospace", config: {} }, { id: 9, name: "propulsion", config: {} }] as any);
  renderPage();
  await screen.findByText("aerospace");
  expect(screen.getAllByText("Open →")[0].closest("a")).toHaveAttribute("href", "/corpora/7");
});

test("expanding a corpus lazy-loads and lists its documents", async () => {
  vi.spyOn(api, "listCorpora").mockResolvedValue([{ id: 7, name: "aerospace", config: {} }] as any);
  const members = vi.spyOn(api, "listCorpusMembers").mockResolvedValue(
    [{ document_id: 5, filename: "f35.pdf", status: "indexed", selected_pipeline_ids: [], pipelines: [] }] as any);
  renderPage();
  // collapsed by default: members not fetched, document not shown
  await screen.findByText("aerospace");
  expect(members).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/Expand aerospace/i));
  expect(await screen.findByText("f35.pdf")).toBeInTheDocument();
  expect(members).toHaveBeenCalledWith(7);
});

test("creating a corpus calls createCorpus with the typed name", async () => {
  vi.spyOn(api, "listCorpora").mockResolvedValue([] as any);
  const create = vi.spyOn(api, "createCorpus").mockResolvedValue({ id: 1, name: "x", config: {} } as any);
  renderPage();
  fireEvent.change(screen.getByLabelText(/New corpus name/i), { target: { value: "aerospace" } });
  fireEvent.click(screen.getByRole("button", { name: /Create corpus/i }));
  await waitFor(() => expect(create).toHaveBeenCalledWith("aerospace"));
});
