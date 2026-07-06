// Pure helpers turning a component's Options JSON schema (from /components) into
// renderable form fields, and collapsing edited values down to only those that
// differ from the schema default (so server-side defaults stay authoritative).

export type OptionFieldType = "integer" | "number" | "boolean" | "string" | "enum";
export interface OptionField {
  name: string;
  type: OptionFieldType;
  default: unknown;
  label: string;
  min?: number;
  max?: number;
  longString?: boolean;   // render a textarea (e.g. a prompt_template)
  values?: string[];      // enum: the allowed choices, rendered as a select
}

interface JsonSchema {
  properties?: Record<string, Record<string, unknown>>;
}

function fieldType(prop: Record<string, unknown>): OptionFieldType {
  // a pydantic Literal["a","b"] serializes as {type: "string", enum: [...]}
  if (Array.isArray(prop.enum) && prop.enum.every((v) => typeof v === "string")) return "enum";
  const t = prop.type;
  if (t === "integer" || t === "number" || t === "boolean" || t === "string") return t;
  return "string";   // unions / anyOf fall back to a text input
}

export function optionFields(schema: JsonSchema | null | undefined): OptionField[] {
  const props = schema?.properties;
  if (!props) return [];
  return Object.entries(props).map(([name, prop]) => {
    const type = fieldType(prop);
    const def = prop.default;
    return {
      name,
      type,
      default: def,
      label: typeof prop.title === "string" ? prop.title : name,
      min: typeof prop.minimum === "number" ? prop.minimum : undefined,
      max: typeof prop.maximum === "number" ? prop.maximum : undefined,
      longString: type === "string" && typeof def === "string" && def.length > 60,
      values: type === "enum" ? (prop.enum as string[]) : undefined,
    };
  });
}

export function changedOptions(
  values: Record<string, unknown>, fields: OptionField[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (!(f.name in values)) continue;
    if (values[f.name] !== f.default) out[f.name] = values[f.name];
  }
  return out;
}
