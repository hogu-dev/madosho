import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Alchemy } from "../Alchemy";
import { api } from "../../api/client";

let canWrite = true;
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite }) }));

const GOALS = [
  { id: 3, name: "sota-watch", corpus_id: 1, goal_type: "living-research",
    spec: { prompt: "track the state of the art" }, coverage: "full",
    include_generated: false, created_at: "2026-07-01T10:00:00Z" },
  { id: 2, name: "contract-brief", corpus_id: 2, goal_type: "report",
    spec: {}, coverage: "search", include_generated: true, created_at: null },
];

const CORPORA = [
  { id: 1, name: "aerospace", config: {} },
  { id: 2, name: "contracts", config: {} },
];

beforeEach(() => {
  vi.restoreAllMocks();
  canWrite = true;
  vi.spyOn(api, "listCorpora").mockResolvedValue(CORPORA as any);
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/alchemy"]}>
      <Routes>
        <Route path="/alchemy" element={<Alchemy />} />
        <Route path="/alchemy/:goalRef" element={<div>goal detail page</div>} />
      </Routes>
    </MemoryRouter>);
}

test("lists goals with name, type pill, corpus and coverage", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue(GOALS as any);
  renderPage();
  expect(await screen.findByText("sota-watch")).toBeInTheDocument();
  expect(screen.getByText("contract-brief")).toBeInTheDocument();
  expect(screen.getByText("living-research")).toBeInTheDocument();
  expect(screen.getByText("report")).toBeInTheDocument();
  expect(screen.getByText("full")).toBeInTheDocument();
  expect(screen.getByText("#2")).toBeInTheDocument();   // corpus id column
});

test("rows link to the goal detail by numeric id", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue(GOALS as any);
  renderPage();
  const name = await screen.findByText("sota-watch");
  expect(name.closest("a")).toHaveAttribute("href", "/alchemy/3");
});

test("empty state points at the create form when the user can write", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue([]);
  renderPage();
  expect(await screen.findByText("No alchemy goals yet")).toBeInTheDocument();
  expect(screen.getByText(/form above/)).toBeInTheDocument();
});

test("load failure surfaces the error", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockRejectedValue(new Error("500: boom"));
  renderPage();
  expect(await screen.findByText(/boom/)).toBeInTheDocument();
});

test("create form posts a living-research goal and navigates to it", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue([]);
  const create = vi.spyOn(api, "createAlchemyGoal")
    .mockResolvedValue({ id: 9 } as any);
  renderPage();
  await screen.findByText("New goal");
  await waitFor(() => expect((screen.getByLabelText("Corpus") as HTMLSelectElement).value).toBe("1"));

  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Name"), "energy-brief");
  await user.type(screen.getByLabelText("Goal"), "Summarize energy storage from the corpus.");
  await user.click(screen.getByRole("button", { name: /create goal/i }));

  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0][0]).toEqual({
    name: "energy-brief",
    corpus_id: 1,
    goal_type: "living-research",
    spec: { goal: "Summarize energy storage from the corpus." },
    coverage: "search",
  });
  expect(await screen.findByText("goal detail page")).toBeInTheDocument();
});

test("report type requires a template before create is enabled", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue([]);
  renderPage();
  await screen.findByText("New goal");
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Name"), "brief");
  await user.click(screen.getByRole("button", { name: /report/i }));

  // no template yet -> create disabled
  expect(screen.getByRole("button", { name: /create goal/i })).toBeDisabled();
  await user.type(screen.getByLabelText("Template"), "## Section one");
  expect(screen.getByRole("button", { name: /create goal/i })).toBeEnabled();
});

test("read-only users see no create form, and the empty state points to the CLI", async () => {
  canWrite = false;
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue([]);
  renderPage();
  expect(await screen.findByText("No alchemy goals yet")).toBeInTheDocument();
  expect(screen.queryByText("New goal")).not.toBeInTheDocument();
  expect(screen.getByText(/madosho alchemy create/)).toBeInTheDocument();
});
