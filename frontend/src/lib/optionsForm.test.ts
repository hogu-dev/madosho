import { describe, expect, it } from "vitest";
import { optionFields, changedOptions } from "./optionsForm";

const schema = {
  properties: {
    max_chars: { type: "integer", default: 1200, minimum: 1, title: "Max chars" },
    overlap: { type: "integer", default: 150 },
    breakpoint_percentile: { type: "number", default: 95, minimum: 0, maximum: 100 },
  },
};

describe("optionFields", () => {
  it("extracts fields with type, default and bounds", () => {
    const fields = optionFields(schema);
    const mc = fields.find((f) => f.name === "max_chars")!;
    expect(mc.type).toBe("integer");
    expect(mc.default).toBe(1200);
    expect(mc.min).toBe(1);
    const bp = fields.find((f) => f.name === "breakpoint_percentile")!;
    expect(bp.max).toBe(100);
  });
  it("returns [] for null/empty schema", () => {
    expect(optionFields(null)).toEqual([]);
    expect(optionFields({})).toEqual([]);
  });
});

describe("changedOptions", () => {
  it("keeps only values differing from the default", () => {
    const fields = optionFields(schema);
    const out = changedOptions({ max_chars: 800, overlap: 150 }, fields);
    expect(out).toEqual({ max_chars: 800 });   // overlap unchanged -> dropped
  });
  it("returns {} when nothing changed", () => {
    const fields = optionFields(schema);
    expect(changedOptions({ max_chars: 1200 }, fields)).toEqual({});
  });
});
