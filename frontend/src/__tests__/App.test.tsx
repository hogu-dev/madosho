import { render, screen } from "@testing-library/react";
import App from "../App";

// App now wraps in AuthProvider which calls api.me() on mount.
// Mock the client so me() resolves synchronously to auth-not-required,
// meaning the gate falls open and the router/shell render without a real backend.
vi.mock("../api/client", () => ({
  api: {
    me: vi.fn().mockResolvedValue({ authenticated: false, auth_required: false, scope: null, name: null }),
    login: vi.fn(),
    logout: vi.fn(),
  },
  setUnauthorizedHandler: vi.fn(),
}));

test("App boots, frames the wordmark, and lands on Documents", async () => {
  render(<App />);
  // findByText waits for the auth gate to resolve open, then the Shell mounts
  expect(await screen.findByText("madosho")).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: /documents/i })).toBeInTheDocument();
});
