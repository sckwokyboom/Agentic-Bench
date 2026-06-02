import { apiGet } from "./client";

export type JsonSchema = Record<string, unknown>;

let cached: JsonSchema | null = null;
let pending: Promise<JsonSchema> | null = null;

// Pydantic emits Optional[T] as { anyOf: [{type:"<T>"}, {type:"null"}] }, which rjsf
// renders as a pointless type-picker dropdown. Collapse any such two-branch nullable
// anyOf to the non-null branch T, preserving that branch's own constraints (enum/pattern/
// format) AND the parent node's sibling keys (title/description/default), so it renders
// as a single field. Pure: returns new objects, never mutates the input.
function isNullBranch(s: unknown): boolean {
  return !!s && typeof s === "object" && (s as Record<string, unknown>).type === "null";
}

export function collapseNullable(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(collapseNullable);
  if (node && typeof node === "object") {
    const obj = node as Record<string, unknown>;
    const anyOf = obj.anyOf;
    if (Array.isArray(anyOf) && anyOf.length === 2) {
      const nullCount = anyOf.filter(isNullBranch).length;
      const nn = anyOf.find((s) => !isNullBranch(s));
      if (nullCount === 1 && nn && typeof nn === "object") {
        const nnObj = nn as Record<string, unknown>;
        const { anyOf: _drop, ...rest } = obj;
        // Spread nn first so its enum/pattern/format survive; spread rest so the parent's
        // title/description/default win; keep nn.type explicitly when the branch has one.
        const merged: Record<string, unknown> =
          "type" in nnObj ? { ...nnObj, ...rest, type: nnObj.type } : { ...nnObj, ...rest };
        return collapseNullable(merged);
      }
    }
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) out[k] = collapseNullable(v);
    return out;
  }
  return node;
}

export async function loadSchema(): Promise<JsonSchema> {
  if (cached) return cached;
  if (pending) return pending;
  pending = apiGet<JsonSchema>("/api/schema")
    .then((s) => { cached = collapseNullable(s) as JsonSchema; pending = null; return cached; })
    .catch((e) => { pending = null; throw e; });
  return pending;
}

// Test-only escape hatch — keep export prefixed with `_`.
export function _resetSchemaCache() { cached = null; pending = null; }
