import type { TurnInfo } from "../api/types";

export function stopReasonHistogram(turns: TurnInfo[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const t of turns) {
    const k = t.reason ?? "unknown";
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}
