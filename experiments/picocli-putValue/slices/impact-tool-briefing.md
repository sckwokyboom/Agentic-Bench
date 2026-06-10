# Tooling note: `impact`

This session provides a custom tool named `impact` (it is allowed — it is part
of the task environment, not an external source).

What it does: analyzes YOUR CURRENT diff (uncommitted changes) and returns,
per touched method: Tier-1 VERIFIER tests (cover AND kill mutants — run these
after every edit), Tier-2 coverers (final validation only), and mutation BLIND
SPOTS — changed lines the test suite cannot detect (a green run there proves
nothing; be extra careful and re-read the contract).

How to use it well:
1. After editing the method, call `impact` (no arguments).
2. Run the Tier-1 tests it names instead of the whole suite.
3. Treat blind-spot warnings as "the suite will not catch a mistake here".
