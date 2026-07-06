import type { Dispatch, ReactNode, SetStateAction } from "react";
import type { Components, LlmEndpoint } from "../api/types";
import { recipeErrors, componentLabel } from "../lib/recipe";
import { ContextualLlmSelect } from "./ContextualLlmSelect";
import { VisionLlmSelect } from "./VisionLlmSelect";

// The three indexing slots (Extract/Chunk/Index) plus per-slot options. Shared by
// the upload builder and the reconfigure modal so both pick recipes identically,
// including the contextual chunker's nested LLM selector.
export type RecipeState = {
  parser?: string; chunker?: string; embedder?: string;
  options?: Record<string, Record<string, unknown>>;
};

const LABEL: Record<string, string> = { parser: "Extract", chunker: "Chunk", embedder: "Index" };

export function RecipePicker({ components, endpoints, recipe, setRecipe }: {
  components: Components | null;
  endpoints: LlmEndpoint[];
  recipe: RecipeState;
  setRecipe: Dispatch<SetStateAction<RecipeState>>;
}) {
  const visionCount = endpoints.filter((e) => e.supports_vision).length;
  const slotErrors = recipeErrors(recipe, components, endpoints.length, visionCount);

  const select = (kind: "parser" | "chunker" | "embedder", nested?: ReactNode) => {
    const err = slotErrors[kind];
    return (
      <div>
        <div style={{ background: "var(--card)", borderRadius: 9, padding: "9px 14px",
          border: err ? "1px solid var(--oxblood)" : "1px solid var(--frame-rule)" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em",
              textTransform: "uppercase", width: 62,
              color: err ? "var(--oxblood)" : "var(--ink-faint)" }}>{LABEL[kind]}</span>
            <select value={recipe[kind] ?? ""} aria-label={LABEL[kind]}
              onChange={(e) => setRecipe((r) => ({ ...r, [kind]: e.target.value }))}>
              {(components?.[kind] ?? []).map((o) =>
                <option key={o.name} value={o.name}>{componentLabel(o.name)}</option>)}
            </select>
          </label>
          {nested && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 9, paddingTop: 9,
              paddingLeft: 18, borderTop: "1px dashed var(--frame-rule)" }}>
              <span aria-hidden style={{ color: "var(--ink-faint)", fontSize: 13 }}>↳</span>
              {nested}
            </div>
          )}
        </div>
        {err && <div role="alert" style={{ fontSize: 11.5, color: "var(--oxblood)",
          margin: "4px 0 0 4px" }}>{LABEL[kind]} {err}</div>}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {select("parser", recipe.parser === "vision" ? (
        <VisionLlmSelect endpoints={endpoints}
          value={(recipe.options?.parser?.vision_endpoint as string) ?? null}
          onChange={(name) => setRecipe((r) => ({ ...r,
            options: { ...r.options, parser: { ...r.options?.parser, vision_endpoint: name } } }))} />
      ) : undefined)}
      {select("chunker", recipe.chunker === "contextual" ? (
        <ContextualLlmSelect endpoints={endpoints}
          value={(recipe.options?.chunker?.llm_endpoint as string) ?? null}
          onChange={(name) => setRecipe((r) => ({ ...r,
            options: { ...r.options, chunker: { ...r.options?.chunker, llm_endpoint: name } } }))} />
      ) : undefined)}
      {select("embedder")}
    </div>
  );
}
