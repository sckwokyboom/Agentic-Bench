"""Multi-factor regression gate for the diagnose loop.

`failed_count` alone is unsafe: a drop can hide tests that stopped running or
got skipped, or a worse scenario breaking while a trivial one is fixed. Accept a
round only if it compiles, the suite actually ran, no fewer tests executed, and
it strictly improved (more passing, or fewer failures with no new errors/skips).
The orchestrator confirms a regression by re-running the newly-failing tests
before reverting (flaky-robustness lives in the caller; this decision is pure).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SuiteResult:
    compiled: bool
    ran: bool                 # the suite executed (vs a build/infra error)
    executed: int             # number of tests that actually ran
    passed: int
    failed: int
    errors: int = 0
    skipped: int = 0


def decide(before: SuiteResult, after: SuiteResult) -> tuple[bool, str]:
    """Return (accept, reason). Accept => keep the edit as the new best."""
    if not after.compiled:
        return False, "does not compile"
    if not after.ran:
        return False, "test suite did not run (infra error)"
    if after.executed < before.executed:
        return False, (f"fewer tests executed ({after.executed} < {before.executed}) "
                       "— a failure-count drop here is not real progress")
    if after.errors > before.errors:
        return False, f"new errors ({before.errors} -> {after.errors})"
    if after.skipped > before.skipped:
        return False, f"more skipped ({before.skipped} -> {after.skipped})"
    if after.passed > before.passed:
        return True, f"more passing ({before.passed} -> {after.passed})"
    if after.failed < before.failed:
        return True, f"fewer failures ({before.failed} -> {after.failed})"
    return False, "no improvement"
