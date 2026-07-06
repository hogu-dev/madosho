import type { LlmEndpoint } from "../api/types";

// Shown only when the parser is "vision": that parser transcribes each page image
// with a vision LLM, so the user picks WHICH configured vision-capable endpoint to
// use. The selection is stored as the parser's `vision_endpoint` option; leaving it
// on the default means the build uses the registry's vision-default endpoint. Only
// vision-capable endpoints are offered. Renders nothing when none exist
// (recipeErrors already flags that case).
export function VisionLlmSelect(
  { endpoints, value, onChange }:
  { endpoints: LlmEndpoint[]; value: string | null; onChange: (name: string) => void },
) {
  const vision = endpoints.filter((e) => e.supports_vision);
  if (vision.length === 0) return null;
  const def = vision.find((e) => e.is_vision_default)?.name ?? vision[0].name;
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
        textTransform: "uppercase", color: "var(--ink-faint)" }}>Vision LLM</span>
      <select aria-label="Vision LLM" value={value ?? def}
        onChange={(e) => onChange(e.target.value)}>
        {vision.map((e) => (
          <option key={e.id} value={e.name}>{e.name}{e.is_vision_default ? " (default)" : ""}</option>
        ))}
      </select>
    </label>
  );
}
