"""Standalone, stdlib-only model-reachability probe. Runs in the bare sandbox
image (only python3 needed). Sends a 1-token completion to the configured
endpoint and prints a KEY-SCRUBBED JSON verdict to stdout. The key is read from
the env var named by argv[3] — never passed in argv.

Usage:  python3 model_probe.py <base_url> <model> <key_env_name>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def classify(status, body: str, error: str | None) -> tuple[bool, str]:
    """(reachable, reason) from an HTTP status / body / transport error."""
    if error is not None:
        e = error.lower()
        if "certificate" in e or "ssl" in e or "cert_" in e:
            return (False, "tls")
        return (False, "network")
    if status == 200:
        return (True, "ok")
    if status in (401, 403):
        return (False, "auth")
    low = body.lower()
    if status == 404 or (
        status == 400
        and "model" in low
        and ("exist" in low or "not" in low or "found" in low)
    ):
        return (False, "model_not_found")
    return (False, f"http_{status}")


def main(argv: list[str]) -> int:
    base_url, model, key_env = argv[1], argv[2], argv[3]
    key = os.environ.get(key_env, "")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    status = None
    body = ""
    error = None
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read(2048).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read(2048).decode("utf-8", "replace")
        except Exception:
            body = ""
    except Exception as exc:  # URLError, timeout, ssl, etc.
        error = f"{type(exc).__name__}: {exc}"
    reachable, reason = classify(status, body, error)
    detail = scrub((error or body or "")[:300], key)
    print(json.dumps({"reachable": reachable, "reason": reason, "detail": detail}))
    return 0 if reachable else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
