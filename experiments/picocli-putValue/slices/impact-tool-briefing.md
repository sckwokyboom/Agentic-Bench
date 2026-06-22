# Tooling note: `impact`

This session provides an `impact` command (allowed — part of the task
environment, not an external source). It has two modes.

## `impact` — which tests to run

Run it from the shell with no arguments, AFTER you have edited the method (it
reads your uncommitted diff, so before any edit it has nothing to report):

    impact

It prints, per changed method, the tests that cover it (most-relevant,
name-matched tests first) and a **ready-to-paste, blast-radius-aware test
command**:

- If your change is **narrow**, it gives a focused `--tests …` command to run
  while iterating, then the full-suite command to confirm before you finish.
- If your change is **broad** (it touches code many tests exercise), a focused
  subset would hide failures elsewhere — so it tells you to run the **full
  suite** instead. Trust that over any green subset.

The command it prints already uses the correct invocation for this project
(e.g. `./gradlew :test`) — paste it as-is.

## `impact failures` — what your change broke

After a test run, pipe its output to attribute the failures:

    ./gradlew :test --continue 2>&1 | impact failures

It splits the failing tests into **caused by a method you changed** (fix these
first) vs **not covered by your change** (likely pre-existing, unrelated, or
flaky). Use it on a broad change to separate your regressions from noise.

## The loop

1. Edit the body of the target method.
2. Run `impact` → run the command it prints.
3. If tests fail, pipe the output through `impact failures` to see which are
   yours, and fix those.
4. Re-run `impact` after each further edit. Before declaring done, run the FULL
   suite and make sure it is green.
