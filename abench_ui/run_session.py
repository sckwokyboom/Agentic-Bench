"""RunSession — encapsulates one in-flight experiment, runs it in a thread,
publishes WS-style envelope messages, supports cooperative cancel.

Envelope types emitted (in order):
  session.started  — once at the start, with total_runs count
  run.phase        — fine-grained setup status during the otherwise-silent
                     startup window (baseline verify, workdir prep, 429 backoff)
  run.started      — once per condition×rep, before the run_task call
  raw_event        — once per opencode JSONL event relayed from the model
  run.finished     — once per condition×rep, after the run_task call returns
  session.finished — always (via finally), with duration_s
  session.error    — only on unhandled exception (before session.finished)
"""
from __future__ import annotations

import threading
import time
import traceback
from enum import Enum
from typing import Callable

from abench.config import Experiment
from abench.opencode_client import RunResult
from abench.runner import compute_plan, default_batch_id, run_experiment


class SessionState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class _PerRunPublishingClient:
    """Wraps an inner OpenCodeClient to emit run.started / raw_event / run.finished
    envelopes around each run_task call.

    The runner calls client_factory(exp) ONCE and then calls run_task N times
    (once per condition×rep), so wrapping at run_task level gives per-rep hooks.
    """

    def __init__(
        self,
        inner,
        publish: Callable[[dict], None],
        session_id: str,
        total_runs: int,
        plan: list,
        position_callback: Callable[[int, str, int], None],
        batch_id: str,
    ):
        self._inner = inner
        self._publish = publish
        self._session_id = session_id
        self._total_runs = total_runs
        self._plan = plan
        self._position_callback = position_callback
        self._batch_id = batch_id
        self._idx: int = 0
        # A condition×rep may call run_task more than once (phased orchestration
        # → one call per phase, all on the same workdir). Track the in-flight run
        # so phase sub-calls REUSE its identity instead of consuming a plan slot.
        self._last_workdir: str | None = None
        self._cur_cond = None
        self._cur_rep: int = 0
        self._cur_run_idx: int = 0
        self._pending_finish: dict | None = None

    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int | None,
        agent_tools: "dict[str, bool] | None" = None,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
        debug_sink: Callable[[str], None] | None = None,
        cancel_event: "threading.Event | None" = None,
        temperature: "float | None" = None,
    ) -> RunResult:
        # A condition×rep may invoke run_task MORE THAN ONCE: phased
        # orchestration drives the agent per phase (understand→plan→implement→
        # diagnose…), every phase a separate run_task on the SAME workdir.
        # Advance to the next plan entry — and emit run.started — only when a
        # NEW workdir appears, so phase sub-calls don't each consume a plan slot.
        # Counting per-call overran self._plan → IndexError, the crash that
        # killed every phased run. The plain (non-phased) path calls run_task
        # once per run, so this stays a no-op there.
        if workdir != self._last_workdir:
            # New workdir = a new condition×rep. Flush the PREVIOUS run's
            # deferred run.finished before starting this one (see the stash below).
            self._flush_finished()
            self._last_workdir = workdir
            # Guard: never IndexError even if the call count somehow exceeds the
            # plan — degrade to the last entry rather than crash the run.
            cond, rep = (self._plan[self._idx] if self._idx < len(self._plan)
                         else self._plan[-1])
            self._idx += 1
            self._cur_cond, self._cur_rep, self._cur_run_idx = cond, rep, self._idx

            # Notify RunSession about the current position
            self._position_callback(self._idx, cond.name, rep)

            self._publish({
                "type": "run.started",
                "session_id": self._session_id,
                "run_idx": self._idx,
                "total_runs": self._total_runs,
                "condition": cond.name,
                "rep": rep,
            })
        cond, rep, run_idx = self._cur_cond, self._cur_rep, self._cur_run_idx

        def on_event_relay(event: dict) -> None:
            self._publish({
                "type": "raw_event",
                "session_id": self._session_id,
                "run_idx": run_idx,
                "condition": cond.name,
                "rep": rep,
                "event": event,
            })
            on_event(event)

        result = self._inner.run_task(
            workdir=workdir,
            system_prompt=system_prompt,
            model=model,
            user_message=user_message,
            timeout_s=timeout_s,
            agent_tools=agent_tools,
            on_event=on_event_relay,
            log_sink=log_sink,
            debug_sink=debug_sink,
            cancel_event=cancel_event,
            temperature=temperature,
        )

        tr = result.trace

        # Surface a model/endpoint failure in the UI (not just the log): a run that
        # errored or produced no output at all — an unreachable endpoint, a bad
        # key, a provider error. Published as a model_error phase BEFORE the
        # deferred run.finished, so the banner shows the reason instead of a stuck
        # "waiting for first model response".
        no_output = not tr.steps if hasattr(tr, "steps") else False
        model_failed = (
            (tr.interrupted_reason in ("error", "stalled", "timeout") and no_output)
            or (tr.n_service_errors or 0) > 0
        )
        if model_failed:
            detail = ""
            msgs = getattr(tr, "service_error_messages", None)
            if msgs:
                detail = f" — {msgs[0]}"
            elif tr.interrupted_reason == "stalled":
                detail = " — no model output (endpoint unreachable or request hung)"
            elif tr.interrupted_reason == "timeout":
                detail = " — timed out before any model response"
            elif tr.interrupted_reason == "error":
                detail = " — opencode exited before any model response"
            self._publish({
                "type": "run.phase",
                "session_id": self._session_id,
                "phase": "model_error",
                "run_idx": run_idx,
                "condition": cond.name,
                "rep": rep,
                "message": f"Model/endpoint error{detail}",
            })

        # `made_source_changes` mirrors the metrics semantics (non-empty patch);
        # the runner has already populated tr.final_diff_summary from the real
        # diff by the time run_task returns, so read the files list off the
        # trace — the reliable source available here without re-reading
        # metrics.json. n_service_errors / verify_insensitive come straight off
        # the trace too.
        fds = tr.final_diff_summary
        made_source_changes = bool(fds is not None and fds.files)
        # run.finished is DEFERRED, not published here: a phased run calls
        # run_task once per phase, and emitting per phase marked the run "done"
        # after the first phase. Stash the latest result and flush exactly ONE
        # run.finished per run — when the next run's workdir appears, or via
        # RunSession.flush() at session end. For phased the stash is the LAST
        # phase's trace (partial verify/duration); the authoritative whole-run
        # trace is trace.json, written by the runner after orchestration.
        self._pending_finish = {
            "type": "run.finished",
            "session_id": self._session_id,
            "batch_id": self._batch_id,
            "run_idx": run_idx,
            "total_runs": self._total_runs,
            "condition": cond.name,
            "rep": rep,
            "finished": tr.finished,
            "interrupted_reason": tr.interrupted_reason,
            "n_service_errors": tr.n_service_errors,
            "made_source_changes": made_source_changes,
            "verify_insensitive": tr.verify_insensitive,
            # Wall-clock seconds the agent actually ran (spawn→exit; excludes any
            # 429 backoff, which happens between attempts). Drives the live ETA.
            "duration_s": (
                tr.ended_at - tr.started_at
                if tr.ended_at is not None and tr.started_at is not None
                else None
            ),
            "verify": {
                "status": tr.verify_status,
                "passed_count": tr.verify_passed_count,
                "failed_count": tr.verify_failed_count,
                "failed_names": list(tr.verify_failed_names) if tr.verify_failed_names else [],
                "command": tr.verify_command,
                "duration_s": tr.verify_duration_s,
            },
        }

        return result

    def _flush_finished(self) -> None:
        """Emit the stashed run.finished for the run that just ended (if any)."""
        if self._pending_finish is not None:
            self._publish(self._pending_finish)
            self._pending_finish = None

    def flush(self) -> None:
        """Flush the final run's deferred run.finished. RunSession calls this at
        session end, where no later workdir arrives to trigger the flush."""
        self._flush_finished()

    def control_event(self, event: dict) -> None:
        """Publish a phased-orchestrator event (phase hand-off / controller
        action) for the CURRENT run as a raw_event, so the live stream shows what
        the orchestrator is doing. VISUALIZATION ONLY — these are never written to
        events.jsonl nor counted in metrics (controller steps are excluded there),
        so they cannot affect the cross-trace comparison."""
        if self._cur_cond is None:
            return
        self._publish({
            "type": "raw_event",
            "session_id": self._session_id,
            "run_idx": self._cur_run_idx,
            "condition": self._cur_cond.name,
            "rep": self._cur_rep,
            "event": event,
        })


class RunSession:
    def __init__(
        self,
        id: str,
        experiment: Experiment,
        client_factory: Callable[[Experiment], object],
        publish: Callable[[dict], None],
        batch_id: str | None = None,
        isolated: bool = False,
    ):
        self.id = id
        self.experiment = experiment
        self._client_factory = client_factory
        self._publish = publish
        # Exposed (LAN) mode: keys are per-session, so the preflight must not warn
        # about a "missing" key that actually arrives via the session store.
        self._isolated = isolated
        # One batch id per session; reused across every run it writes so the
        # server/UI can group + replay this batch (Task 1 on-disk layout).
        self.batch_id = batch_id or default_batch_id()
        self.state = SessionState.PENDING
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self._thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()
        # The per-run publishing wrapper, captured so we can flush its deferred
        # final run.finished at session end (see _PerRunPublishingClient.flush).
        self._wrapper: "_PerRunPublishingClient | None" = None
        self._context_window: "int | None" = None
        # Plan-tracking attributes
        self.plan: list = []
        self.current_idx: int = 0
        self.total_runs: int = 0
        self._current_condition: str | None = None
        self._current_rep: int | None = None

    @property
    def current_condition(self) -> str | None:
        return self._current_condition

    @property
    def current_rep(self) -> int | None:
        return self._current_rep

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("RunSession already started")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Cooperative cancel. Sets the cancel Event, which is threaded down to
        the running opencode subprocess (killed promptly) and checked before
        each remaining run so the loop breaks."""
        self._cancel_flag.set()

    def _position_callback(self, idx: int, condition: str, rep: int) -> None:
        """Called by _PerRunPublishingClient on each run_task entry."""
        self.current_idx = idx
        self._current_condition = condition
        self._current_rep = rep

    def _publish_phase(self, payload: dict) -> None:
        """Relay a fine-grained setup/progress signal from the runner as a
        run.phase envelope, so the UI can show what's happening during the
        otherwise-silent startup window (baseline verify, workdir prep, 429
        backoff) before the model produces its first event."""
        self._publish({"type": "run.phase", "session_id": self.id, **payload})

    def _run(self) -> None:
        self.state = SessionState.RUNNING
        self.started_at = time.time()

        # Compute the execution plan so RunSession and _PerRunPublishingClient
        # share the same shuffled ordering.
        self.plan = compute_plan(self.experiment)
        self.total_runs = len(self.plan)

        # Resolve the model's context window ONCE (override or best-effort fetch)
        # so the live UI can show "% of context used"; passed to run_experiment
        # below to avoid a duplicate fetch.
        from abench.model_limits import resolve_context_window
        try:
            self._context_window = resolve_context_window(self.experiment)
        except Exception:
            self._context_window = None

        iso = self.experiment.isolation
        self._publish({
            "type": "session.started",
            "session_id": self.id,
            "batch_id": self.batch_id,
            "model": self.experiment.model,
            "total_runs": self.total_runs,
            "conditions": [c.name for c in self.experiment.conditions],
            "isolation": {
                "nonce_prefix": iso.nonce_prefix,
                "shuffle_order": iso.shuffle_order,
            },
            "model_context_window": self._context_window,
        })

        def wrapped_factory(exp: Experiment):
            inner = self._client_factory(exp)
            self._wrapper = _PerRunPublishingClient(
                inner=inner,
                publish=self._publish,
                session_id=self.id,
                total_runs=self.total_runs,
                plan=self.plan,
                position_callback=self._position_callback,
                batch_id=self.batch_id,
            )
            return self._wrapper

        try:
            run_experiment(self.experiment, wrapped_factory, _plan=self.plan,
                           batch_id=self.batch_id, cancel_event=self._cancel_flag,
                           progress=self._publish_phase,
                           context_window=self._context_window,
                           isolated=self._isolated)
            if self._cancel_flag.is_set():
                self.state = SessionState.CANCELLED
            else:
                self.state = SessionState.COMPLETED
        except Exception as exc:
            self.state = SessionState.FAILED
            self._publish({
                "type": "session.error",
                "session_id": self.id,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })
        finally:
            # Emit the LAST run's deferred run.finished before the session ends —
            # no later workdir arrives to trigger its flush. Best-effort.
            if self._wrapper is not None:
                try:
                    self._wrapper.flush()
                except Exception:
                    pass
            self.ended_at = time.time()
            duration = self.ended_at - (self.started_at or self.ended_at)
            self._publish({
                "type": "session.finished",
                "session_id": self.id,
                "duration_s": duration,
            })
