import { render, screen, fireEvent } from "@testing-library/react";
import { ConfirmDialog } from "../ConfirmDialog";

test("renders the title and body and fires onConfirm", () => {
  const onConfirm = vi.fn();
  render(<ConfirmDialog open title="Delete this?" confirmLabel="Delete" danger
    onConfirm={onConfirm} onClose={() => {}}>body text</ConfirmDialog>);
  expect(screen.getByText("Delete this?")).toBeInTheDocument();
  expect(screen.getByText("body text")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

test("Cancel fires onClose, not onConfirm", () => {
  const onConfirm = vi.fn(), onClose = vi.fn();
  render(<ConfirmDialog open title="Delete this?" onConfirm={onConfirm} onClose={onClose} />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onConfirm).not.toHaveBeenCalled();
});

test("busy disables both buttons so a slow action can't double-fire", () => {
  const onConfirm = vi.fn();
  render(<ConfirmDialog open title="Delete this?" confirmLabel="Delete" busy
    onConfirm={onConfirm} onClose={() => {}} />);
  const confirm = screen.getByRole("button", { name: /Working/i });
  expect(confirm).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  fireEvent.click(confirm);
  expect(onConfirm).not.toHaveBeenCalled();
});

test("renders nothing when closed", () => {
  render(<ConfirmDialog open={false} title="Delete this?" onConfirm={() => {}} onClose={() => {}} />);
  expect(screen.queryByText("Delete this?")).not.toBeInTheDocument();
});
