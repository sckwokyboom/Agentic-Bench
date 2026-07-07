"""`abench-ui` console-script — starts the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

import uvicorn

from .server import create_app


def _static_index_path() -> Path:
    """Path to the SPA's index.html. Extracted as a function so tests can
    monkeypatch it without mutating the real build artefact on disk."""
    return Path(__file__).resolve().parent / "static" / "index.html"


def _lan_urls(port: int) -> list[str]:
    """Best-effort list of URLs this host is reachable at on the LAN, so the
    operator can tell teammates what to open. Never raises (no network egress
    is required — a UDP socket only picks the outbound interface)."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))  # TEST-NET-1: no packets sent, just picks the iface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in sorted(ips)]


def _serving_banner(host: str, port: int) -> str:
    if host in ("127.0.0.1", "localhost", "::1"):
        return (f"abench-ui: http://127.0.0.1:{port}  "
                "(local only — pass --expose to serve on the LAN)")
    lines = [f"abench-ui: serving on {host}:{port} — open from another machine at one of:",
             f"    http://127.0.0.1:{port}   (this host)"]
    lines += [f"    {u}" for u in _lan_urls(port)]
    lines.append(
        "  ⚠  EXPOSED ON THE NETWORK: anyone who can reach this host can launch runs, "
        "edit configs, and use whatever API keys are configured. Serve only on a trusted LAN.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench-ui")
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="bind address (default: localhost only). Use 0.0.0.0, or --expose, "
             "to serve on the local network.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--expose", action="store_true",
        help="serve on ALL interfaces (0.0.0.0) so other machines on the LAN can "
             "open the UI. Overrides --host.")
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

    host = "0.0.0.0" if args.expose else args.host
    app = create_app(experiments_dir=Path(args.experiments_dir).resolve())
    print(_serving_banner(host, args.port), file=sys.stderr)
    uvicorn.run(app, host=host, port=args.port, log_level="info")
    return 0
