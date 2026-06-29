# Graph-Tipper augmentation + debug methodology

> Target: `picocli.CommandLine$Help$TextTable.putValue`
> File: `src/main/java/picocli/CommandLine.java` (around lines 17414–17416)
> Signature: `public Cell putValue(int row, int col, Text value)`

## How to use this (read first)

You are restoring the body of `putValue`. Its exact behaviour is pinned by the
tests that exercise it — do **not** try to model it in your head from the method
name or a quick read. **Observe the real data flow at runtime, then implement
against what you saw.** This augmentation gives you everything you need to do
that without spelunking a 19,000-line file:

- the **direct tests** (with oracles) — the precise contract;
- **JaCoCo runtime coverage** (which tests execute `putValue`) plus a **focus
  set** — the few of them whose assertions actually constrain it;
- the **consumer contract** (`addRowValues`) and the **call chains** from the
  asserting tests down to `putValue` — what reads its return value, and the
  single chokepoint every call passes through (so you know where to probe).

**Workflow:**
1. Read the *Direct tests* and the *Consumer contract* below — that is the spec.
2. **Instrument the focus-set tests** (see *Which tests to instrument*) with
   temporary `//[probe]` print statements to watch the real data flow: the args
   `putValue` receives, the per-cell state, and the actual-vs-expected value the
   assertion compares. You may — and often should — also drop `//[probe]` prints
   into the chain methods in `CommandLine.java` (especially `addRowValues`, the
   single consumer/chokepoint) to see what `putValue` is handed and what the
   caller does with its return value across many tests at once.
3. Run those tests, read the `[probe]` output, and write/correct the body using
   the values you observed — not from assumption. Re-run after each change.
4. **Remove every `//[probe]` line before you finish.**

Don't rely on `grep` alone to understand behaviour — it shows you call sites, not
runtime values. **Search freely** for any method, type, or test you need during
the session, open files directly when you need more than the slices below, and
**do not hesitate to add `//[probe]` prints to tests or to the code** to see what
is actually happening — that is the point.

---

## Direct tests (the contract)

| Test (file:line) | Args | Oracle |
|---|---|---|
| `picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex` (src/test/java/picocli/HelpTest.java:2775) | `(1, 0, Ansi.OFF.text("abc"))` on a 0-row table | throws `IllegalArgumentException`, msg == `"Cannot write to row 1: rowCount=0"` |
| `picocli.HelpTest.testTextTablePutValue_NullOrEmpty` (src/test/java/picocli/HelpTest.java:2786) | `(0, 0, null)` and `(0, 0, EMPTY_TEXT)` | returns a `Cell` with `column == 0`, `row == 0` |

```java
// src/test/java/picocli/HelpTest.java:2775
void testTextTablePutValue_DisallowsInvalidRowIndex() {
    TextTable tt = new TextTable(Help.Ansi.OFF, new Help.Column[] { new Help.Column(30, 2, Help.Column.Overflow.SPAN) });
    try {
        tt.putValue(1, 0, Help.Ansi.OFF.text("abc"));
    } catch (IllegalArgumentException ex) {
        assertEquals("Cannot write to row 1: rowCount=0", ex.getMessage());
    }
}

// src/test/java/picocli/HelpTest.java:2786
void testTextTablePutValue_NullOrEmpty() {
    TextTable tt = new TextTable(Help.Ansi.OFF, new Help.Column[] { new Help.Column(30, 2, Help.Column.Overflow.SPAN) });
    tt.addEmptyRow();
    TextTable.Cell cell00 = tt.putValue(0, 0, null);
    assertEquals(0, cell00.column);
    assertEquals(0, cell00.row);
    TextTable.Cell other00 = tt.putValue(0, 0, Help.Ansi.EMPTY_TEXT);
    assertEquals(0, other00.column);
    assertEquals(0, other00.row);
}
```

## Which tests to instrument

### Universe — JaCoCo runtime coverage

`putValue` is executed at runtime by **412 of the ~2437 tests**, spread across **42 test classes** (full breakdown below). The other ~2000 tests never reach it — no point instrumenting those. But this coverage is Tier-2 ("the test executed the method *somewhere*"): it does **not** tell you which of the 412 constrain `putValue`'s behaviour. ~403 of them reach it only **incidentally**, while rendering some unrelated feature's usage message, and assert the whole usage string — so they won't reveal its contract. (Gradle runs by class, so this is the granularity that matters: e.g. to watch a broad data-flow sample through the chokepoint, run the whole `HelpTest` class — it holds 173 of the coverers.)

| coverers | test class |
|---:|---|
| 173 | `picocli.HelpTest` |
| 31 | `picocli.ArgGroupTest` |
| 28 | `picocli.ExecuteTest` |
| 21 | `picocli.HelpAnsiTest` |
| 19 | `picocli.HelpSubCommandTest` |
| 14 | `picocli.EndOfOptionsDelimiterTest` |
| 13 | `picocli.MixinTest` |
| 12 | `picocli.I18nTest` |
| 12 | `picocli.ModelUsageMessageSpecTest` |
| 9 | `picocli.InterpolatedModelTest` |
| 8 | `picocli.CommandMethodTest` |
| 7 | `picocli.AtFileTest` |
| 7 | `picocli.SubcommandTests` |
| 6 | `picocli.ModelCommandSpecTest` |
| 5 | `picocli.AutoCompleteTest` |
| 5 | `picocli.DefaultProviderTest` |
| 4 | `picocli.Issue1565HideParamOnUnknownOption` |
| 4 | `picocli.NegatableOptionTest` |
| 3 | `picocli.AbbreviationMatcherTest` |
| 3 | `picocli.SplitSynopsisLabelTest` |
| 2 | `picocli.CompletionCandidatesTest` |
| 2 | `picocli.Issue1225UnmatchedArgBadIndex` |
| 2 | `picocli.Issue1351` |
| 2 | `picocli.RangeTest` |
| 2 | `picocli.TextTableTest` |
| 2 | `picocli.UnmatchedArgumentExceptionTest` |
| 1 | `picocli.CommandAnnotationInheritedTest` |
| 1 | `picocli.CommandLineTest` |
| 1 | `picocli.InheritedOptionTest` |
| 1 | `picocli.Issue1125_1538_OptionNameOrSubcommandAsOptionValue` |
| 1 | `picocli.Issue1528` |
| 1 | `picocli.Issue2309` |
| 1 | `picocli.Issue2341` |
| 1 | `picocli.Issue2413ArgGroupHelpOrdering` |
| 1 | `picocli.Issue776ArgGroupsIgnoredInMixinTest` |
| 1 | `picocli.Issue779ExceptionWhenNestedGroupInMixin` |
| 1 | `picocli.MapOptionsTest` |
| 1 | `picocli.ModelTransformerTest` |
| 1 | `picocli.OrderedArgGroupSynopsisTest` |
| 1 | `picocli.OrderedSynopsisTest` |
| 1 | `picocli.ParameterPreprocessorTest` |
| 1 | `picocli.ResourceBundlePropagationTest` |

### Where to start — the focus set (2 direct + 7 TextTable-targeted)
These are the coverers whose **oracle actually pins `putValue`**. Instrument
these first — the ones whose expected output you don't fully understand:

**Direct** (call `putValue` directly and assert its result/exception — graph/AST-derived):
- `picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex`
- `picocli.HelpTest.testTextTablePutValue_NullOrEmpty`

**TextTable-targeted** (build a `TextTable` and assert the exact rendered string —
this is where TRUNCATE/SPAN/WRAP + indent are pinned; name-matched to `TextTable`/`putValue`):
- `picocli.HelpTest.testTextTable`
- `picocli.HelpTest.testTextTableAddsNewRowWhenAnyColumnTooLong`
- `picocli.HelpTest.testTextTableWithLargeWidth`
- `picocli.HelpTest.testTextTableAddRowValues`
- `picocli.HelpTest.testTextTableCellAt`
- `picocli.TextTableTest.addRowValues`
- `picocli.TextTableTest.addRowValues_nulls`

(In `src/test/java/picocli/HelpTest.java` and `src/test/java/picocli/TextTableTest.java`.)

Run a single candidate and read your probes like this:
```
./gradlew test --tests 'picocli.HelpTest.testTextTable' --info 2>&1 | grep '\[probe\]'
```
(Gradle captures test `System.out`; `--info` surfaces it on the console.)

---

## Consumer contract: `addRowValues` (the single consumer — 1256 chains)

`addRowValues` is the **only** consumer of `putValue`'s return value, and it sits
on **every** chain that reaches `putValue` (see *Call chains*). Get the returned
`Cell` right.

```java
public void addRowValues(Text... values) {
    if (values.length > columns.length) {
        throw new IllegalArgumentException(values.length + " values don't fit in " + columns.length + " columns");
    }
    addEmptyRow();
    int oldIndent = unindent(values);
    for (int col = 0; col < values.length; col++) {
        int row = rowCount() - 1;              // write to last row: previous value may have wrapped to next row
        Cell cell = putValue(row, col, values[col]);
        // add a row if a value spanned/wrapped AND there are still remaining values
        if ((cell.row != row || cell.column != col) && col != values.length - 1) {
            addEmptyRow();
        }
    }
    reindent(oldIndent);
}
```

**Implied requirements on `putValue` (AST-derived):**
- MUST return non-null (else NPE on `cell.row` / `cell.column`).
- The returned `Cell`'s `row` and `column` are read by the caller — they must
  reflect the **last cell actually written to**. `addRowValues` compares them to
  the input `(row, col)` to decide whether the value spanned/wrapped and a new
  row is needed. (TRUNCATE/no-overflow → return the same `(row, col)`.)
- The return value participates in the caller's control flow.
- No try/catch around the call → exceptions (e.g. the invalid-row check)
  propagate to the caller as-is.

---

## Call chains (blast radius)

Every runtime path funnels into `addRowValues → putValue`. Entry points by chain
count (all share the tail `… → TextTable.addRowValues → TextTable.putValue`):

| Entry-point | chains | depth | tail before addRowValues | representative test |
|---|---|---|---|---|
| `CommandLine.parseArgs` | 498 | 12 | `…EnvironmentVariablesRenderer.render` | `picocli.spring.PicocliSpringFactoryTest.testParseTopLevelCommand` |
| `CommandLine.populateCommand` | 302 | 13 | `…EnvironmentVariablesRenderer.render` | `DefaultProviderEnvironmentTest.testIssue962…` |
| `CommandLine.getUsageMessage` | 162 | 6 | `CommandLine.usage → EnvironmentVariablesRenderer.render` | `DefaultProviderEnvironmentTest.testIssue616…` |
| `CommandLine.execute` | 141 | 8 | `…CommandLine.usage → EnvironmentVariablesRenderer.render` | `codegen…manpage.Issue2145.testManPageGenAsSubcommand` |
| `Help.synopsis` | 44 | 6 | `Help.insertSynopsisCommandName` (**different tail**) | `ArgGroupTest.testIssue722` |
| `CommandLine.parse` | 36 | 12 | `…EnvironmentVariablesRenderer.render` | `CommandLineTest.testCommandLine_isUsageHelpRequested…` |
| `AutoComplete.main` | 20 | 9 | `…CommandLine.usage → EnvironmentVariablesRenderer.render` | `AutoCompleteSystemExitTest.testAutoCompleteAppHelp` |
| `CommandLine.usage` | 20 | 7 | `EnvironmentVariablesRenderer.render` | `CommandLineTest.testUsageObjectPrintstreamColorscheme…` |
| `UnmatchedOptionTest.expect` | 17 | 14 | `…EnvironmentVariablesRenderer.render` | `UnmatchedOptionTest.testSingleValuePositionalDoesNotConsumeActualOption` |
| `CommandLine.run` | 16 | 11 | `…CommandLine.usage → EnvironmentVariablesRenderer.render` | `ExecuteLegacyTest.testRun1WithInvalidInput` |

There are only **two distinct tails** into `addRowValues`:

```java
// Tail A (most chains): render an option/env table, one row per entry.
public String render(CommandLine.Help help) {
    TextTable textTable = TextTable.forColumns(help.colorScheme(),
            new Column(keyLength + 3, 2, Column.Overflow.SPAN),
            new Column(width(help) - (keyLength + 3), 2, Column.Overflow.WRAP));
    for (Map.Entry<String, String> entry : env.entrySet()) {
        textTable.addRowValues(String.format(entry.getKey()), String.format(entry.getValue()));
    }
}

// Tail B (synopsis path): pad the command name, then one wide row.
protected String insertSynopsisCommandName(int synopsisHeadingLength, Text optionsAndPositionalsAndCommandsDetails) {
    TextTable textTable = TextTable.forColumnWidths(colorScheme, width());
    Text PADDING = Ansi.OFF.new Text(stringOf('X', synopsisHeadingLength), ...);
    textTable.addRowValues(PADDING.concat(colorScheme.commandText(commandName)).concat(optionsAndPositionalsAndCommandsDetails));
}
```

---

## Broad data flow in one run (the chokepoint)

`addRowValues` is the **single consumer** of `putValue` and sits on **every** one
of the 412 chains (see *Call chains*). So a `//[probe]` at the top of `putValue`
itself — or in `addRowValues` right around the call — captures the
`(row, col, value)` going in and the returned `Cell` coming out of **every** call
in a test run, not just one. This is the best single place to watch the data
flow:

```java
// inside addRowValues(Text...), around the call — remove before finishing:
Cell cell = putValue(row, col, values[col]);
System.out.println("[probe] putValue(row=" + row + ", col=" + col
        + ", value='" + values[col] + "') -> Cell(col=" + cell.column
        + ", row=" + cell.row + ")");  //[probe]
```

Run the **focus set** with that probe to see a controlled, oracle-backed sample
of the data flow across several tests at once:

```
./gradlew test --tests 'picocli.HelpTest.testTextTable*' --tests 'picocli.TextTableTest' --info 2>&1 | grep '\[probe\]'
```

Two caveats if you widen the run beyond the focus set:
- The ~403 incidental coverers flood the output with arbitrary CLI strings (low
  signal, and it can blow your context). They have no oracle on `putValue`, so
  they show input *variety* but not what the *correct* output is.
- A probe inside `addRowValues`/`putValue` prints during **every** test that
  renders a usage message, and many picocli tests **capture `System.out`** and
  assert on it — your probe will corrupt their captured output and make them
  fail spuriously. Don't chase those failures; they disappear once the probe is
  removed. Prefer probing + running the focus set.

If you need to know how a collaborator works (the `copy(...)` overloads, the
`Column` width/indent/overflow model, `addEmptyRow`, `length(...)`, `toString`),
open `CommandLine.java` and read it, or probe it — don't guess.

---

## Reminders

- `//[probe]` prints are temporary — **remove them all before you finish.** Test
  files are restored by the harness before grading, but keep `CommandLine.java`
  clean too (mark every debug line with `//[probe]`).
- The full green `./gradlew test --continue` suite is the final gate — run it
  only **after** removing your probes.
