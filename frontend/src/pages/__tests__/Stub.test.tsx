import { render, screen } from "@testing-library/react";
import { Stub } from "../Stub";

test("Stub renders its surface title and the coming-soon note", () => {
  render(<Stub title="Quality" description="Scoreboard + eval" />);
  expect(screen.getByRole("heading", { name: "Quality" })).toBeInTheDocument();
  expect(screen.getByText("Scoreboard + eval")).toBeInTheDocument();
  expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
});
