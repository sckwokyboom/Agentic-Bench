export interface TurnGroup {
  messageId: string;
  parts: any[];
  reason: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  tokensReasoning: number | null;
  cost: number | null;
  startedAt: number | null;
  endedAt: number | null;
}

export function groupEventsByTurn(events: any[]): TurnGroup[] {
  const byId = new Map<string, TurnGroup>();
  const order: string[] = [];
  for (const ev of events) {
    const id = ev?.part?.messageID;
    if (!id) continue;
    if (!byId.has(id)) {
      byId.set(id, {
        messageId: id, parts: [], reason: null,
        tokensIn: null, tokensOut: null, tokensReasoning: null,
        cost: null, startedAt: ev.timestamp ?? null, endedAt: null,
      });
      order.push(id);
    }
    const g = byId.get(id)!;
    g.parts.push(ev.part);
    g.endedAt = ev.timestamp ?? g.endedAt;
    if (ev.part.type === "step-finish") {
      g.reason = ev.part.reason ?? null;
      g.tokensIn = ev.part.tokens?.input ?? null;
      g.tokensOut = ev.part.tokens?.output ?? null;
      g.tokensReasoning = ev.part.tokens?.reasoning ?? null;
      g.cost = ev.part.cost ?? null;
    }
  }
  for (const g of byId.values()) {
    g.parts.sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));
  }
  return order.map((id) => byId.get(id)!);
}
