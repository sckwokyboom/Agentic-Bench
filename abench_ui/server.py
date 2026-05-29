"""FastAPI application — REST + WS, in-process abench runner."""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Callable

from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ValidationError

from abench.config import Experiment
from abench.opencode_client import RealOpenCodeClient

from . import experiments as exp_mod
from . import providers as prov_mod
from . import runs as runs_mod
from .run_session import RunSession, SessionState
from .schema import experiment_json_schema
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


# ── App factory ──────────────────────────────────────────────────────────────

def create_app(
    *,
    experiments_dir: Path,
    client_factory_override: Callable | None = None,
) -> FastAPI:
    """Build the FastAPI app rooted at `experiments_dir`.

    If `client_factory_override` is provided, RunSession uses it instead of
    constructing a RealOpenCodeClient — the test seam."""
    app = FastAPI(title="abench-ui", version="0.1.0")
    state: dict = {
        "experiments_dir": Path(experiments_dir),
        "sessions": {},       # sid -> RunSession
        "buffers": {},        # sid -> SessionEventBuffer
        "ws_queues": {},      # sid -> list[asyncio.Queue]
        "client_factory_override": client_factory_override,
    }
    app.state.abench = state

    api = APIRouter(prefix="/api")

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
        try:
            return exp_mod.read_experiment(state["experiments_dir"], name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, f"experiment '{name}' not found")

    @api.put("/experiments/{name}")
    async def _write_exp(name: str, request: Request):
        payload = await request.json()
        # Validate via pydantic round-trip before writing.
        # Also enforce business rules (e.g. repetitions >= 1) not captured
        # by base pydantic type constraints.
        try:
            Experiment(**payload)
        except (ValidationError, Exception) as exc:
            raise HTTPException(422, str(exc))
        # Extra business-rule validation
        reps = payload.get("repetitions")
        if reps is not None and isinstance(reps, int) and reps < 1:
            raise HTTPException(422, "repetitions must be >= 1")
        exp_mod.write_experiment(state["experiments_dir"], name, payload)
        return {"ok": True}

    @api.delete("/experiments/{name}")
    def _delete_exp(name: str):
        target = state["experiments_dir"] / name
        if not target.is_dir():
            raise HTTPException(404, f"experiment '{name}' not found")
        shutil.rmtree(target)
        return {"ok": True}

    # ── Runs (read-only artefacts + PATCH success) ───────────────────────────

    @api.get("/runs/{name}")
    def _list_runs(name: str):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        return runs_mod.list_runs(runs_dir)

    @api.get("/runs/{name}/{condition}/{rep}/metrics")
    def _read_metrics(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return json.loads(
                runs_mod.read_artefact(runs_dir, condition, rep, "metrics.json")
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/trace")
    def _read_trace(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return json.loads(
                runs_mod.read_artefact(runs_dir, condition, rep, "trace.json")
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/patch")
    def _read_patch(name: str, condition: str, rep: int):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return Response(
                runs_mod.read_artefact(runs_dir, condition, rep, "changes.patch"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    @api.get("/runs/{name}/{condition}/{rep}/method_comparison")
    def _method_comparison(name: str, condition: str, rep: int, request: Request):
        """Compare a named method in the reference vs stripped version of the
        experiment's target_file.  Requires experiment.target_file to be set."""
        try:
            exp_payload = exp_mod.read_experiment(state["experiments_dir"], name)
        except exp_mod.ExperimentNotFound:
            raise HTTPException(404, "experiment not found")
        target_file = exp_payload.get("target_file")
        if not target_file:
            raise HTTPException(400, "experiment has no target_file configured")
        exp_dir = state["experiments_dir"] / name
        reference = exp_dir / "original"
        workdir_proxy = exp_dir / "stripped"  # post-run workdir is gone; use stripped
        methods = exp_payload.get("target_methods") or []
        method = request.query_params.get("method") or (methods[0] if methods else "")
        return runs_mod.method_comparison(
            reference_dir=reference,
            workdir=workdir_proxy,
            target_file=target_file,
            method_name=method,
        )

    @api.patch("/runs/{name}/{condition}/{rep}")
    def _patch_run(name: str, condition: str, rep: int, body: _SuccessPatchBody):
        runs_dir = state["experiments_dir"] / name / "runs" / name
        try:
            return runs_mod.patch_success(
                runs_dir, condition, rep, success=body.success
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))

    # ── Validate / Providers ────────────────────────────────────────────────

    @api.post("/validate/model")
    def _validate(body: _ValidateModelBody):
        r = validate_model(body.model)
        return {"status": r.status, "provider": r.provider, "suggestions": r.suggestions}

    @api.get("/providers")
    def _providers():
        return prov_mod.list_providers()

    @api.post("/providers/{provider}/credentials")
    def _creds(provider: str, body: _CredentialsBody):
        prov_mod.write_credentials(provider, body.api_key)
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

        def publish(envelope: dict) -> None:
            buf.append(envelope)
            for q in list(state["ws_queues"].get(sid, [])):
                try:
                    q.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass

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

    @api.get("/sessions/{sid}")
    def _session_state(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        return {
            "state": session.state.value,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
        }

    @api.delete("/sessions/{sid}")
    def _cancel_session(sid: str):
        session = state["sessions"].get(sid)
        if session is None:
            raise HTTPException(404, "session not found")
        session.cancel()
        return {"ok": True}

    app.include_router(api)

    # ── WebSocket ────────────────────────────────────────────────────────────

    @app.websocket("/ws/sessions/{sid}")
    async def _ws(ws: WebSocket, sid: str):
        await ws.accept()
        if sid not in state["sessions"]:
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

    return app
