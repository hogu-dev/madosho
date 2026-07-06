import { render, screen, fireEvent } from "@testing-library/react";
import { Modal } from "../Modal";

test("renders nothing when closed", () => {
  render(<Modal open={false} onClose={() => {}}><button>Inside</button></Modal>);
  expect(screen.queryByText("Inside")).not.toBeInTheDocument();
});

test("renders children and a dialog role when open", () => {
  render(<Modal open onClose={() => {}}><button>Inside</button></Modal>);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText("Inside")).toBeInTheDocument();
});

test("Escape calls onClose", () => {
  const onClose = vi.fn();
  render(<Modal open onClose={onClose}><button>Inside</button></Modal>);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("clicking the backdrop closes, clicking the panel does not", () => {
  const onClose = vi.fn();
  render(<Modal open onClose={onClose}><button>Inside</button></Modal>);
  fireEvent.click(screen.getByText("Inside"));   // inside the panel
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("modal-backdrop"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("moves focus into the dialog on open", () => {
  render(<Modal open onClose={() => {}}><button>Inside</button></Modal>);
  expect(screen.getByText("Inside")).toHaveFocus();
});
