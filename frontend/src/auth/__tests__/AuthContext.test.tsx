import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach, test, expect } from "vitest";
import { AuthProvider, useAuth } from "../AuthContext";

vi.mock("../../api/client", () => ({
  api: { me: vi.fn(), login: vi.fn(), loginPassword: vi.fn(), logout: vi.fn() },
  setUnauthorizedHandler: vi.fn(),
}));
import { api } from "../../api/client";

function Probe() {
  const { status, canWrite } = useAuth();
  return <div>status:{status} canWrite:{String(canWrite)}</div>;
}

beforeEach(() => vi.clearAllMocks());

test("auth not required -> opens, write allowed", async () => {
  (api.me as any).mockResolvedValue({ authenticated: false, auth_required: false, scope: null, name: null });
  render(<AuthProvider><Probe /></AuthProvider>);
  await screen.findByText("status:open canWrite:true");
});

test("me() error -> opens (back-compat, server still enforces)", async () => {
  (api.me as any).mockRejectedValue(new Error("network"));
  render(<AuthProvider><Probe /></AuthProvider>);
  await screen.findByText("status:open canWrite:true");
});

test("auth required, anonymous -> locked", async () => {
  (api.me as any).mockResolvedValue({ authenticated: false, auth_required: true, scope: null, name: null });
  render(<AuthProvider><Probe /></AuthProvider>);
  await screen.findByText(/status:locked/);
});

test("read scope -> open but canWrite false", async () => {
  (api.me as any).mockResolvedValue({ authenticated: true, auth_required: true, scope: "read", name: "r" });
  render(<AuthProvider><Probe /></AuthProvider>);
  await screen.findByText("status:open canWrite:false");
});

test("login submits the key then re-checks me", async () => {
  (api.me as any)
    .mockResolvedValueOnce({ authenticated: false, auth_required: true, scope: null, name: null })
    .mockResolvedValue({ authenticated: true, auth_required: true, scope: "write", name: "w" });
  (api.login as any).mockResolvedValue({ scope: "write", name: "w" });
  const { Login } = await import("../Login");
  render(<AuthProvider><Login /></AuthProvider>);
  await userEvent.click(screen.getByText(/use an api key/i));
  await userEvent.type(screen.getByLabelText(/api key/i), "mdsh_x");
  await userEvent.click(screen.getByRole("button", { name: /unlock/i }));
  await waitFor(() => expect(api.login).toHaveBeenCalledWith("mdsh_x"));
});

test("loginPassword submits credentials then re-checks me", async () => {
  (api.me as any)
    .mockResolvedValueOnce({ authenticated: false, auth_required: true, scope: null, name: null, kind: null })
    .mockResolvedValue({ authenticated: true, auth_required: true, scope: "admin", name: "root", kind: "user" });
  (api.loginPassword as any).mockResolvedValue({ scope: "admin", name: "root", kind: "user" });

  function LoginPasswordButton() {
    const { loginPassword } = useAuth();
    return (
      <button onClick={() => loginPassword("root", "pw")}>Login with Password</button>
    );
  }

  render(<AuthProvider><LoginPasswordButton /></AuthProvider>);
  await userEvent.click(screen.getByRole("button", { name: /login with password/i }));
  await waitFor(() => expect(api.loginPassword).toHaveBeenCalledWith("root", "pw"));
});
