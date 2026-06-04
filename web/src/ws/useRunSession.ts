import { useEffect, useRef, useState } from "react";
import type { Envelope } from "./envelope";

interface State {
  envelopes: Envelope[];
  lastEventId: number;
  status: "connecting" | "open" | "closed" | "done";
  error: string | null;
}

const RECONNECT_DELAY_MS = 750;
// Server closes an unknown/expired session (e.g. after a server restart) with
// this code — terminal, never worth reconnecting.
const UNKNOWN_SESSION_CODE = 4004;
// Backstop: stop the open/close loop if reconnects never succeed.
const MAX_RECONNECTS = 8;

export function useRunSession(sid: string | undefined) {
  const [state, setState] = useState<State>({
    envelopes: [],
    lastEventId: 0,
    status: "connecting",
    error: null,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const lastIdRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    if (!sid) return;
    doneRef.current = false;
    lastIdRef.current = 0;
    let reconnects = 0;

    function connect() {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${window.location.host}/ws/sessions/${sid}?last_event_id=${lastIdRef.current}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setState((s) => ({ ...s, status: "connecting" }));

      ws.onopen = () => { reconnects = 0; setState((s) => ({ ...s, status: "open" })); };

      ws.onmessage = (ev) => {
        let env: Envelope;
        try {
          env = JSON.parse(ev.data) as Envelope;
        } catch {
          return;
        }
        // Drop replayed duplicates: on reconnect the server replays from
        // last_event_id and any overlap would otherwise be appended twice,
        // inflating done/running counts. Skip anything we have already seen.
        if (typeof env.event_id === "number") {
          if (env.event_id <= lastIdRef.current) return;
          lastIdRef.current = env.event_id;
        }
        if (env.type === "session.finished" || env.type === "session.error") {
          doneRef.current = true;
        }
        setState((s) => ({
          ...s,
          envelopes: [...s.envelopes, env],
          lastEventId: lastIdRef.current,
          error: env.type === "session.error" ? env.message : s.error,
        }));
      };

      ws.onclose = (event) => {
        if (doneRef.current) {
          setState((s) => ({ ...s, status: "done" }));
          return;
        }
        // Unknown/expired session → terminal; reconnecting would loop forever
        // (open/close every 750ms). Stop and surface a clear message.
        if (event.code === UNKNOWN_SESSION_CODE) {
          doneRef.current = true;
          setState((s) => ({
            ...s, status: "closed",
            error: s.error
              ?? "This run session is no longer available (the server may have restarted). Open the experiment's Results to view finished runs.",
          }));
          return;
        }
        reconnects += 1;
        if (reconnects > MAX_RECONNECTS) {
          setState((s) => ({
            ...s, status: "closed",
            error: s.error ?? "Lost connection to the run session.",
          }));
          return;
        }
        setState((s) => ({ ...s, status: "closed" }));
        setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();
    return () => {
      doneRef.current = true;
      wsRef.current?.close();
    };
  }, [sid]);

  return state;
}
