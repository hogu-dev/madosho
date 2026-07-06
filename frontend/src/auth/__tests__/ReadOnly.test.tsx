import { render, screen } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { ReadOnlyBanner } from "../ReadOnlyBanner";

vi.mock("../AuthContext", () => ({ useAuth: vi.fn() }));
import { useAuth } from "../AuthContext";

test("banner shows for a read-only session", () => {
  (useAuth as any).mockReturnValue({ authRequired: true, canWrite: false });
  render(<ReadOnlyBanner />);
  expect(screen.getByText(/read-only/i)).toBeInTheDocument();
});

test("no banner when writes are allowed", () => {
  (useAuth as any).mockReturnValue({ authRequired: true, canWrite: true });
  const { container } = render(<ReadOnlyBanner />);
  expect(container).toBeEmptyDOMElement();
});

test("no banner when auth is not required", () => {
  (useAuth as any).mockReturnValue({ authRequired: false, canWrite: true });
  const { container } = render(<ReadOnlyBanner />);
  expect(container).toBeEmptyDOMElement();
});
