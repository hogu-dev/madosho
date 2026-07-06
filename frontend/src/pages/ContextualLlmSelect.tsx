import type { LlmEndpoint } from "../api/types";

// Shown only when the chunker is "contextual": that chunker situates each chunk
// with an LLM call, so the user picks WHICH configured endpoint to use. The
// selection is stored as the chunker's `llm_endpoint` option; leaving it on the
// default means the build uses the registry's default index-time LLM. Renders
// nothing when no endpoints exist (recipeErrors already flags that case).
export function ContextualLlmSelect(
  { endpoints, value, onChange }:
  { endpoints: LlmEndpoint[]; value: string | null; onChange: (name: string) => void },
) {
  if (endpoints.length === 0) return null;
  const def = endpoints.find((e) => e.is_default)?.name ?? endpoints[0].name;
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
        textTransform: "uppercase", color: "var(--ink-faint)" }}>LLM</span>
      <select aria-label="Contextual LLM" value={value ?? def}
        onChange={(e) => onChange(e.target.value)}>
        {endpoints.map((e) => (
          <option key={e.id} value={e.name}>{e.name}{e.is_default ? " (default)" : ""}</option>
        ))}
      </select>
    </label>
  );
}
