// frontend/src/pages/__tests__/Users.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Users } from "../Users";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({
  api: { listUsers: vi.fn(), createUser: vi.fn(), deactivateUser: vi.fn(), resetUserPassword: vi.fn() },
}));
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ scope: "admin" }) }));

beforeEach(() => {
  (api.listUsers as any).mockResolvedValue([
    { id: 1, username: "root", scope: "admin", is_active: true, created_at: null, last_login_at: null },
  ]);
  (api.createUser as any).mockResolvedValue({ id: 2, username: "alice", scope: "write", is_active: true, created_at: null, last_login_at: null });
});

describe("Users", () => {
  it("lists existing users", async () => {
    render(<Users />);
    expect(await screen.findByText("root")).toBeInTheDocument();
  });

  it("creates a user", async () => {
    render(<Users />);
    await screen.findByText("root");
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));
    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith("alice", "write", "pw"));
  });
});
