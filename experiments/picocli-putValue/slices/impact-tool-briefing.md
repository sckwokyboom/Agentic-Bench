# Tooling note: `impact`

This session provides an `impact` command (allowed — part of the task
environment, not an external source). Run it from the shell with no arguments:

    impact

What it does: reads YOUR CURRENT uncommitted diff and prints, per changed
method, the tests that cover it — so you can run a focused subset instead of the
whole suite.

IMPORTANT — timing: `impact` reads your DIFF, so run it AFTER you have edited the
method. Before any edit it has nothing to report.

Work in this loop:
1. Edit the body of `putValue`.
2. Run `impact` → it lists the tests that cover your change.
3. Run those (or their classes), e.g. `./gradlew test --tests 'picocli.HelpTest'`,
   and fix what fails.
4. Re-run `impact` after each further edit to re-check which tests are affected.
