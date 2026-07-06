import type { Components } from "../api/types";

export type Recipe = { parser?: string; chunker?: string; embedder?: string };

// Friendlier display names for the builder dropdowns: the parenthetical names the
// algorithm so a user can tell the options apart without reading docs. Names not
// listed here render as-is. Keep keys in sync with the registry component names.
const COMPONENT_LABEL: Record<string, string> = {
  semantic: "Semantic (REGEX)",
  "recursive-text": "Recursive-text (Paragraph/Line)",
  router: "Router (Mixed)",
};

/** Human label for a component name, for builder menus. Falls back to the name. */
export function componentLabel(name: string): string {
  return COMPONENT_LABEL[name] ?? name;
}

const SLOTS = ["parser", "chunker", "embedder"] as const;
type Slot = typeof SLOTS[number];

// Builder labels for each slot, used inside error messages so they read in the
// user's terms ("...in extract") rather than the internal kind ("...in parser").
const SLOT_LABEL: Record<Slot, string> = { parser: "extract", chunker: "chunk", embedder: "index" };

// Preferred default per slot = the canonical stack the backend's
// default_pipeline_config builds (docling -> docling-hybrid -> granite). Falls
// back to first-in-list when a preferred component isn't installed.
const PREFERRED: Record<Slot, string> = {
  parser: "docling", chunker: "docling-hybrid", embedder: "granite-embedding-english-r2",
};

/**
 * Per-slot error messages for a recipe, given the component catalog's declared
 * `requires`. Returns {} when every chosen component's hard dependencies are
 * met. When a dependency is unmet BOTH boxes in the conflict are flagged: the
 * requiring slot (e.g. the docling-hybrid CHUNK box -> "needs docling or router
 * in extract") and the violating slot (the EXTRACT box -> "needs docling or
 * router for the docling-hybrid chunk"), so whichever box the user looks at
 * explains the problem. Empty = valid.
 */
export function recipeErrors(
  recipe: Recipe, components: Components | null, endpointCount?: number,
  visionEndpointCount?: number,
): Partial<Record<Slot, string>> {
  const errors: Partial<Record<Slot, string>> = {};
  if (!components) return errors;
  if (recipe.chunker === "contextual" && endpointCount === 0) {
    errors.chunker = "no valid LLM endpoint configured";
  }
  if (recipe.parser === "vision" && visionEndpointCount === 0) {
    errors.parser = "no vision-capable LLM endpoint configured";
  }
  for (const slot of SLOTS) {
    const name = recipe[slot];
    if (!name) continue;
    const requires = (components[slot] ?? []).find((c) => c.name === name)?.requires;
    if (!requires) continue;
    for (const [reqSlotStr, allowed] of Object.entries(requires)) {
      const reqSlot = reqSlotStr as Slot;
      if (!allowed.includes(recipe[reqSlot] ?? "")) {
        const allowedStr = allowed.join(" or ");
        // the component that owns the requirement (e.g. CHUNK): name the slot to fix
        errors[slot] = `needs ${allowedStr} in ${SLOT_LABEL[reqSlot]}`;
        // the slot whose value is wrong (e.g. EXTRACT): name the component demanding it
        errors[reqSlot] = `needs ${allowedStr} for the ${name} ${SLOT_LABEL[slot]}`;
      }
    }
  }
  return errors;
}

/** True when the recipe has no unmet slot dependencies (safe to build). */
export function recipeIsValid(recipe: Recipe, components: Components | null,
  endpointCount?: number, visionEndpointCount?: number): boolean {
  return Object.keys(
    recipeErrors(recipe, components, endpointCount, visionEndpointCount)).length === 0;
}

/**
 * Suggest a unique pipeline name for a document + recipe, avoiding names already
 * in use. Mirrors the backend convention `<stem>_<parser>` (sanitized the same way
 * as the server's sanitize_name: keep [A-Za-z0-9._-], replace the rest with "_").
 * Appends `_2`, `_3`, ... on collision. This matters beyond convenience: the build
 * endpoint is idempotent by (document, name), so a colliding name silently resolves
 * to the EXISTING pipeline instead of building the new recipe.
 */
export function suggestPipelineName(
  filename: string, parser: string | undefined, taken: Iterable<string>,
): string {
  const stem = (filename.split("/").pop() ?? filename).replace(/\.[^.]+$/, "") || "doc";
  const slug = stem.replace(/[^A-Za-z0-9._-]/g, "_");
  const base = parser ? `${slug}_${parser}` : slug;
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let i = 2; ; i++) {
    const candidate = `${base}_${i}`;
    if (!used.has(candidate)) return candidate;
  }
}

/** The recipe a freshly opened builder should start on: the canonical default
 *  stack when available, else the first option per slot. Always a valid pair. */
export function defaultRecipe(components: Components): Recipe {
  const pick = (slot: Slot) => {
    const rows = components[slot] ?? [];
    return rows.find((r) => r.name === PREFERRED[slot])?.name ?? rows[0]?.name;
  };
  return { parser: pick("parser"), chunker: pick("chunker"), embedder: pick("embedder") };
}
