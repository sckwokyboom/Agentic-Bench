#!/usr/bin/env python3
"""poke_opencode.py — a tiny standalone way to drive OpenCode with a DeepSeek key.

What it does
------------
1. Takes a DeepSeek API key (``--api-key`` / ``$DEEPSEEK_API_KEY`` / interactive
   prompt) and writes it into OpenCode's ``auth.json`` under the ``deepseek``
   provider — the same file/shape OpenCode's own ``providers login`` produces.
2. Runs ``opencode run --format json`` as a subprocess in a working directory,
   pinning both ``model`` and ``small_model`` via a temporary ``opencode.json``
   (pinning ``small_model`` is required: its default is a *paid* model, which
   makes background tasks fail with HTTP 402 and abort the whole run).
3. Reads the JSONL event stream live, prints a one-line summary per event to
   **stderr**, and prints the model's final answer to **stdout** (so you can pipe
   the answer while still watching progress).

Standalone: only the Python standard library, plus the ``opencode`` CLI on PATH.
No ``pip install`` and no dependency on the surrounding ``abench`` package.

Run ``python3 scripts/poke_opencode.py --help`` for options; see scripts/README.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

DEFAULT_MODEL = "deepseek/deepseek-chat"
PROVIDER = "deepseek"

# Exit codes
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_BINARY = 127
EXIT_TIMEOUT = 124


# ── small helpers ───────────────────────────────────────────────────────────
def log(msg: str = "") -> None:
    """Print to stderr (the live progress channel) and flush."""
    print(msg, file=sys.stderr, flush=True)


def truncate(text: str, n: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def auth_path() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def write_deepseek_key(api_key: str) -> Path:
    """Merge the DeepSeek key into OpenCode's auth.json (atomic write)."""
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            data = {}
    data[PROVIDER] = {"type": "api", "key": api_key}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-auth-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def resolve_api_key(args: argparse.Namespace) -> str | None:
    """Return the DeepSeek key from flag, env, or an interactive prompt.

    Returns None only when the user opted out of writing a key (--no-write-key).
    """
    if args.no_write_key:
        return None
    if args.api_key:
        return args.api_key.strip()
    env = os.environ.get("DEEPSEEK_API_KEY")
    if env:
        return env.strip()
    if sys.stdin.isatty() or sys.stderr.isatty():
        import getpass

        key = getpass.getpass("DeepSeek API key (input hidden): ").strip()
        if key:
            return key
    log(
        "error: no DeepSeek key. Pass --api-key, set $DEEPSEEK_API_KEY, "
        "or use --no-write-key if it is already configured in opencode."
    )
    sys.exit(EXIT_ERROR)


def read_prompt(args: argparse.Namespace) -> str:
    """Resolve the user prompt: positional arg, --prompt-file, or stdin."""
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            return text
    log("error: no prompt. Pass it as an argument, via --prompt-file, or on stdin.")
    sys.exit(EXIT_ERROR)


# ── event summarising (mirrors abench's normalizer's view of the stream) ─────
def summarize_event(event: dict) -> str | None:
    """One human-readable line for an OpenCode JSONL event, or None to skip.

    Naming gotcha (from the verified API notes): the envelope ``type`` is
    snake_case (``tool_use``/``step_finish``) while ``part.type`` is hyphenated
    (``tool``/``step-finish``). We key off ``part.type`` like the harness does.
    """
    etype = event.get("type")
    part = event.get("part") or {}
    ptype = part.get("type")

    if ptype == "text":
        snippet = truncate(part.get("text") or "", 160)
        return f"  [llm ] {snippet}" if snippet else None

    if ptype == "reasoning":
        snippet = truncate(part.get("text") or "", 120)
        return f"  [think] {snippet}" if snippet else "  [think]"

    if ptype == "tool":
        name = part.get("tool") or "?"
        state = part.get("state") or {}
        status = state.get("status")
        args = state.get("input") or {}
        hint = (
            args.get("command")
            or args.get("filePath")
            or args.get("path")
            or args.get("pattern")
            or ""
        )
        tag = {"completed": "ok ", "error": "err"}.get(status, "...")
        return f"  [tool] {tag} {name} {truncate(str(hint), 100)}".rstrip()

    if ptype in ("step-finish", "step_finish") or etype == "step_finish":
        tokens = part.get("tokens") or {}
        total = tokens.get("total")
        cost = part.get("cost")
        bits = []
        if total is not None:
            bits.append(f"{total} tok")
        if cost is not None:
            bits.append(f"${cost:.6f}")
        return f"  [step] {' · '.join(bits)}" if bits else None

    if etype == "error" or ptype == "error":
        return f"  [ERR ] {truncate(json.dumps(event), 240)}"

    return None


def collect_answer_text(event: dict, by_message: dict[str, list[str]], order: list[str]) -> None:
    """Accumulate assistant text parts keyed by messageID so we can print the
    final assistant message cleanly at the end."""
    part = event.get("part") or {}
    if part.get("type") != "text":
        return
    text = part.get("text") or ""
    if not text:
        return
    mid = part.get("messageID") or "_"
    if mid not in by_message:
        by_message[mid] = []
        order.append(mid)
    by_message[mid].append(text)


# ── the run ──────────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> int:
    binary = shutil.which(args.binary) or (args.binary if Path(args.binary).exists() else None)
    if not binary:
        log(f"error: '{args.binary}' not found on PATH. Install it: npm i -g opencode-ai")
        return EXIT_NO_BINARY

    prompt = read_prompt(args)

    key = resolve_api_key(args)
    if key:
        path = write_deepseek_key(key)
        log(f"[poke] wrote DeepSeek key → {path}")

    # Working directory: a throwaway temp dir unless the user pins one.
    created_tmp = False
    if args.dir:
        workdir = Path(args.dir).expanduser().resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="poke-opencode-"))
        created_tmp = True

    small_model = args.small_model or args.model
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": args.model,
        "small_model": small_model,
    }

    # Write opencode.json into the workdir, preserving any existing one so we
    # never clobber a real project's config.
    cfg_path = workdir / "opencode.json"
    original_cfg = cfg_path.read_bytes() if cfg_path.is_file() else None

    rc = EXIT_OK
    watchdog: threading.Timer | None = None
    try:
        cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        cmd = [
            binary, "run",
            "--format", "json",
            "--print-logs",
            "--log-level", "INFO",
            "--dir", str(workdir),
            "--model", args.model,
            "--dangerously-skip-permissions",
        ]
        if args.agent:
            cmd += ["--agent", args.agent]
        cmd.append(prompt)

        log(f"[poke] model={args.model}  small_model={small_model}  dir={workdir}")
        log(f"[poke] $ {' '.join(cmd[:8])} … \"<prompt>\"")
        log("")

        # stderr: inherit (stream opencode's INFO logs) only with --verbose;
        # otherwise discard so its verbose log can't fill the pipe and deadlock.
        stderr_dest = None if args.verbose else subprocess.DEVNULL
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=stderr_dest,
            cwd=str(workdir),
            env=os.environ.copy(),
        )

        # Wall-clock timeout: a one-shot watchdog kills the process; reading
        # stdout stays single-threaded.
        timed_out = threading.Event()

        def _kill_on_timeout() -> None:
            timed_out.set()
            proc.kill()

        watchdog = threading.Timer(args.timeout, _kill_on_timeout)
        watchdog.daemon = True
        watchdog.start()

        by_message: dict[str, list[str]] = {}
        order: list[str] = []
        saw_rate_limit = False

        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # forwards-compat: skip non-JSON / log preamble lines
            summary = summarize_event(event)
            if summary is not None:
                log(summary)
            collect_answer_text(event, by_message, order)
            if event.get("type") == "error":
                payload = event.get("error") or event.get("part") or {}
                if isinstance(payload, dict):
                    status = payload.get("statusCode") or payload.get("status") or payload.get("code")
                    if str(status) == "429":
                        saw_rate_limit = True

        proc.wait()
        watchdog.cancel()

        log("")
        if timed_out.is_set():
            log(f"[poke] ✗ timed out after {args.timeout}s")
            return EXIT_TIMEOUT
        if saw_rate_limit:
            log("[poke] ✗ rate limited (HTTP 429) — slow down or check your DeepSeek quota")
            return EXIT_ERROR
        if proc.returncode != 0:
            log(f"[poke] ✗ opencode exited with code {proc.returncode}"
                + ("" if args.verbose else " (re-run with --verbose for opencode's logs)"))
            rc = EXIT_ERROR

        # Final answer = the text parts of the last assistant message.
        answer = "\n".join(by_message[order[-1]]) if order else ""
        log("=" * 60)
        log("ANSWER" + ("" if answer else "  (no text produced — tools only?)"))
        log("=" * 60)
        if answer:
            print(answer)  # stdout: clean, pipe-able
        return rc

    finally:
        if watchdog is not None:
            watchdog.cancel()
        # Restore / remove our opencode.json, then drop the temp workdir.
        try:
            if original_cfg is not None:
                cfg_path.write_bytes(original_cfg)
            elif cfg_path.is_file():
                cfg_path.unlink()
        except OSError:
            pass
        if created_tmp and not args.keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        elif created_tmp:
            log(f"[poke] kept workdir: {workdir}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poke_opencode.py",
        description="Drive OpenCode with a DeepSeek key and print the answer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 scripts/poke_opencode.py --api-key sk-... \"What is 2+2? Reply with just the number.\"\n"
            "  DEEPSEEK_API_KEY=sk-... python3 scripts/poke_opencode.py \"List files here\" --dir .\n"
            "  echo \"Explain this repo\" | python3 scripts/poke_opencode.py --no-write-key --verbose\n"
        ),
    )
    p.add_argument("prompt", nargs="?", help="prompt to send (or use --prompt-file / stdin)")
    p.add_argument("--api-key", help="DeepSeek API key (else $DEEPSEEK_API_KEY, else prompt)")
    p.add_argument("--no-write-key", action="store_true",
                   help="don't touch auth.json — assume opencode already has the key")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"opencode model id (default: {DEFAULT_MODEL})")
    p.add_argument("--small-model", default=None,
                   help="model for background tasks (default: same as --model; "
                        "set to a free model like opencode/mimo-v2.5-free to avoid extra cost)")
    p.add_argument("--dir", help="working directory the agent sees (default: throwaway temp dir)")
    p.add_argument("--agent", default=None, help="opencode agent name (default: opencode's own default)")
    p.add_argument("--prompt-file", help="read the prompt from this file")
    p.add_argument("--timeout", type=float, default=300.0, help="wall-clock timeout in seconds (default: 300)")
    p.add_argument("--verbose", action="store_true", help="stream opencode's own INFO logs to stderr")
    p.add_argument("--keep-workdir", action="store_true", help="don't delete the temp working directory")
    p.add_argument("--binary", default="opencode", help="path to the opencode binary (default: opencode)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        log("\n[poke] interrupted")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
