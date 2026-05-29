"""`abench-ui` console-script — starts the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .server import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench-ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--experiments-dir",
        default="experiments",
        help="path to the experiments/ directory",
    )
    args = parser.parse_args(argv)

    app = create_app(experiments_dir=Path(args.experiments_dir).resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
