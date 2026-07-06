import { render, screen, fireEvent } from "@testing-library/react";
import { Heading, Button, Panel, Card, EmptyState } from "../primitives";
import { SegmentedToggle, RelevanceBar, CodeBlock } from "../primitives";

test("Heading renders the requested level in the serif face", () => {
  render(<Heading level={2}>Documents</Heading>);
  const h = screen.getByRole("heading", { level: 2, name: "Documents" });
  expect(h).toBeInTheDocument();
});

test("Button defaults to the primary variant and is a button", () => {
  render(<Button>Cast</Button>);
  const b = screen.getByRole("button", { name: "Cast" });
  expect(b).toHaveAttribute("data-variant", "primary");
  expect(b).toHaveAttribute("type", "button");
});

test("Button ghost variant and disabled state", () => {
  const onClick = vi.fn();
  render(<Button variant="ghost" disabled onClick={onClick}>Cancel</Button>);
  const b = screen.getByRole("button", { name: "Cancel" });
  expect(b).toHaveAttribute("data-variant", "ghost");
  expect(b).toBeDisabled();
});

test("Panel and Card render their children", () => {
  render(<Panel><Card>inside</Card></Panel>);
  expect(screen.getByText("inside")).toBeInTheDocument();
});

test("EmptyState shows the title and the optional hint", () => {
  render(<EmptyState title="Your library is empty" hint="Upload a PDF" />);
  expect(screen.getByText("Your library is empty")).toBeInTheDocument();
  expect(screen.getByText("Upload a PDF")).toBeInTheDocument();
});

import { StatusDot, MeterBar } from "../primitives";

test("StatusDot shows the label and colors itself by status", () => {
  render(<StatusDot status="indexed" label="indexed" />);
  expect(screen.getByText("indexed")).toBeInTheDocument();
});

test("StatusDot falls back to the status string when no label given", () => {
  render(<StatusDot status="failed" />);
  expect(screen.getByText("failed")).toBeInTheDocument();
});

test("MeterBar renders the value over max", () => {
  render(<MeterBar value={11} max={15} />);
  expect(screen.getByText("11")).toBeInTheDocument();
  expect(screen.getByText("/15")).toBeInTheDocument();
});

import { SegmentScore } from "../primitives";

test("SegmentScore shows the numeric value", () => {
  render(<SegmentScore value={4} />);
  expect(screen.getByText("4")).toBeInTheDocument();
});

test("SegmentScore renders `max` segments", () => {
  render(<SegmentScore value={3} max={5} />);
  expect(screen.getByTestId("segments").children).toHaveLength(5);
});

// Regression: fractional values — label uses one decimal, fill rounds to nearest integer.
// value=3.2: OLD fill logic (i < 3.2) lights 4 segments; NEW (i < Math.round(3.2)=3) lights 3.
// This test is RED under old code (expects 3 lit, old gives 4) and GREEN under new code.
test("SegmentScore value=3.2 shows '3.2' label and rounds fill to 3 lit segments", () => {
  render(<SegmentScore value={3.2} max={5} />);
  expect(screen.getByText("3.2")).toBeInTheDocument();
  const segs = Array.from(screen.getByTestId("segments").children) as HTMLElement[];
  // jsdom normalizes rgba() to include spaces: "rgba(43, 33, 23, 0.14)"
  const muted = "rgba(43, 33, 23, 0.14)";
  const litCount = segs.filter((s) => s.style.background !== muted).length;
  const mutedCount = segs.filter((s) => s.style.background === muted).length;
  expect(litCount).toBe(3);
  expect(mutedCount).toBe(2);
});

test("SegmentedToggle marks the active option and fires onChange", () => {
  const onChange = vi.fn();
  render(<SegmentedToggle value="answer" onChange={onChange}
    options={[{ value: "answer", label: "Answer" }, { value: "retrieval", label: "Retrieval only" }]} />);
  const active = screen.getByRole("button", { name: "Answer" });
  expect(active).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Retrieval only" }));
  expect(onChange).toHaveBeenCalledWith("retrieval");
});

test("RelevanceBar shows the raw score and a relative-filled bar", () => {
  const { container } = render(<RelevanceBar value={6} max={12} />);
  expect(screen.getByText("6")).toBeInTheDocument();           // raw number shown
  const segs = container.querySelectorAll("[data-testid='rel-seg']");
  expect(segs).toHaveLength(5);
  // 6/12 -> round(2.5) -> 3 filled
  const filled = Array.from(segs).filter((s) => (s as HTMLElement).dataset.filled === "true");
  expect(filled).toHaveLength(3);
});

test("RelevanceBar with max<=0 renders the number and an empty bar", () => {
  const { container } = render(<RelevanceBar value={0} max={0} />);
  expect(screen.getByText("0")).toBeInTheDocument();
  const filled = container.querySelectorAll("[data-testid='rel-seg'][data-filled='true']");
  expect(filled).toHaveLength(0);
});

test("CodeBlock renders its children in a mono block", () => {
  render(<CodeBlock>system: hello</CodeBlock>);
  expect(screen.getByText("system: hello")).toBeInTheDocument();
});
