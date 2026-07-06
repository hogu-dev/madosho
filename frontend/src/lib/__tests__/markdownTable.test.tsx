// frontend/src/lib/__tests__/markdownTable.test.tsx
import { render, screen } from "@testing-library/react";
import { RenderedText } from "../markdownTable";

test("draws a markdown pipe table as a real grid", () => {
  const md = "Intro line\n\n| Term | Value |\n| --- | --- |\n| Notice | 90 days |\n| Payment | 30 days |";
  render(<RenderedText text={md} />);
  const table = screen.getByRole("table");
  expect(table).toBeInTheDocument();
  // header cells
  expect(screen.getByRole("columnheader", { name: "Term" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Value" })).toBeInTheDocument();
  // body cells
  expect(screen.getByRole("cell", { name: "90 days" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "30 days" })).toBeInTheDocument();
  // surrounding prose still rendered as text
  expect(screen.getByText(/Intro line/)).toBeInTheDocument();
});

test("renders plain text with no table as no grid", () => {
  render(<RenderedText text={"just some prose\nwith two lines"} />);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByText(/just some prose/)).toBeInTheDocument();
});
