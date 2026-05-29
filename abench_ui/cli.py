"""`abench-ui` console-script — starts the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from .server import create_app


def _static_index_path() -> Path:
    """Path to the SPA's index.html. Extracted as a function so tests can
    monkeypatch it without mutating the real build artefact on disk."""
    return Path(__file__).resolve().parent / "static" / "index.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench-ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--experiments-dir",
        default="experiments",
        help="path to the experiments/ directory",
    )
    parser.add_argument(
        "--skip-bundle-check",
        action="store_true",
        help="boot without the SPA bundle (API-only mode, for tests)",
    )
    args = parser.parse_args(argv)

    if not args.skip_bundle_check and not _static_index_path().is_file():
        print(
            "abench-ui: SPA bundle not found at abench_ui/static/index.html.\n"
            "Build the frontend first:\n"
            "    cd web && npm install && npm run build\n"
            "Or re-run with --skip-bundle-check for API-only mode.",
            file=sys.stderr,
        )
        return 2

    app = create_app(experiments_dir=Path(args.experiments_dir).resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
