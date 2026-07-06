import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { NotFound } from "../NotFound";

test("404 offers a way back to Documents and Scrying", () => {
  render(<MemoryRouter><NotFound /></MemoryRouter>);
  expect(screen.getByText("404")).toBeInTheDocument();
  expect(screen.getByText(/slipped from the archive/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /return to documents/i })).toHaveAttribute("href", "/documents");
  expect(screen.getByRole("link", { name: /open scrying/i })).toHaveAttribute("href", "/scrying");
});
