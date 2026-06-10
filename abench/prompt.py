# abench/prompt.py
from __future__ import annotations

# Ground rules prepended to the system prompt (both conditions) when
# isolation.forbid_external_sources is on. Keeps results reflecting work done
# from the project's own sources/tests rather than a leaked or memorized
# original. NOTE: this is a soft control — the agent runs with skip-permissions,
# so true isolation also needs the original kept off the filesystem / sandboxing.
GROUNDING_GUARD = (
    "# Ground rules (do not violate)\n"
    "- Treat this project directory as the entire world. Work ONLY inside it.\n"
    "- Use ONLY this project's own source files and tests to understand and "
    "solve the task.\n"
    "- Do NOT recover code from version-control history: no `git log`, "
    "`git show`, `git diff`, `git stash`, reflog, or reading anything under "
    "`.git/`.\n"
    "- Do NOT read or fetch anything outside this project: no other "
    "copy/checkout of this project, no absolute paths outside it (even if a "
    "path is mentioned in the task), no other directories, and no network or "
    "internet access.\n"
    "- Write the solution yourself from the project's sources and tests; do not "
    "paste it from an external or remembered copy."
    "\n- Custom tools provided by the harness in this session (e.g. project-local "
    "tools like `impact`) ARE allowed — use them freely; they are part of the task "
    "environment, not an external source."
)


def compose(task: str, augmentation: str | None) -> str:
    task = task.strip()
    if augmentation and augmentation.strip():
        return f"{task}\n\n---\n\n{augmentation.strip()}"
    return task


def build_system_prompt(
    base: str | None,
    *,
    nonce: str | None = None,
    fixture_sha: str | None = None,
    forbid_external_sources: bool = True,
) -> str:
    """Compose the effective system prompt for a run.

    Order: grounding guard (if enabled) → nonce/fixture marker (if any) → the
    experiment's own system prompt. Each block is separated by a blank line.
    """
    parts: list[str] = []
    if forbid_external_sources:
        parts.append(GROUNDING_GUARD)
    if nonce is not None:
        parts.append(f"# abench-run: {nonce}\n# fixture: {fixture_sha or ''}")
    base = (base or "").strip()
    if base:
        parts.append(base)
    return "\n\n".join(parts)
