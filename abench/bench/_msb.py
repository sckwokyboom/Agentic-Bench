"""Multi-SWE-bench native-format helpers (schema accessors; evaluator driver +
report reader come in later Plan-4b tasks). Pinned harness:
github.com/multi-swe-bench/multi-swe-bench @ 24f493f8 (v1.1.0)."""
from __future__ import annotations

from typing import Any


def instance_id(rec: dict) -> str:
    """The harness's id: 'org/repo:pr-<number>'."""
    return f"{rec['org']}/{rec['repo']}:pr-{rec['number']}"


def display_repo(rec: dict) -> str:
    return f"{rec['org']}/{rec['repo']}"


def base_sha(rec: dict) -> str:
    return rec["base"]["sha"]


def image_ref(rec: dict) -> str:
    """Official per-PR image: mswebench/<org>_m_<repo>:pr-<number> (lowercased)."""
    return f"mswebench/{rec['org']}_m_{rec['repo']}:pr-{rec['number']}".lower()


def issue_text(rec: dict) -> str:
    """Canonical issue text: title + body + linked resolved-issue bodies. No gold,
    no tests, no hints (issue-only fidelity, spec §2)."""
    parts: list[str] = []
    if rec.get("title"):
        parts.append(rec["title"].strip())
    if rec.get("body"):
        parts.append(rec["body"].strip())
    for iss in rec.get("resolved_issues") or []:
        t, b = (iss.get("title") or "").strip(), (iss.get("body") or "").strip()
        if t or b:
            parts.append((t + "\n" + b).strip())
    return "\n\n".join(p for p in parts if p)


def prediction_record(rec: dict, fix_patch: str) -> dict[str, Any]:
    """The evaluator's prediction JSONL record — {org, repo, number, fix_patch} ONLY."""
    return {"org": rec["org"], "repo": rec["repo"], "number": rec["number"], "fix_patch": fix_patch}
