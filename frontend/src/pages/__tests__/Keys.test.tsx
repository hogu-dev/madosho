// frontend/src/pages/__tests__/Keys.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { it, expect, vi, beforeEach } from "vitest";
import { Keys } from "../Keys";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";

vi.mock("../../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  api: {
    listKeys: vi.fn(),
    createKey: vi.fn(),
    revokeKey: vi.fn(),
  },
}));

const mockLogin = vi.fn();
const mockLogout = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  (api.listKeys as any).mockResolvedValue([]);
  (api.revokeKey as any).mockResolvedValue(undefined);
  (api.createKey as any).mockResolvedValue({
    name: "ci", prefix: "mdsh_bbbb", scope: "write", key: "mdsh_bbbbSECRET",
  });
});

it("admin sees the key list", async () => {
  vi.mocked(useAuth).mockReturnValue({ scope: "admin", login: mockLogin, logout: mockLogout } as any);
  (api.listKeys as any).mockResolvedValue([
    { name: "root", prefix: "mdsh_aaaa", scope: "admin",
      created_at: null, last_used_at: null, revoked_at: null },
  ]);
  render(<Keys />);
  expect(await screen.findByText("root")).toBeInTheDocument();
});

it("mint shows the one-time reveal and dismiss clears it", async () => {
  vi.mocked(useAuth).mockReturnValue({ scope: "admin", login: mockLogin, logout: mockLogout } as any);
  render(<Keys />);
  await waitFor(() => expect(api.listKeys).toHaveBeenCalled());

  // Fill the mint form and submit
  fireEvent.change(screen.getByLabelText(/key name/i), { target: { value: "ci" } });
  fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

  // Secret must appear in the one-time callout
  expect(await screen.findByText("mdsh_bbbbSECRET")).toBeInTheDocument();

  // Secret must NOT be in any list row (rows show prefix only, never the full key)
  const listItems = screen.queryAllByRole("listitem");
  for (const item of listItems) {
    expect(item.textContent).not.toContain("mdsh_bbbbSECRET");
  }

  // Dismiss clears the callout
  fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
  expect(screen.queryByText("mdsh_bbbbSECRET")).not.toBeInTheDocument();
});

it("non-admin scope shows cannot-manage-keys and hides the mint form", () => {
  vi.mocked(useAuth).mockReturnValue({ scope: "write", login: mockLogin, logout: mockLogout } as any);
  render(<Keys />);
  expect(screen.getByText(/cannot manage keys/i)).toBeInTheDocument();
  expect(screen.queryByLabelText(/key name/i)).not.toBeInTheDocument();
});

it("revoke calls the client and refreshes the list", async () => {
  vi.mocked(useAuth).mockReturnValue({ scope: "admin", login: mockLogin, logout: mockLogout } as any);
  (api.listKeys as any).mockResolvedValue([
    { name: "ci", prefix: "mdsh_bbbb", scope: "write",
      created_at: null, last_used_at: null, revoked_at: null },
  ]);
  render(<Keys />);

  const revokeBtn = await screen.findByRole("button", { name: /revoke/i });
  fireEvent.click(revokeBtn);

  await waitFor(() => expect(api.revokeKey).toHaveBeenCalledWith("ci"));
  await waitFor(() => expect(api.listKeys).toHaveBeenCalledTimes(2));
});
