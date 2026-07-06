import { apiGet } from "./client";

export type JsonSchema = Record<string, unknown>;

let cached: JsonSchema | null = null;
let pending: Promise<JsonSchema> | null = null;

// Pydantic emits Optional[T] as { anyOf: [{type:"<T>"}, {type:"null"}] }, which rjsf
// renders as a pointless type-picker dropdown. Collapse any such two-branch nullable
// anyOf to the non-null branch T, preserving that branch's own constraints (enum/pattern/
// format) AND the parent node's sibling keys (title/description/default).
//
// CRUCIAL: keep the value nullable — emit `type: ["<T>", "null"]` (not just "<T>"), so
// AJV still ACCEPTS null (the common "auto"/baseline case where command/augmentation are
// null) while rjsf renders a single widget for the non-null type rather than the type
// picker. Collapsing to a bare "<T>" would make AJV reject null and disable Save.
// Pure: returns new objects, never mutates the input.
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
      const nnType = nn && typeof nn === "object"
        ? (nn as Record<string, unknown>).type
        : undefined;
      // Collapse ONLY nullable primitives, whose non-null branch carries an explicit
      // `type`. A nullable nested model (benchmark, orchestration) has a `$ref` non-null
      // branch with NO `type`; collapsing to it would drop the "null" option, so AJV
      // rejects the null pydantic emits for the unset optional model and wrongly disables
      // Save/Run. Leave those anyOf intact (recurse below) so null stays valid.
      const primitiveNonNull = typeof nnType === "string" || Array.isArray(nnType);
      if (nullCount === 1 && nn && typeof nn === "object" && primitiveNonNull) {
        const nnObj = nn as Record<string, unknown>;
        const { anyOf: _drop, ...rest } = obj;
        // Spread nn first so its enum/pattern/format survive; spread rest so the parent's
        // title/description/default win.
        const merged: Record<string, unknown> = { ...nnObj, ...rest };
        // Preserve nullability via an array type so null stays valid.
        const t = nnObj.type;
        if (typeof t === "string") merged.type = [t, "null"];
        else if (Array.isArray(t)) merged.type = t.includes("null") ? t : [...t, "null"];
        // If the non-null branch constrains values via enum, allow null too.
        if (Array.isArray(merged.enum) && !merged.enum.includes(null)) {
          merged.enum = [...merged.enum, null];
        }
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
