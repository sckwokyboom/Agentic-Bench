import { apiGet } from "./client";

export type JsonSchema = Record<string, unknown>;

let cached: JsonSchema | null = null;
let pending: Promise<JsonSchema> | null = null;

// Pydantic emits Optional[str] as { anyOf: [{type:"string"}, {type:"null"}] }, which
// rjsf renders as a pointless type-picker dropdown. Collapse such nodes to a plain
// { type: "string" } (preserving title/description/default) so they render as one text field.
export function collapseNullableStrings(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(collapseNullableStrings);
  if (node && typeof node === "object") {
    const obj = node as Record<string, unknown>;
    const anyOf = obj.anyOf;
    if (Array.isArray(anyOf) && anyOf.length === 2) {
      const types = anyOf.map((s) => (s && typeof s === "object" ? (s as Record<string, unknown>).type : undefined));
      const hasString = types.includes("string");
      const hasNull = types.includes("null");
      if (hasString && hasNull) {
        const { anyOf: _drop, ...rest } = obj;
        return { ...rest, type: "string" };
      }
    }
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) out[k] = collapseNullableStrings(v);
    return out;
  }
  return node;
}

export async function loadSchema(): Promise<JsonSchema> {
  if (cached) return cached;
  if (pending) return pending;
  pending = apiGet<JsonSchema>("/api/schema")
    .then((s) => { cached = collapseNullableStrings(s) as JsonSchema; pending = null; return cached; })
    .catch((e) => { pending = null; throw e; });
  return pending;
}

// Test-only escape hatch — keep export prefixed with `_`.
export function _resetSchemaCache() { cached = null; pending = null; }
