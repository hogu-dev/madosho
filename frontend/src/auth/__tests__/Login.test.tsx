import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Login } from "../Login";

const loginPassword = vi.fn().mockResolvedValue(undefined);
const login = vi.fn().mockResolvedValue(undefined);
vi.mock("../AuthContext", () => ({ useAuth: () => ({ login, loginPassword }) }));

describe("Login", () => {
  it("submits username and password by default", async () => {
    render(<Login />);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: "root" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(loginPassword).toHaveBeenCalledWith("root", "pw"));
  });

  it("can switch to API-key entry", async () => {
    render(<Login />);
    fireEvent.click(screen.getByText(/use an api key/i));
    fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "mdsh_x" } });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("mdsh_x"));
  });
});
