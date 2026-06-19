# `impact` — example output for the `putValue` task

What the `impact` shell command returns when the agent runs it **after** restoring
`putValue` in this experiment. This is the concrete artifact the augmented-tool
condition gives the agent: per changed method, the tests that cover it — with the
genuinely relevant (name-matched) tests floated to the top — plus a ready-to-paste
focused `./gradlew` command, so the agent runs a targeted subset instead of the
whole suite.

## How it is invoked

The agent (in the sandbox / on the host via the `.venv/bin/impact` shim) just runs,
with no arguments, from the workdir root:

```
impact          # or: bash impact
```

It then: walks up for `.opencode/impact.json` (config → sibling `.impact/` data
shipped by `overlays/impact-artifacts/`), runs `git diff HEAD` to see the agent's
**uncommitted** edit, maps each changed line to the method whose `[start,end]` span
contains it (`putValue` is `CommandLine.java:17414-17459`), and prints the covering
tests. It reads the **diff**, so it has nothing to report until after the edit.

## INPUT — the agent's edit (the `putValue` diff)

`git diff HEAD` after restoring the method body (excerpt):

```diff
             public Cell putValue(int row, int col, Text value) {
-                throw new UnsupportedOperationException("TODO: implement putValue");
+                if (row > rowCount() - 1) {
+                    throw new IllegalArgumentException("Cannot write to row " + row + ": rowCount=" + rowCount());
+                }
+                if (value == null || value.plain.length() == 0) { return new Cell(col, row); }
+                Column column = columns[col];
+                int indent = column.indent;
+                switch (column.overflow) {
+                    case TRUNCATE: ...
+                    case SPAN:     ...
+                    case WRAP:     ...
+                }
+                throw new IllegalStateException(column.overflow.toString());
             }
```

## OUTPUT — what `impact` prints for that diff

Note the ranking: the tests whose **name** echoes the method/class (`putValue`,
`TextTable`) are listed first and flagged, and the focused command targets those
specific test methods — exactly the tests a capable agent otherwise greps for by
hand.

```
# impact — tests affected by your uncommitted changes

## picocli.CommandLine$Help$TextTable.putValue  (changed)
412 tests cover this method (Tier-2 coverers — name-matched first; run these to verify):
  - picocli.HelpTest.testTextTable   <- name match
  - picocli.HelpTest.testTextTableAddRowValues   <- name match
  - picocli.HelpTest.testTextTableAddsNewRowWhenAnyColumnTooLong   <- name match
  - picocli.HelpTest.testTextTableCellAt   <- name match
  - picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex   <- name match
  - picocli.HelpTest.testTextTablePutValue_NullOrEmpty   <- name match
  - picocli.HelpTest.testTextTableWithLargeWidth   <- name match
  - picocli.TextTableTest.addRowValues   <- name match
  - picocli.TextTableTest.addRowValues_nulls   <- name match
  - picocli.AbbreviationMatcherTest.testAbbrevOptions
  - picocli.AbbreviationMatcherTest.testAbbrevSubcommands
  ... (incidental coverage-only tests continue, list capped at 40)
  + 372 more

Focused run — tests whose name targets the change (most specific; run these FIRST):
  ./gradlew test --tests 'picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex' --tests 'picocli.HelpTest.testTextTablePutValue_NullOrEmpty' --tests 'picocli.TextTableTest.addRowValues' --tests 'picocli.TextTableTest.addRowValues_nulls' ...

Note: mutation data is empty → Tier-1 (cover+kill) and blind-spots are unavailable; the lists above are coverage-based (Tier-2).
```

## Notes

- **Ranking (name-match first).** The coverage list is Tier-2 — *any* test that
  executes the method — so for a broadly-covered method the genuinely relevant
  tests are buried. `build_report` now floats tests whose name matches the method
  or its innermost class (`putValue`, `TextTable`) to the top, flags them, and
  builds the focused command from those specific test methods. (Earlier the list
  was raw coverage order and a capable agent ignored it, grepping the dedicated
  `testTextTablePutValue_*` tests by hand — now `impact` hands them over directly.)
- **412 coverers, list capped at 40.** Caps are `_MAX_TESTS = 40`,
  `_MAX_SPECIFIC = 8`, `_MAX_CLASSES = 8` (`docker/impact_cli.py`); hence
  `+ 372 more`. The full mapping is `overlays/impact-artifacts/.impact/coverage.json`.
- **Tier-2 only.** `mutation.json` is `{}`, so the report is coverage-based
  ("which tests execute this method"), not mutation-based — hence the note and no
  blind-spots section.
- **putValue is a stress case for breadth.** 412 of the suite's tests touch the
  `Help$TextTable.putValue` rendering path. Pre-ranking that made the list useless;
  with ranking the dedicated tests surface regardless. For a *clean A/B*, the
  `addRowValues` target (see `experiment-mac-addrowvalues.yaml`) is more tractable.

## Regenerate

```
# from the repo root
WORK=$(mktemp -d); REPO=$PWD
mkdir -p "$WORK/src/main/java/picocli" "$WORK/.opencode"
cp -r experiments/picocli-putValue/overlays/impact-artifacts/.impact "$WORK/.impact"
cp experiments/picocli-putValue/overlays/impact-artifacts/.opencode/impact.json "$WORK/.opencode/impact.json"
cp experiments/picocli-putValue/stripped/src/main/java/picocli/CommandLine.java "$WORK/src/main/java/picocli/CommandLine.java"
( cd "$WORK" && git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -qm stub )
cp experiments/picocli-putValue/original/src/main/java/picocli/CommandLine.java "$WORK/src/main/java/picocli/CommandLine.java"
( cd "$WORK" && python3 "$REPO/docker/impact_cli.py" )
```
