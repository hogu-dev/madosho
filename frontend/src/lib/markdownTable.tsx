// frontend/src/lib/markdownTable.tsx
// Renders extraction text with GitHub-style markdown tables (what docling's
// export_to_markdown emits) drawn as real grids; everything else stays as
// pre-wrap text. Deliberately tiny and dependency-free -- it targets exactly the
// pipe-table shape docling produces, not full markdown. Used by the head-to-head's
// "Rendered" view, where char-level diffs are off (offsets don't map post-render).
import type { ReactNode, CSSProperties } from "react";

const ROW = /^\s*\|(.+)\|\s*$/;             // a pipe-delimited row: | a | b |
const hairline = "1px solid rgba(120,95,40,0.18)";

function splitCells(line: string): string[] {
  const m = line.match(ROW);
  return (m ? m[1] : line).split("|").map((c) => c.trim());
}

// Separator row under the header: every cell is dashes with optional colons (:---:).
function isSep(line: string): boolean {
  if (!ROW.test(line)) return false;
  return splitCells(line).every((c) => /^:?-{1,}:?$/.test(c.replace(/\s/g, "")));
}

const tableStyle: CSSProperties = {
  borderCollapse: "collapse", margin: "6px 0", fontSize: 12, fontFamily: "var(--font-mono)",
};
const cell: CSSProperties = { border: hairline, padding: "5px 9px", textAlign: "left", verticalAlign: "top" };
const headCell: CSSProperties = { ...cell, background: "rgba(156,121,32,0.08)", fontWeight: 600 };

export function RenderedText({ text }: { text: string }): ReactNode {
  const lines = (text || "").split("\n");
  const out: ReactNode[] = [];
  let prose: string[] = [];
  const flushProse = (key: string) => {
    if (prose.length) {
      out.push(<div key={key} style={{ whiteSpace: "pre-wrap" }}>{prose.join("\n")}</div>);
      prose = [];
    }
  };

  let i = 0;
  while (i < lines.length) {
    // A table is a header row immediately followed by a separator row.
    if (ROW.test(lines[i]) && i + 1 < lines.length && isSep(lines[i + 1])) {
      flushProse(`p${i}`);
      const header = splitCells(lines[i]);
      i += 2;                                       // consume header + separator
      const body: string[][] = [];
      while (i < lines.length && ROW.test(lines[i]) && !isSep(lines[i])) {
        body.push(splitCells(lines[i]));
        i++;
      }
      out.push(
        <table key={`t${i}`} style={tableStyle}>
          <thead><tr>{header.map((h, j) => <th key={j} style={headCell}>{h}</th>)}</tr></thead>
          <tbody>
            {body.map((r, ri) => (
              <tr key={ri}>{r.map((c, ci) => <td key={ci} style={cell}>{c}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      );
    } else {
      prose.push(lines[i]);
      i++;
    }
  }
  flushProse("pEnd");
  return <>{out}</>;
}
