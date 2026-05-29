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
        event_id = next(self._counter)
        self._items.append((event_id, event))
        return event_id

    def replay_from(self, last_event_id: int) -> Iterable[dict]:
        for eid, ev in self._items:
            if eid >= last_event_id:
                yield ev
