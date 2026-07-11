import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Alchemy } from "../Alchemy";
import { api } from "../../api/client";

const GOALS = [
  { id: 3, name: "sota-watch", corpus_id: 1, goal_type: "living-research",
    spec: { prompt: "track the state of the art" }, coverage: "full",
    include_generated: false, created_at: "2026-07-01T10:00:00Z" },
  { id: 2, name: "contract-brief", corpus_id: 2, goal_type: "report",
    spec: {}, coverage: "search", include_generated: true, created_at: null },
];

beforeEach(() => { vi.restoreAllMocks(); });

function renderPage() {
  return render(<MemoryRouter initialEntries={["/alchemy"]}><Alchemy /></MemoryRouter>);
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

test("empty state explains goals are created via the CLI", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockResolvedValue([]);
  renderPage();
  expect(await screen.findByText("No alchemy goals yet")).toBeInTheDocument();
  expect(screen.getByText(/madosho alchemy create/)).toBeInTheDocument();
});

test("load failure surfaces the error", async () => {
  vi.spyOn(api, "listAlchemyGoals").mockRejectedValue(new Error("500: boom"));
  renderPage();
  expect(await screen.findByText(/boom/)).toBeInTheDocument();
});
