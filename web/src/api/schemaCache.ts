import { apiGet } from "./client";

export type JsonSchema = Record<string, unknown>;

let cached: JsonSchema | null = null;
let pending: Promise<JsonSchema> | null = null;

export async function loadSchema(): Promise<JsonSchema> {
  if (cached) return cached;
  if (pending) return pending;
  pending = apiGet<JsonSchema>("/api/schema")
    .then((s) => { cached = s; pending = null; return s; })
    .catch((e) => { pending = null; throw e; });
  return pending;
}

// Test-only escape hatch — keep export prefixed with `_`.
export function _resetSchemaCache() { cached = null; pending = null; }
