// frontend/src/pages/__tests__/Settings.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi, beforeEach } from "vitest";
import { Settings } from "../Settings";
import { api } from "../../api/client";

// Settings now calls useAuth() for canWrite gating; mock it so tests run without a real provider.
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ canWrite: true }) }));

vi.mock("../../api/client", () => ({ api: {
  listLlmEndpoints: vi.fn(), createLlmEndpoint: vi.fn(),
  deleteLlmEndpoint: vi.fn(), setDefaultLlmEndpoint: vi.fn(),
  setVisionDefaultLlmEndpoint: vi.fn(),
}}));

beforeEach(() => vi.clearAllMocks());

it("lists endpoints with the default marked", async () => {
  (api.listLlmEndpoints as any).mockResolvedValue([
    { id: 1, name: "gemma4-local", provider: "openai", model: "gemma-4-e4b",
      api_base: "http://h:8081/v1", key_env_var: null, is_default: true, key_present: false,
      supports_text: true, supports_vision: false, is_vision_default: false,
      api_flavor: "chat" },
  ]);
  render(<Settings />);
  expect(await screen.findByText("gemma4-local")).toBeInTheDocument();
  expect(screen.getByText(/default/i)).toBeInTheDocument();
});

it("creates an endpoint from the form", async () => {
  (api.listLlmEndpoints as any).mockResolvedValue([]);
  (api.createLlmEndpoint as any).mockResolvedValue({ id: 2 });
  render(<Settings />);
  await waitFor(() => expect(api.listLlmEndpoints).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "qwen" } });
  fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: "openai" } });
  fireEvent.change(screen.getByLabelText(/^model/i), { target: { value: "qwen3-14b" } });
  fireEvent.change(screen.getByLabelText(/api base/i), { target: { value: "http://h:8081/v1" } });
  fireEvent.click(screen.getByRole("button", { name: /add endpoint/i }));
  await waitFor(() => expect(api.createLlmEndpoint).toHaveBeenCalledWith(
    expect.objectContaining({ name: "qwen", provider: "openai", model: "qwen3-14b",
      supports_text: true, supports_vision: false })));
});

it("shows a warning when no endpoint supports vision", async () => {
  vi.mocked(api.listLlmEndpoints).mockResolvedValue([
    { id: 1, name: "t", provider: "openai", model: "m", api_base: "u",
      key_env_var: null, is_default: true, key_present: false,
      supports_text: true, supports_vision: false, is_vision_default: false,
      api_flavor: "chat" },
  ]);
  render(<Settings />);
  expect(await screen.findByText(/no vision endpoint/i)).toBeInTheDocument();
});

it("sends the selected api_flavor and defaults to chat", async () => {
  (api.listLlmEndpoints as any).mockResolvedValue([]);
  (api.createLlmEndpoint as any).mockResolvedValue({ id: 3 });
  render(<Settings />);
  await waitFor(() => expect(api.listLlmEndpoints).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "relay-endpoint" } });
  fireEvent.change(screen.getByLabelText(/^model/i), { target: { value: "gpt-5" } });
  fireEvent.change(screen.getByLabelText(/api base/i), { target: { value: "http://p:10531/v1" } });
  fireEvent.change(screen.getByLabelText(/api flavor/i), { target: { value: "responses" } });
  fireEvent.click(screen.getByRole("button", { name: /add endpoint/i }));
  await waitFor(() => expect(api.createLlmEndpoint).toHaveBeenCalledWith(
    expect.objectContaining({ name: "relay-endpoint", api_flavor: "responses" })));
});

it("shows a responses API chip on responses-flavor endpoints", async () => {
  vi.mocked(api.listLlmEndpoints).mockResolvedValue([
    { id: 4, name: "relay-endpoint", provider: "openai", model: "gpt-5", api_base: "u",
      key_env_var: null, is_default: true, key_present: false,
      supports_text: true, supports_vision: true, is_vision_default: true,
      api_flavor: "responses" },
  ]);
  render(<Settings />);
  expect(await screen.findByText(/responses API/i)).toBeInTheDocument();
});

it("calls setVisionDefaultLlmEndpoint when Make vision default is clicked", async () => {
  vi.mocked(api.listLlmEndpoints).mockResolvedValue([
    { id: 2, name: "v", provider: "openai", model: "gemma-4-e4b", api_base: "u",
      key_env_var: null, is_default: true, key_present: false,
      supports_text: true, supports_vision: true, is_vision_default: false,
      api_flavor: "chat" },
  ]);
  vi.mocked(api.setVisionDefaultLlmEndpoint).mockResolvedValue({} as never);
  render(<Settings />);
  const btn = await screen.findByRole("button", { name: /make vision default/i });
  await userEvent.click(btn);
  expect(api.setVisionDefaultLlmEndpoint).toHaveBeenCalledWith(2);
});
