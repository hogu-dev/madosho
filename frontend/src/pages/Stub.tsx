import { Panel, Heading } from "../design/primitives";

export function Stub({ title, description }: { title: string; description?: string }) {
  return (
    <Panel>
      <Heading level={1}>{title}</Heading>
      {description && <p style={{ color: "var(--ink-muted)", marginTop: 0 }}>{description}</p>}
      <p style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
        Coming soon.
      </p>
    </Panel>
  );
}
