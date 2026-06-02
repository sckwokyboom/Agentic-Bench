"""Per-session ring buffer of raw events for WebSocket replay on reconnect."""
from __future__ import annotations

import itertools
from collections import deque
from typing import Iterable


class SessionEventBuffer:
    def __init__(self, capacity: int = 5000):
        self.capacity = capacity
        self._counter = itertools.count(1)
        self._items: deque[tuple[int, dict]] = deque(maxlen=capacity)

    def append(self, event: dict) -> int:
        """Append event and return its assigned event_id.

        NOTE: the stored envelope does NOT have event_id injected here.
        Prefer next_id() + append_with_id() when you want event_id baked in."""
        event_id = next(self._counter)
        self._items.append((event_id, event))
        return event_id

    def next_id(self) -> int:
        """Reserve and return the next event_id without appending anything."""
        return next(self._counter)

    def append_with_id(self, event_id: int, event: dict) -> None:
        """Append an event that already has its event_id baked in."""
        self._items.append((event_id, event))

    def replay_from(self, last_event_id: int) -> Iterable[dict]:
        # EXCLUSIVE: the client passes the last event_id it already HAS; replay
        # returns strictly-newer events so a reconnect never duplicates the
        # last-seen envelope. (last_event_id=0 → everything, since ids start 1.)
        for eid, ev in self._items:
            if eid > last_event_id:
                yield ev
