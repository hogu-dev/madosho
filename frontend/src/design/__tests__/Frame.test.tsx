import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { Sidebar, NavItem, Breadcrumbs, BackLink } from "../Frame";

// Sidebar now calls useAuth to conditionally render the admin-only Users nav item.
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ scope: "admin" }) }));

// Sidebar polls a running-jobs count for the Jobs badge; mock it so the test
// stays off the network and can drive the badge value.
const jobsMock = vi.hoisted(() => ({ count: 0 }));
vi.mock("../../hooks/useRunningJobsCount", () => ({ useRunningJobsCount: () => jobsMock.count }));
beforeEach(() => { jobsMock.count = 0; });

function at(path: string, node: ReactNode) {
  return render(<MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>);
}

test("Sidebar shows the wordmark and the grouped destinations", () => {
  at("/documents", <Sidebar />);
  expect(screen.getByText("madosho")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /documents/i })).toHaveAttribute("href", "/documents");
  expect(screen.getByRole("link", { name: /scrying/i })).toHaveAttribute("href", "/scrying");
  expect(screen.getByRole("link", { name: /settings/i })).toHaveAttribute("href", "/settings");
});

test("the active destination is marked, others are not", () => {
  at("/documents/42", <Sidebar />);
  // a document detail keeps Documents active (prefix match)
  expect(screen.getByRole("link", { name: /documents/i })).toHaveAttribute("data-active", "true");
  expect(screen.getByRole("link", { name: /corpora/i })).toHaveAttribute("data-active", "false");
});

test("root path activates Documents", () => {
  at("/", <Sidebar />);
  expect(screen.getByRole("link", { name: /documents/i })).toHaveAttribute("data-active", "true");
});

test("Jobs nav item shows a live count badge while builds run, and none when idle", () => {
  jobsMock.count = 3;
  at("/documents", <Sidebar />);
  const jobs = screen.getByRole("link", { name: /jobs/i });
  expect(jobs).toHaveAttribute("href", "/jobs");
  expect(jobs).toHaveTextContent("3");
});

test("Jobs nav item has no badge when nothing is building", () => {
  jobsMock.count = 0;
  at("/documents", <Sidebar />);
  // the only digits in the sidebar would be a badge; none expected at idle
  expect(screen.getByRole("link", { name: /^jobs$/i })).toBeInTheDocument();
});

test("NavItem renders an optional badge", () => {
  at("/x", <NavItem to="/documents" label="Documents" active={false} badge={7} />);
  expect(screen.getByText("7")).toBeInTheDocument();
});

test("Breadcrumbs links the non-final items and leaves the last as text", () => {
  at("/", <Breadcrumbs items={[{ label: "Documents", to: "/documents" }, { label: "report.pdf" }]} />);
  expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute("href", "/documents");
  expect(screen.getByText("report.pdf")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "report.pdf" })).toBeNull();
});

test("BackLink points where told", () => {
  at("/", <BackLink to="/documents/42">Back to document</BackLink>);
  expect(screen.getByRole("link", { name: /back to document/i })).toHaveAttribute("href", "/documents/42");
});
