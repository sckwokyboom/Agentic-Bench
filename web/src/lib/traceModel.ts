import type { Step, Trace } from "../api/types";

export type UiPart =
  | { kind: "reasoning" | "text"; text: string }
  | { kind: "tool"; name: string; args: Record<string, unknown>; output: string | null; exitCode: number | null; ok: boolean | null }
  | { kind: "edit"; path: string; patch: string };

export interface UiTurn {
  index: number;
  messageId: string | null;
  reason: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  tokensReasoning: number | null;
  cost: number | null;
  durationS: number | null;
  parts: UiPart[];
}

function emptyTurn(index: number): UiTurn {
  return { index, messageId: null, reason: null, tokensIn: null, tokensOut: null,
    tokensReasoning: null, cost: null, durationS: null, parts: [] };
}

// ── From the normalized trace.json (finished runs — authoritative) ──────────
export function turnsFromTrace(trace: Pick<Trace, "steps" | "turns">): UiTurn[] {
  const byTurn = new Map<number, UiTurn>();
  const ensure = (i: number) => {
    let t = byTurn.get(i);
    if (!t) { t = emptyTurn(i); byTurn.set(i, t); }
    return t;
  };
  const resultByCall = new Map<string, Step>();
  for (const s of trace.steps) {
    if (s.kind === "tool_result" && s.tool_call_id) resultByCall.set(s.tool_call_id, s);
  }
  for (const s of trace.steps) {
    if (s.turn == null) continue;
    const t = ensure(s.turn);
    if (s.kind === "reasoning") t.parts.push({ kind: "reasoning", text: s.text ?? "" });
    else if (s.kind === "assistant_text") t.parts.push({ kind: "text", text: s.text ?? "" });
    else if (s.kind === "file_edit") t.parts.push({ kind: "edit", path: s.path ?? "", patch: s.patch ?? "" });
    else if (s.kind === "tool_call") {
      const res = s.tool_call_id ? resultByCall.get(s.tool_call_id) : undefined;
      const exitCode = res?.exit_code ?? null;
      t.parts.push({
        kind: "tool", name: s.tool_name ?? "?", args: s.tool_args ?? {},
        output: res?.output ?? null,
        exitCode,
        ok: exitCode == null ? null : exitCode === 0,
      });
    }
  }
  trace.turns.forEach((ti, idx) => {
    const t = ensure(idx);
    t.messageId = ti.message_id ?? null;
    t.reason = ti.reason ?? null;
    t.tokensIn = ti.tokens_in ?? null;
    t.tokensOut = ti.tokens_out ?? null;
    t.tokensReasoning = ti.tokens_reasoning ?? null;
    t.cost = ti.cost ?? null;
    t.durationS = (ti.started_at != null && ti.ended_at != null)
      ? ti.ended_at - ti.started_at : null;
  });
  return [...byTurn.values()].sort((a, b) => a.index - b.index);
}

// ── From raw OpenCode events (live stream — no normalized trace yet) ────────
export function turnsFromRawEvents(rawEvents: any[]): UiTurn[] {
  const order: string[] = [];
  const byId = new Map<string, UiTurn>();
  const ensure = (mid: string) => {
    let t = byId.get(mid);
    if (!t) { t = emptyTurn(order.length); t.messageId = mid; byId.set(mid, t); order.push(mid); }
    return t;
  };
  for (const ev of rawEvents) {
    const p = ev?.part ?? {};
    const mid = p.messageID;
    if (!mid) continue;
    const t = ensure(mid);
    if (p.type === "reasoning") t.parts.push({ kind: "reasoning", text: String(p.text ?? "") });
    else if (p.type === "text") t.parts.push({ kind: "text", text: String(p.text ?? "") });
    else if (p.type === "patch") t.parts.push({ kind: "edit", path: String(p.path ?? ""), patch: String(p.patch ?? "") });
    else if (p.type === "tool") {
      const st = p.state ?? {};
      const exitRaw = st.metadata?.exit;
      const exitCode = typeof exitRaw === "number" ? exitRaw : null;
      const ok = st.status === "error" ? false : exitCode == null ? (st.status === "completed" ? true : null) : exitCode === 0;
      t.parts.push({
        kind: "tool", name: String(p.tool ?? "?"), args: st.input ?? {},
        output: st.output != null ? String(st.output) : null, exitCode, ok,
      });
    } else if (p.type === "step-finish") {
      const tk = p.tokens ?? {};
      t.reason = p.reason ?? t.reason;
      t.tokensIn = tk.input ?? t.tokensIn;
      t.tokensOut = tk.output ?? t.tokensOut;
      t.tokensReasoning = tk.reasoning ?? t.tokensReasoning;
      t.cost = p.cost ?? t.cost;
    }
  }
  return order.map((mid) => byId.get(mid)!);
}

// Per-turn breakdown by real tool name: { read: 3, grep: 2, edit: 1 }.
export function toolBreakdown(turn: UiTurn): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of turn.parts) {
    if (p.kind === "tool") out[p.name] = (out[p.name] ?? 0) + 1;
    else if (p.kind === "edit") out["edit"] = (out["edit"] ?? 0) + 1;
  }
  return out;
}
