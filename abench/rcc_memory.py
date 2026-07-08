"""Memory Graph for rcc: a tolerant JSON store, ``fqn -> {causal_graph,
test_classes, ts}``. Exact-match keys (semantic lookup is a later phase). The
A/B runner gives each rep a FRESH file (rep independence); the hit-rate demo
passes one persistent path across two runs — both are Phase 2 wiring."""
from __future__ import annotations

import json
import time
from pathlib import Path


class RccMemory:
    def __init__(self, path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            if isinstance(d, dict) and isinstance(d.get("entries"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"entries": {}}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2))
        except OSError:
            pass                                    # best-effort persistence

    def get(self, fqn: str) -> "dict | None":
        e = self._data["entries"].get(fqn)
        # Tolerate hand-edited/corrupt entries the same way as a corrupt file:
        # a malformed entry is a MISS, never a crash downstream.
        if (isinstance(e, dict) and isinstance(e.get("causal_graph"), dict)
                and isinstance(e.get("test_classes"), list)):
            return e
        return None

    def put(self, fqn: str, causal_graph: dict, test_classes: list) -> None:
        self._data["entries"][fqn] = {"causal_graph": causal_graph,
                                      "test_classes": list(test_classes),
                                      "ts": time.time()}
        self._save()

    def invalidate(self, fqn: str) -> None:
        if self._data["entries"].pop(fqn, None) is not None:
            self._save()
