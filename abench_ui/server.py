"""FastAPI application — REST + WS, in-process abench runner."""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable

from contextlib import asynccontextmanager

from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from abench import report
from abench.config import Experiment
from abench.opencode_client import RealOpenCodeClient

from . import experiments as exp_mod
from . import providers as prov_mod
from . import runs as runs_mod
from .run_session import RunSession, SessionState
from .schema import experiment_json_schema
from . import validate as validate_mod
from .validate import validate_model
from .ws_buffer import SessionEventBuffer


# ── Pydantic request models ──────────────────────────────────────────────────

class _ValidateModelBody(BaseModel):
    model: str


class _CredentialsBody(BaseModel):
    api_key: str


class _RunStartBody(BaseModel):
    experiment_name: str


class _SuccessPatchBody(BaseModel):
    success: bool | None = None


class _VerifyStartBody(BaseModel):
    name: str
    condition: str | None = None
    rep: int | None = None
    batch: str | None = None


# ── Module helpers ─────────────────────────────────────────────────────────

def _verify_system_label(command: str | None) -> str | None:
    if not command:
        return None
    first = command.split()[0]
    if first in ("mvn", "./mvnw"):
        return "maven"
    if first in ("gradle", "./gradlew"):
        return "gradle"
    if first == "pytest":
        return "pytest"
    return "custom"


# ── App factory ──────────────────────────────────────────────────────────────

def create_app(
    *,
    experiments_dir: Path,
    client_factory_override: Callable | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI app rooted at `experiments_dir`.

    If `client_factory_override` is provided, RunSession uses it instead of
    constructing a RealOpenCodeClient — the test seam."""
    state: dict = {
        "experiments_dir": Path(experiments_dir),
        "sessions": {},       # sid -> RunSession
        "buffers": {},        # sid -> SessionEventBuffer
        "ws_queues": {},      # sid -> list[asyncio.Queue]
        "verify_jobs": {},    # vid -> job dict
        "client_factory_override": client_factory_override,
        "event_loop": None,   # captured on startup
    }

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        state["event_loop"] = asyncio.get_running_loop()
        yield

    app = FastAPI(title="abench-ui", version="0.1.0", lifespan=_lifespan)
    app.state.abench = state

    api = APIRouter(prefix="/api")

    # ── Path-traversal guard ─────────────────────────────────────────────────

    def _exp_dir_for(name: str) -> Path:
        """Resolve experiments_dir/<name> and refuse path-traversal."""
        root = state["experiments_dir"].resolve()
        target = (root / name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(400, "invalid experiment name")
        return target

    # ── Schema ──────────────────────────────────────────────────────────────

    @api.get("/schema")
    def _schema():
        return experiment_json_schema()

    # ── Experiments CRUD ────────────────────────────────────────────────────

    @api.get("/experiments")
    def _list_exp():
        return exp_mod.list_experiments(state["experiments_dir"])

    @api.post("/experiments/upload")
    async def _upload_exp(request: Request):
        """Parse a raw YAML body → return resolved Experiment payload.
        Does NOT persist anything. Returns 422 on YAML or pydantic errors."""
        import yaml as _yaml

        body = (await request.body()).decode("utf-8")
        try:
            data = _yaml.safe_load(body)
        except _yaml.YAMLError as exc:
            raise HTTPException(422, f"invalid YAML: {exc}")
        if not isinstance(data, dict):
            raise HTTPException(422, "top-level YAML must be a mapping")
        try:
            exp = Experiment(**data)
        except (ValidationError, Exception) as exc:
            raise HTTPException(422, str(exc))
        return exp.model_dump(mode="json")

    @api.get("/experiments/{name}")
    def _read_exp(name: str):
        _exp_dir_for(name)  # traversal guard
        try:
            return exp_mod.read_experiment(state["experiments_dir"], name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, f"experiment '{name}' not found")

    @api.get("/experiments/{name}/verify_command")
    def _detect_verify_command(name: str):
        from abench.config import load_experiment
        from abench.verify import detect_verify

        exp_dir = _exp_dir_for(name)
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.is_file():
            raise HTTPException(404, f"experiment '{name}' not found")
        try:
            exp = load_experiment(yaml_path)
            if exp.verify.command:
                return {"command": exp.verify.command,
                        "system": _verify_system_label(exp.verify.command),
                        "ambiguous": False, "candidates": []}
            d = detect_verify(exp.fixture_path)
            return {"command": d.command, "system": d.system,
                    "ambiguous": d.ambiguous, "candidates": d.candidates}
        except Exception:
            return {"command": None, "system": None, "ambiguous": False, "candidates": []}

    @api.put("/experiments/{name}")
    async def _write_exp(name: str, request: Request):
        _exp_dir_for(name)  # traversal guard
        payload = await request.json()
        # Validate via pydantic round-trip before writing.
        # Pydantic enforces repetitions >= 1 via Field(ge=1).
        try:
            Experiment(**payload)
        except (ValidationError, Exception) as exc:
            raise HTTPException(422, str(exc))
        exp_mod.write_experiment(state["experiments_dir"], name, payload)
        return {"ok": True}

    @api.delete("/experiments/{name}")
    def _delete_exp(name: str):
        target = _exp_dir_for(name)
        if not target.is_dir():
            raise HTTPException(404, f"experiment '{name}' not found")
        shutil.rmtree(target)
        return {"ok": True}

    # ── Runs (read-only artefacts + PATCH success) ───────────────────────────

    def _resolve_runs_dir(name: str, batch: str | None) -> Path:
        """Resolve <exp>/runs/<exp> for the chosen batch (newest by default,
        legacy flat layout as a fallback). 404 if it can't be resolved."""
        root = _exp_dir_for(name) / "runs" / name
        rd = runs_mod.batch_runs_dir(root, batch)
        if rd is None:
            raise HTTPException(404, f"no runs for '{name}'"
                                + (f" batch '{batch}'" if batch else ""))
        return rd

    @api.get("/runs/{name}/batches")
    def _list_batches(name: str):
        root = _exp_dir_for(name) / "runs" / name
        return runs_mod.list_batches(root)

    @api.get("/runs/{name}")
    def _list_runs(name: str, batch: str | None = None):
        root = _exp_dir_for(name) / "runs" / name
        rd = runs_mod.batch_runs_dir(root, batch)
        if rd is None:
            # No runs at all (or bad batch). Preserve the historical "empty
            # list" behaviour only when NO batch was requested and there are
            # simply no runs yet; an explicit bad batch is a 404.
            if batch:
                raise HTTPException(404, f"no runs for '{name}' batch '{batch}'")
            return []
        return runs_mod.list_runs(rd)

    @api.get("/runs/{name}/summary")
    def _runs_summary(name: str, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        return report.summary_json(rd)

    @api.get("/runs/{name}/{condition}/{rep}/metrics")
    def _read_metrics(name: str, condition: str, rep: int, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return json.loads(
                runs_mod.read_artefact(rd, condition, rep, "metrics.json")
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/trace")
    def _read_trace(name: str, condition: str, rep: int, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return json.loads(
                runs_mod.read_artefact(rd, condition, rep, "trace.json")
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/patch")
    def _read_patch(name: str, condition: str, rep: int, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return Response(
                runs_mod.read_artefact(rd, condition, rep, "changes.patch"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/events")
    def _read_events(name: str, condition: str, rep: int, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return Response(
                runs_mod.read_artefact(rd, condition, rep, "events.jsonl"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/verify_log")
    def _read_verify_log(name: str, condition: str, rep: int, batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return Response(
                runs_mod.read_artefact(rd, condition, rep, "verify_output.log"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/run_log")
    def _read_run_log(name: str, condition: str, rep: int,
                      batch: str | None = None, tail_bytes: int | None = None):
        """Raw run.log. With ?tail_bytes=N, return only the last N chars (from a
        line boundary) prefixed with a truncation notice — run.log can be many MB
        for a verbose build, and rendering all of it freezes the browser. Omit
        tail_bytes (or 0) for the full log (download)."""
        rd = _resolve_runs_dir(name, batch)
        try:
            text = runs_mod.read_artefact(rd, condition, rep, "run.log")
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))
        if tail_bytes and tail_bytes > 0 and len(text) > tail_bytes:
            shown = text[-tail_bytes:]
            nl = shown.find("\n")  # start at a line boundary, not mid-line
            if nl != -1:
                shown = shown[nl + 1:]
            notice = (
                f"[abench] run.log is large — showing the last {len(shown)} of "
                f"{len(text)} characters (use “Download full log” for everything)\n"
                f"{'-' * 60}\n"
            )
            text = notice + shown
        return Response(text, media_type="text/plain")

    @api.get("/runs/{name}/{condition}/{rep}/method_comparison")
    def _method_comparison(name: str, condition: str, rep: int, request: Request,
                           batch: str | None = None):
        """Compare a named method in the reference vs the agent's post-run output
        of the experiment's target_file.  Requires experiment.target_file to be set."""
        exp_dir = _exp_dir_for(name)
        try:
            exp_payload = exp_mod.read_experiment(state["experiments_dir"], name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, "experiment not found")
        target_file = exp_payload.get("target_file")
        if not target_file:
            raise HTTPException(400, "experiment has no target_file configured")
        reference = exp_dir / "original"
        methods = exp_payload.get("target_methods") or []
        method = request.query_params.get("method") or (methods[0] if methods else "")
        # Use the agent's post-run snapshot of target_file if available;
        # fall back to pre-stripped state which will show divergent for unrun experiments.
        rd = runs_mod.batch_runs_dir(exp_dir / "runs" / name, batch)
        snapshot = (rd / condition / f"rep_{rep}" / "target_after_agent.txt"
                    if rd is not None else None)
        override = snapshot if snapshot is not None and snapshot.is_file() else None
        return runs_mod.method_comparison(
            reference_dir=reference,
            workdir=exp_dir / "stripped",
            target_file=target_file,
            method_name=method,
            regen_file_override=override,
        )

    @api.patch("/runs/{name}/{condition}/{rep}")
    def _patch_run(name: str, condition: str, rep: int, body: _SuccessPatchBody,
                   batch: str | None = None):
        rd = _resolve_runs_dir(name, batch)
        try:
            return runs_mod.patch_success(
                rd, condition, rep, success=body.success
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    # ── Validate / Providers ────────────────────────────────────────────────

    @api.post("/validate/model")
    def _validate(body: _ValidateModelBody):
        r = validate_model(body.model)
        return {"status": r.status, "provider": r.provider, "suggestions": r.suggestions}

    @api.get("/models")
    def _models_catalog():
        # Degrade gracefully: opencode CLI may be absent. Never 500.
        try:
            return validate_mod.list_model_catalog()
        except Exception:  # noqa: BLE001
            return []

    @api.get("/providers")
    def _providers():
        return prov_mod.list_providers()

    @api.post("/providers/{provider}/credentials")
    def _creds(provider: str, body: _CredentialsBody):
        prov_mod.write_credentials(provider, body.api_key)
        # Invalidate the validate caches so the new key takes effect immediately
        # (otherwise the model chip keeps showing "no key" for up to the TTL).
        validate_mod.clear_caches()
        return {"ok": True}

    # ── Session management (POST /runs + GET/DELETE /sessions) ───────────────

    @api.post("/runs")
    def _start_run(body: _RunStartBody):
        try:
            exp_payload = exp_mod.read_experiment(
                state["experiments_dir"], body.experiment_name
            )
        except exp_mod.ExperimentNotFound:
            raise HTTPException(
                404, f"experiment '{body.experiment_name}' not found"
            )
        exp = Experiment(**exp_payload)
        sid = uuid.uuid4().hex
        buf = SessionEventBuffer()
        state["buffers"][sid] = buf
        state["ws_queues"][sid] = []

        loop = state["event_loop"]

        def publish(envelope: dict) -> None:
            # Bake event_id into the envelope before buffering so that
            # replay_from() sends the same enriched envelope as live streaming.
            event_id = buf.next_id()
            envelope_with_id = dict(envelope, event_id=event_id)
            buf.append_with_id(event_id, envelope_with_id)
            if loop is not None:
                for q in list(state["ws_queues"].get(sid, [])):
                    loop.call_soon_threadsafe(q.put_nowait, envelope_with_id)

        client_factory = state["client_factory_override"] or (
            lambda e: RealOpenCodeClient(e.opencode, e.timeout_s)
        )
        session = RunSession(
            id=sid,
            experiment=exp,
            client_factory=client_factory,
            publish=publish,
        )
        state["sessions"][sid] = session
        session.start()
        return {"session_id": sid}

    def _summarize_session(s) -> dict:
        """Status + enough experiment context (name, batch, conditions) that the
        UI can re-open a session by sid alone — e.g. after the live tab was
        closed or the page reloaded (location.state is then gone)."""
        return {
            "session_id": s.id,
            "experiment_name": s.experiment.name,
            "batch_id": s.batch_id,
            "state": s.state.value,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "total_runs": s.total_runs,
            "current_idx": s.current_idx,
            "current_condition": s.current_condition,
            "current_rep": s.current_rep,
            "conditions": [c.name for c in s.experiment.conditions],
        }

    @api.get("/sessions")
    def _list_active_sessions():
        """In-flight sessions (pending/running), newest first, so the UI can
        always offer a way back to a live run after the tab was closed."""
        active = [
            _summarize_session(s)
            for s in state["sessions"].values()
            if s.state.value in ("pending", "running")
        ]
        active.sort(key=lambda x: x["started_at"] or 0, reverse=True)
        return active

    @api.get("/sessions/{sid}")
    def _session_state(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        return _summarize_session(session)

    @api.delete("/sessions/{sid}")
    def _cancel_session(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        session.cancel()
        return {"ok": True}

    # ── Re-verify jobs ────────────────────────────────────────────────────────

    @api.post("/verify")
    def _start_verify(body: _VerifyStartBody):
        from abench.config import load_experiment
        from abench import reverify as reverify_mod

        exp_dir = _exp_dir_for(body.name)
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.is_file():
            raise HTTPException(404, f"experiment '{body.name}' not found")
        exp = load_experiment(yaml_path)

        if body.condition is not None and body.rep is not None:
            targets = [(body.condition, body.rep)]
        else:
            targets = reverify_mod.discover_runs(exp, batch=body.batch)

        vid = uuid.uuid4().hex
        job = {"state": "running", "total": len(targets), "done": 0,
               "current": None, "results": [], "error": None}
        state["verify_jobs"][vid] = job

        def _run_job() -> None:
            try:
                for condition, rep in targets:
                    job["current"] = {"condition": condition, "rep": rep}
                    v = reverify_mod.reverify_run(exp, condition, rep, batch=body.batch)
                    job["results"].append({
                        "condition": condition, "rep": rep, "status": v.status,
                        "reason": v.reason, "message": v.message,
                        "passed_count": v.passed_count, "failed_count": v.failed_count,
                    })
                    job["done"] += 1
                job["current"] = None
                job["state"] = "done"
            except Exception as exc:  # noqa: BLE001
                job["state"] = "error"
                job["error"] = repr(exc)

        threading.Thread(target=_run_job, daemon=True).start()
        return {"verify_id": vid}

    @api.get("/verify/{verify_id}")
    def _verify_job_status(verify_id: str):
        job = state["verify_jobs"].get(verify_id)
        if job is None:
            raise HTTPException(404, "verify job not found")
        return job

    app.include_router(api)

    # ── WebSocket ────────────────────────────────────────────────────────────

    @app.websocket("/ws/sessions/{sid}")
    async def _ws(ws: WebSocket, sid: str):
        await ws.accept()
        if sid not in state["sessions"]:
            # Unknown/expired session (e.g. the server was restarted, dropping
            # in-memory sessions). Tell the client so it shows a message and
            # STOPS reconnecting — otherwise it hammers open/close every 750ms.
            try:
                await ws.send_json({
                    "type": "session.error",
                    "message": ("This run session is no longer available — the server "
                                "may have been restarted. Open the experiment's Results "
                                "to view finished runs."),
                })
            except Exception:
                pass
            await ws.close(code=4004)
            return

        buf: SessionEventBuffer = state["buffers"][sid]
        q: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        state["ws_queues"].setdefault(sid, []).append(q)

        # Replay buffered events from last_event_id onward (for reconnect).
        last_id = int(ws.query_params.get("last_event_id", 0))
        terminal_replayed = False
        for ev in buf.replay_from(last_id):
            await ws.send_json(ev)
            if ev.get("type") in ("session.finished", "session.error"):
                terminal_replayed = True

        # If replay already included the terminal event, no need to stream live.
        if terminal_replayed:
            try:
                state["ws_queues"][sid].remove(q)
            except (KeyError, ValueError):
                pass
            return

        # Stream live events until terminal envelope.
        try:
            while True:
                envelope = await asyncio.wait_for(q.get(), timeout=30.0)
                await ws.send_json(envelope)
                if envelope.get("type") in ("session.finished", "session.error"):
                    break
        except asyncio.TimeoutError:
            # Session may have finished before we connected; check buffer again.
            for ev in buf.replay_from(last_id):
                await ws.send_json(ev)
                if ev.get("type") in ("session.finished", "session.error"):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            try:
                state["ws_queues"][sid].remove(q)
            except (KeyError, ValueError):
                pass

    # ── Static SPA bundle ────────────────────────────────────────────────────
    # Registered AFTER app.include_router(api) and the @app.websocket handler,
    # so API and WS routes win over the catch-all below.
    _static_dir = Path(static_dir) if static_dir is not None else Path(__file__).resolve().parent / "static"
    _index = _static_dir / "index.html"
    if _index.is_file():
        _assets = _static_dir / "assets"
        if _assets.is_dir():
            app.mount("/assets", StaticFiles(directory=_assets), name="assets")

        @app.get("/", include_in_schema=False)
        def _spa_root():
            return FileResponse(_index)

        # Match ALL methods on the catch-all so that an unmatched /api or /ws
        # request (e.g. DELETE /api/experiments/..%2Fetc, which no API route
        # pattern matches) lands here and 404s, rather than the router emitting
        # a misleading 405 because only this GET-only route matched the path.
        # GET on a real SPA route still serves index.html for client-side
        # routing; non-GET on a non-api/ws path is a genuine 404.
        @app.api_route(
            "/{full_path:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
        def _spa_fallback(full_path: str, request: Request):
            # Defence in depth: a stray /api/... or /ws/... with no matching
            # registered route must still 404, not leak index.html.
            if full_path.startswith("api/") or full_path.startswith("ws/"):
                raise HTTPException(404, f"not found: {full_path}")
            # Only GET serves the SPA; other verbs on unknown paths are 404.
            if request.method != "GET":
                raise HTTPException(404, f"not found: {full_path}")
            # Serve a real static asset only if it resolves INSIDE static_dir —
            # refuse path-traversal (e.g. ..%2f..%2fetc%2fpasswd) and fall back
            # to index.html for everything else (client-side routing).
            root = _static_dir.resolve()
            candidate = (root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
            return FileResponse(_index)

    return app
