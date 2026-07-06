import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../router";

// Shell now renders ReadOnlyBanner (and gated pages call useAuth); mock so tests run without a provider.
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true, authRequired: false }) }));

function childPaths() {
  return routes[0].children!.map((c: any) => c.path);
}

test("registers the document-centric surfaces", () => {
  const paths = childPaths();
  for (const p of [
    "documents", "documents/:documentId",
    // corpora list + the document-centric corpus detail page (members + per-doc pipeline pick)
    "corpora", "corpora/:corpusId",
    // compare is now a single standalone surface (the in-doc /documents/:id/compare
    // route was folded into it; the Workbench link deep-links via /compare?document=)
    "scrying", "compare", "quality", "quality/eval/:runId",
    "research", "research/:runId", "settings", "*",
  ]) expect(paths).toContain(p);
});

test("the old in-document compare route was folded into the standalone Compare page", () => {
  expect(childPaths()).not.toContain("documents/:documentId/compare");
});

test("the old corpus-centric routes are gone", () => {
  const paths = childPaths();
  // The corpus detail page is back as a document-centric view, but the old
  // corpus-as-the-unit routes (its own recipe/config, the playground) stay gone.
  expect(paths).not.toContain("corpora/:corpusId/config");
  expect(paths).not.toContain("playground");
});

test("/ redirects to the Documents home", async () => {
  const router = createMemoryRouter(routes, { initialEntries: ["/"] });
  render(<RouterProvider router={router} />);
  expect(await screen.findByRole("heading", { name: /documents/i })).toBeInTheDocument();
});

test("an unknown path renders the 404 inside the shell", () => {
  const router = createMemoryRouter(routes, { initialEntries: ["/nope"] });
  render(<RouterProvider router={router} />);
  expect(screen.getByText("404")).toBeInTheDocument();
  expect(screen.getByText("madosho")).toBeInTheDocument(); // still framed by the shell
});
