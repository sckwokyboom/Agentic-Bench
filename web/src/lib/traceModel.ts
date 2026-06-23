import type { Step, Trace } from "../api/types";

/** Rough token estimate (≈ chars/4); mirrors abench/tokens.py so UI and computed
 * numbers agree. Provider-agnostic heuristic for relative context-cost, not exact. */
export function estimateTokens(text: string | null | undefined): number {
  return text ? Math.ceil(text.length / 4) : 0;
}

export type UiPart =
  | { kind: "reasoning" | "text"; text: string }
  | { kind: "tool"; name: string; args: Record<string, unknown>; output: string | null; outputTokens: number; exitCode: number | null; ok: boolean | null }
  | { kind: "edit"; path: string; patch: string }
  | { kind: "controller"; text: string };

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
  phase: string | null;       // orchestration phase (null = autonomous baseline)
  isController: boolean;       // a deterministic controller action, not an LLM turn
}

function emptyTurn(index: number): UiTurn {
  return { index, messageId: null, reason: null, tokensIn: null, tokensOut: null,
    tokensReasoning: null, cost: null, durationS: null, parts: [], phase: null,
    isController: false };
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
    // First non-null message_id wins, so each UiTurn knows its messageId.
    t.messageId = t.messageId ?? s.message_id ?? null;
    t.phase = t.phase ?? s.phase ?? null;
    if (s.kind === "reasoning") t.parts.push({ kind: "reasoning", text: s.text ?? "" });
    else if (s.kind === "assistant_text") t.parts.push({ kind: "text", text: s.text ?? "" });
    else if (s.kind === "file_edit") t.parts.push({ kind: "edit", path: s.path ?? "", patch: s.patch ?? "" });
    else if (s.kind === "controller") { t.parts.push({ kind: "controller", text: s.text ?? "" }); t.isController = true; }
    else if (s.kind === "tool_call") {
      const res = s.tool_call_id ? resultByCall.get(s.tool_call_id) : undefined;
      const exitCode = res?.exit_code ?? null;
      t.parts.push({
        kind: "tool", name: s.tool_name ?? "?", args: s.tool_args ?? {},
        output: res?.output ?? null,
        outputTokens: estimateTokens(res?.output ?? null),
        exitCode,
        ok: exitCode == null ? null : exitCode === 0,
      });
    }
  }

  const fillStats = (t: UiTurn, ti: Trace["turns"][number]) => {
    t.reason = ti.reason ?? null;
    t.tokensIn = ti.tokens_in ?? null;
    t.tokensOut = ti.tokens_out ?? null;
    t.tokensReasoning = ti.tokens_reasoning ?? null;
    t.cost = ti.cost ?? null;
    t.durationS = (ti.started_at != null && ti.ended_at != null)
      ? ti.ended_at - ti.started_at : null;
  };

  // Join TurnInfo by message_id when steps carry one (real traces); fall back to
  // array-index join for synthetic/legacy data whose steps lack message_id.
  const useMid = trace.steps.some((s) => s.turn != null && s.message_id);
  if (useMid) {
    const byMid = new Map<string, UiTurn>();
    for (const t of byTurn.values()) if (t.messageId) byMid.set(t.messageId, t);
    for (const ti of trace.turns) {
      const mid = ti.message_id ?? null;
      let t = mid != null ? byMid.get(mid) : undefined;
      if (!t) {
        // step-finish for a message with no steps — rare. Append a new turn.
        t = emptyTurn(byTurn.size);
        t.messageId = mid;
        byTurn.set(t.index, t);
        if (mid != null) byMid.set(mid, t);
      }
      fillStats(t, ti);
    }
  } else {
    trace.turns.forEach((ti, idx) => {
      const t = ensure(idx);
      t.messageId = ti.message_id ?? null;
      fillStats(t, ti);
    });
  }
  return [...byTurn.values()].sort((a, b) => a.index - b.index);
}

// ── From raw OpenCode events (live stream — no normalized trace yet) ────────
export function turnsFromRawEvents(rawEvents: any[]): UiTurn[] {
  const order: string[] = [];
  const byId = new Map<string, UiTurn>();
  // Per-turn map of part id → index into t.parts, so a re-emitted part id
  // (e.g. a tool going running → completed) replaces its earlier partial
  // instead of pushing a duplicate. Id-less parts are never coalesced.
  const partIdxById = new Map<string, Map<string, number>>();
  const ensure = (mid: string) => {
    let t = byId.get(mid);
    if (!t) {
      t = emptyTurn(order.length); t.messageId = mid;
      byId.set(mid, t); order.push(mid); partIdxById.set(mid, new Map());
    }
    return t;
  };
  for (const ev of rawEvents) {
    const p = ev?.part ?? {};
    const mid = p.messageID;
    if (!mid) continue;
    const t = ensure(mid);
    // Last-write-wins by part id; absent id → always push.
    const idMap = partIdxById.get(mid)!;
    const pid: string | undefined = p.id ? String(p.id) : undefined;
    const place = (part: UiPart) => {
      if (pid && idMap.has(pid)) {
        t.parts[idMap.get(pid)!] = part;
      } else {
        if (pid) idMap.set(pid, t.parts.length);
        t.parts.push(part);
      }
    };
    if (p.type === "reasoning") place({ kind: "reasoning", text: String(p.text ?? "") });
    else if (p.type === "text") place({ kind: "text", text: String(p.text ?? "") });
    else if (p.type === "patch") place({ kind: "edit", path: String(p.path ?? ""), patch: String(p.patch ?? "") });
    else if (p.type === "tool") {
      const st = p.state ?? {};
      const exitRaw = st.metadata?.exit;
      const exitCode = typeof exitRaw === "number" ? exitRaw : null;
      const ok = st.status === "error" ? false : exitCode == null ? (st.status === "completed" ? true : null) : exitCode === 0;
      const toolOut = st.output != null ? String(st.output) : null;
      place({
        kind: "tool", name: String(p.tool ?? "?"), args: st.input ?? {},
        output: toolOut, outputTokens: estimateTokens(toolOut), exitCode, ok,
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

// ── Observation (tool-output) token cost — "how much context the tools poured in" ──
/** Estimated tokens of this turn's tool outputs (what the model had to read back). */
export function turnObsTokens(turn: UiTurn): number {
  return turn.parts.reduce((n, p) => n + (p.kind === "tool" ? p.outputTokens : 0), 0);
}

/** Across the run: estimated observation tokens per tool name. */
export function observationTokensByTool(turns: UiTurn[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const t of turns) {
    for (const p of t.parts) {
      if (p.kind === "tool" && p.outputTokens > 0) {
        out[p.name] = (out[p.name] ?? 0) + p.outputTokens;
      }
    }
  }
  return out;
}

export function observationTokensTotal(turns: UiTurn[]): number {
  return turns.reduce((n, t) => n + turnObsTokens(t), 0);
}

/** Real provider input tokens summed over turns — the actual context the model
 * was billed for (already reflects any OpenCode compaction/truncation). */
export function realInputTokensTotal(turns: UiTurn[]): number {
  return turns.reduce((n, t) => n + (t.tokensIn ?? 0), 0);
}

// ── Readable per-tool argument summary ───────────────────────────────────────
// Strip the temp workdir prefix (/tmp/abench-<nonce>/…) to the repo-relative tail.
function shortenToolPath(p: string): string {
  const m = /abench-[^/\s]+\/(.+)$/.exec(p);
  return m ? m[1]! : p;
}

/**
 * A readable summary of a tool call's inputs, per tool — NOT first-key-wins (the
 * old picker showed grep's `path` and dropped its `pattern`). Shows the field(s)
 * that actually matter for each tool and never dumps bulky args (edit's
 * oldString/newString, write's content, task's prompt).
 */
export function formatToolArgs(name: string, args: Record<string, unknown> | null | undefined): string {
  const a = args ?? {};
  const s = (k: string): string => (typeof a[k] === "string" ? (a[k] as string) : "");
  const numOf = (k: string): number | null => (typeof a[k] === "number" ? (a[k] as number) : null);
  const rawPath = s("filePath") || s("path") || s("file");
  const rel = rawPath ? shortenToolPath(rawPath) : "";
  const t = (name || "").toLowerCase();
  let out = "";
  switch (t) {
    case "grep": {
      const pat = s("pattern") || s("query");
      const quals = [s("include") && `include:${s("include")}`, rel && `in:${rel}`].filter(Boolean).join(" ");
      out = [pat, quals].filter(Boolean).join("  ");
      break;
    }
    case "glob":
      out = [s("pattern"), rel && `in:${rel}`].filter(Boolean).join("  ");
      break;
    case "read": {
      const off = numOf("offset");
      const lim = numOf("limit");
      const span = off != null ? `@${off}${lim != null ? `+${lim}` : ""}` : (lim != null ? `(${lim} lines)` : "");
      out = [rel, span].filter(Boolean).join("  ");
      break;
    }
    case "list":
      out = rel;
      break;
    case "bash":
      out = s("command") || s("cmd") || s("script");
      break;
    case "edit":
    case "write":
    case "patch":
      out = rel;  // never dump oldString / newString / content
      break;
    case "task":
      out = [s("description"), s("subagent_type") && `(${s("subagent_type")})`].filter(Boolean).join(" ");
      break;
    case "todowrite":
      out = Array.isArray(a.todos) ? `${(a.todos as unknown[]).length} todos` : "";
      break;
    case "webfetch":
    case "fetch":
    case "websearch":
      out = s("url") || s("query");
      break;
    default: {
      const primary = s("command") || s("pattern") || s("query") || rel || s("url") || s("description");
      if (primary) { out = primary; break; }
      const compact = Object.fromEntries(
        Object.entries(a).filter(([k]) => !["oldString", "newString", "content", "prompt", "todos"].includes(k)));
      const j = JSON.stringify(compact);
      out = j === "{}" ? "" : j;
    }
  }
  return out.length > 280 ? out.slice(0, 280) + "…" : out;
}
