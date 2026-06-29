## Debugging method for this task (overrides the editing guidance above)

To learn exactly what `putValue` must produce, you ARE permitted — and expected
— to add TEMPORARY `System.out.println` probes and run the tests, then write the
implementation against what you observe. This overrides the earlier "stay
focused on the requested method / do not touch unrelated code / do not invent
your own test files" guidance, within these bounds:

- Add probes to the EXISTING tests that exercise the method, and — when you need
  to see what `putValue` is handed or what its caller does with the return value
  — to the chain methods in `CommandLine.java` (e.g. `addRowValues`, `copy`).
- **Mark every probe line with a trailing `//[probe]` comment** so you (and the
  harness) can find and strip them. Do not change any assertion, test input, or
  test logic — only add prints.
- **Remove every `//[probe]` line once your implementation is correct**, and run
  the full `./gradlew test --continue` suite clean as the final gate.
- Do NOT write standalone programs or scratch `main`s — instrument the existing
  tests, whose fixtures are already correct and already compile.

Search freely for any method, type, or test you need. The step-by-step procedure
and a graph/coverage map of the target are in the task instructions below.
