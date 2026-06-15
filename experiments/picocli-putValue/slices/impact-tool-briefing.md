# Tooling note: `impact`

This session provides a built-in tool named `impact` (allowed — part of the
task environment, not an external source). Invoke it AS A TOOL (it takes no
arguments). Do NOT run it through the shell / `bash` — call the tool directly.

What it does: analyzes YOUR CURRENT uncommitted diff and returns, per touched
method: Tier-1 VERIFIER tests (cover AND kill mutants), Tier-2 coverers (final
validation only), and mutation BLIND SPOTS — changed lines the suite cannot
detect (a green run there proves nothing; re-read the contract).

IMPORTANT — timing: `impact` reads your DIFF, so it is only useful AFTER you
have edited the method. Calling it before any edit returns nothing.

Work in this loop:
1. Edit the body of `putValue`.
2. Call the `impact` tool → it names the Tier-1 tests for your change.
3. Run exactly those, e.g. `./gradlew test --tests 'picocli.HelpTest.<name>'`,
   and fix what fails.
4. Re-call `impact` after each further edit. Treat blind-spot warnings as
   "the suite will not catch a mistake here — verify the contract by hand".
