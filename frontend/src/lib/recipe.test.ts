import { recipeErrors, recipeIsValid, defaultRecipe, componentLabel, suggestPipelineName } from "./recipe";
import type { Components } from "../api/types";

const COMPONENTS: Components = {
  parser: [{ name: "docling", license: null, org: null },
           { name: "pymupdf", license: null, org: null },
           { name: "router", license: null, org: null }],
  chunker: [
    { name: "docling-hybrid", license: null, org: null,
      requires: { parser: ["docling", "router"] } },
    { name: "recursive-text", license: null, org: null },
  ],
  embedder: [{ name: "granite", license: null, org: null }],
  reranker: [],
};

test("valid recipe has no errors", () => {
  expect(recipeErrors({ parser: "docling", chunker: "docling-hybrid" }, COMPONENTS)).toEqual({});
  expect(recipeIsValid({ parser: "router", chunker: "docling-hybrid" }, COMPONENTS)).toBe(true);
});

test("flags BOTH boxes in the conflict, each with its own message", () => {
  const errs = recipeErrors({ parser: "pymupdf", chunker: "docling-hybrid" }, COMPONENTS);
  expect(Object.keys(errs).sort()).toEqual(["chunker", "parser"]);
  // the chunk box (the component with the requirement) names the slot to fix
  expect(errs.chunker).toContain("docling");
  expect(errs.chunker).toContain("extract");
  // the extract box (the wrong value) names the component demanding it
  expect(errs.parser).toContain("docling");
  expect(errs.parser).toContain("docling-hybrid");
  expect(recipeIsValid({ parser: "pymupdf", chunker: "docling-hybrid" }, COMPONENTS)).toBe(false);
});

test("unconstrained components never error with any parser", () => {
  expect(recipeErrors({ parser: "pymupdf", chunker: "recursive-text" }, COMPONENTS)).toEqual({});
});

test("null components is treated as valid (nothing to enforce yet)", () => {
  expect(recipeIsValid({ parser: "pymupdf", chunker: "docling-hybrid" }, null)).toBe(true);
});

test("defaultRecipe opens on the canonical docling + docling-hybrid stack", () => {
  expect(defaultRecipe(COMPONENTS)).toEqual(
    { parser: "docling", chunker: "docling-hybrid", embedder: "granite" });
  // and that default is itself valid
  expect(recipeIsValid(defaultRecipe(COMPONENTS), COMPONENTS)).toBe(true);
});

test("defaultRecipe falls back to first-in-list when a preferred component is absent", () => {
  const noHybrid: Components = {
    parser: [{ name: "pymupdf", license: null, org: null }],
    chunker: [{ name: "recursive-text", license: null, org: null }],
    embedder: [{ name: "minilm", license: null, org: null }],
    reranker: [],
  };
  expect(defaultRecipe(noHybrid)).toEqual(
    { parser: "pymupdf", chunker: "recursive-text", embedder: "minilm" });
});

const COMP_CONTEXTUAL = {
  parser: [{ name: "docling" }], chunker: [{ name: "contextual" }],
  embedder: [{ name: "granite-embedding-english-r2" }],
} as any;

test("contextual chunker is invalid when no LLM endpoint exists", () => {
  const errs = recipeErrors({ parser: "docling", chunker: "contextual" }, COMP_CONTEXTUAL, 0);
  expect(errs.chunker).toMatch(/no valid llm/i);
});

test("contextual chunker is valid when an endpoint exists", () => {
  const errs = recipeErrors({ parser: "docling", chunker: "contextual" }, COMP_CONTEXTUAL, 1);
  expect(errs.chunker).toBeUndefined();
});

const COMP_VISION = {
  parser: [{ name: "docling" }, { name: "vision" }],
  chunker: [{ name: "recursive-text" }],
  embedder: [{ name: "granite-embedding-english-r2" }],
} as any;

test("vision parser is invalid when no vision-capable endpoint exists", () => {
  const errs = recipeErrors(
    { parser: "vision", chunker: "recursive-text" }, COMP_VISION, 2, 0);
  expect(errs.parser).toMatch(/no vision/i);
});

test("vision parser is valid when a vision endpoint exists", () => {
  const errs = recipeErrors(
    { parser: "vision", chunker: "recursive-text" }, COMP_VISION, 2, 1);
  expect(errs.parser).toBeUndefined();
});

test("suggestPipelineName builds <stem>_<parser> and sanitizes", () => {
  expect(suggestPipelineName("F-35 Overview.pdf", "vision", [])).toBe("F-35_Overview_vision");
  expect(suggestPipelineName("notes.txt", "docling", [])).toBe("notes_docling");
  expect(suggestPipelineName("a/b/deep.pdf", "pypdfium2", [])).toBe("deep_pypdfium2");
});

test("suggestPipelineName disambiguates against taken names", () => {
  const taken = ["doc_vision", "doc_vision_2"];
  expect(suggestPipelineName("doc.pdf", "vision", taken)).toBe("doc_vision_3");
  // a free base name is used as-is
  expect(suggestPipelineName("doc.pdf", "docling", taken)).toBe("doc_docling");
});

test("componentLabel adds an algorithm hint, falls back to the raw name", () => {
  expect(componentLabel("semantic")).toBe("Semantic (REGEX)");
  expect(componentLabel("recursive-text")).toBe("Recursive-text (Paragraph/Line)");
  expect(componentLabel("router")).toBe("Router (Mixed)");
  expect(componentLabel("docling")).toBe("docling");
});
