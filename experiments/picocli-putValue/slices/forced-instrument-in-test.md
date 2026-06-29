# Methodology (required): observe the runtime data flow before you implement

The exact behaviour this method must produce is pinned by the tests that
exercise it. You usually cannot derive that behaviour by reading code alone —
so do not guess it and do not model it in your head. **Observe it at runtime
first**, then write the implementation against what you actually saw.

Follow these steps in order:

1. **Find the test(s) that exercise the target method** (grep the test sources
   for the method name and for the types it touches).
2. **Pick the 1–3 most revealing tests** — the ones whose inputs are non-trivial
   or whose expected output you do not fully understand.
3. **Instrument those tests with temporary `System.out.println` statements** to
   make the data flow visible at the points you are unsure about:
   - the arguments the method receives,
   - the relevant intermediate state (query the objects through their own
     accessors — e.g. dump each cell, row count, column definitions),
   - the **actual vs. expected** value the assertion compares.
   Prefix every probe line with `[probe]` so you can grep it out of the output.
4. **Run only those tests and read the `[probe]` output.** On Gradle, run the
   single test with `--info` and grep your marker, e.g.

       ./gradlew test --tests 'picocli.HelpTest.testTextTable' --info 2>&1 | grep '\[probe\]'

   (Gradle captures test `System.out`; `--info` surfaces it on the console.)
5. **Write or correct the method body using the values you observed** — not from
   assumption. If you are still unsure after one round, add more probes and run
   again. Re-run after each implementation change to confirm the data flow now
   matches what the assertion expects.
6. **Remove every probe** you added once the implementation is correct.

## Rules for instrumentation

- **This overrides the "do not edit tests / modify only CommandLine.java" rule
  above — but ONLY for temporary observation.** You may add `System.out.println`
  to test files to watch the data flow. You may NOT change assertions, test
  inputs, or any test logic, and you must restore the tests to their original
  state before you finish.
- **Probes go in TEST files only — never in `CommandLine.java`.** The graded
  artifact is your `putValue` implementation; keep it free of debug output.
- **Instrument the EXISTING test, not a new standalone program.** The existing
  test already constructs the fixture correctly and already compiles against the
  project. Re-building the fixture yourself in a scratch `main` wastes effort on
  setup that is irrelevant to the task.
- To inspect intermediate state the assertion does not print, call the type's
  own public/package accessors from inside the test (for a table, that means the
  per-cell text, the row count, and each column's width/indent/overflow).
- For reassurance: the harness restores all test files to their original state
  before grading, so your temporary probes can never affect the verdict — the
  only thing graded is your `putValue` body. Still, leave your working tree tidy.

## Example (Java / JUnit)

Inside the existing test that already builds the table and calls the method, add
temporary probes, run, read, then delete them:

    // --- TEMP PROBE (remove before finishing) ---
    System.out.println("[probe] rowCount=" + tt.rowCount());
    for (int r = 0; r < tt.rowCount(); r++) {
        for (int c = 0; c < tt.columns().length; c++) {
            System.out.println("[probe] cell(" + r + "," + c + ")='"
                + tt.textAt(r, c).toString().replace("\n", "\\n") + "'");
        }
    }
    System.out.println("[probe] ACTUAL>>>\n" + tt.toString() + "\n<<<ACTUAL");
    // --- END TEMP PROBE ---

Seeing the real per-cell contents and the real rendered output — rather than
imagining them — is what lets you get the indentation, wrapping, and overflow
behaviour right on the first implementation instead of guessing.
