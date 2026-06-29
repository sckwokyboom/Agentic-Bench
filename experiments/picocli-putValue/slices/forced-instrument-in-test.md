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
  single chokepoint every call passes through (so you know where to probe);
- **clustered call chains** (medoid path per cluster) — the typical end-to-end
  dataflow scenarios that reach `putValue`, so you can probe the *intermediate*
  methods on a test's path, not just `putValue` or the test itself.

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

## Clustered call chains (medoids)

The runtime call chains that reach `putValue` were clustered (by longest-common-
subsequence of the call sequence); below is the **medoid** of each cluster —
i.e. the most representative full path from an entry point down to `putValue`,
with its chain count. These are the typical dataflow scenarios that exercise
`putValue` across the suite.

Use them to debug *through the chain*, not only at the endpoints: pick the
cluster a failing test belongs to, `grep` the intermediate methods on its path,
and drop temporary `//[probe]` prints inside them (e.g. `render`,
`insertSynopsisCommandName`, `addRowValues`) to see what `putValue` is actually
handed and how the caller consumes its return value for that test. This is often
the fastest way to understand a given test's contract w.r.t. `putValue`.

```text
[A] 498 chains · CommandLine.parseArgs → Interpreter.parse → Interpreter.validateConstraints
      → ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[C] 302 chains · CommandLine.populateCommand → CommandLine.parse → Interpreter.parse → …
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[F] 162 chains · CommandLine.getUsageMessage → CommandLine.usage
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[D] 141 chains · CommandLine.execute → TextBasedUnknownOptionHandler.handleParseException
      → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[G]  44 chains · Help.synopsis → Help.detailedSynopsis → Help.makeSynopsisFromParts
      → Help.insertSynopsisCommandName → TextTable.addRowValues → TextTable.putValue   (distinct tail)
[H]  36 chains · CommandLine.parse → Interpreter.parse → Interpreter.validateConstraints → …
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[E]  20 chains · AutoComplete.main → CommandLine.execute → TextBasedUnknownOptionHandler.handleParseException
      → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[I]  20 chains · CommandLine.usage → EnvironmentVariablesRenderer.render
      → TextTable.addRowValues → TextTable.putValue
[B]  17 chains · UnmatchedOptionTest.expect → CommandLine.parseArgs → Interpreter.parse → …
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
[J]  16 chains · CommandLine.run → CommandLine.parseWithHandlers → DefaultExceptionHandler.handleParseException
      → DefaultExceptionHandler.internalHandleParseException → CommandLine.usage
      → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
```

Two tails dominate: `…render → addRowValues → putValue` (option/env tables, all
clusters except G) and `…insertSynopsisCommandName → addRowValues → putValue`
(the synopsis path, G). `addRowValues` is on every chain — see the chokepoint below.

---

## Chain methods (call-site snippets)

Use the full chains above to choose methods to inspect and to place temporary
`//[probe]` diagnostics along the relevant path. These compact fragments show
how arguments and calls flow toward `putValue`; each method-level edge appears
once. They show caller code only—the body of the target method is intentionally
omitted.

- `CommandLine.parseArgs → Interpreter.parse`:
```java
public ParseResult parseArgs(String... args) {
        interpreter.parse(args);
}
```

- `Interpreter.parse → Interpreter.parse`:
```java
List<CommandLine> parse(String... args) {
            Stack<String> arguments = new Stack<String>();
    // ...
            List<CommandLine> result = new ArrayList<CommandLine>();
            parse(result, arguments, args, new ArrayList<Object>(), new HashSet<ArgSpec>());
}
```

- `Interpreter.parse → Interpreter.validateConstraints`:
```java
private void parse(List<CommandLine> parsedCommands, Stack<String> argumentStack, String[] originalArgs, List<Object> nowProcessing, Collection<ArgSpec> inheritedRequired, Set<ArgSpec> initialized) {
            List<ArgSpec> required = new ArrayList<ArgSpec>(commandSpec.requiredArgs());
    // ...
            if (!anyHelpRequested) {
                validateConstraints(argumentStack, required, initialized);
}
```

- `Interpreter.validateConstraints → ParseResult.validateGroups`:
```java
private void validateConstraints(Stack<String> argumentStack, List<ArgSpec> required, Set<ArgSpec> matched) {
            ParseResult pr = parseResultBuilder.build();
            pr.validateGroups();
}
```

- `ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups`:
```java
void validateGroups() {
            for (ArgGroupSpec group : commandSpec.argGroups()) {
                groupMatchContainer.updateUnmatchedGroups(group);
}
```

- `GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue`:
```java
void updateUnmatchedGroups(final ArgGroupSpec group) {
                Assert.assertTrue(Assert.equals(group(), group.parentGroup()), new IHelpSectionRenderer() {public String render(Help h) {
                    return "Internal error: expected " + group.parentGroup() + " (the parent of " + group + "), but was " + group(); }});
}
```

- `Assert.assertTrue → EnvironmentVariablesRenderer.render`:
```java
static void assertTrue(boolean condition, IHelpSectionRenderer producer) {
    if (!condition) throw new IllegalStateException(producer.render(null));
}
```

- `EnvironmentVariablesRenderer.render → TextTable.addRowValues`:
```java
public String render(CommandLine.Help help) {
    // ...
                new Column(width(help) - (keyLength + 3), 2, Column.Overflow.WRAP));
    // ...
        for (Map.Entry<String, String> entry : env.entrySet()) {
            textTable.addRowValues(String.format(entry.getKey()), String.format(entry.getValue()));
}
```

- `TextTable.addRowValues → TextTable.addRowValues`:
```java
public void addRowValues(String... values) {
                final int numColumns = values.length;
    // ...
                Text[] rowValues = new Text[numColumns];
                for (int row = 0; row < maxRows; row++) {
                    addRowValues(rowValues);
}
```

- `TextTable.addRowValues → TextTable.putValue`:
```java
public void addRowValues(Text... values) {
                for (int col = 0; col < values.length; col++) {
                    int row = rowCount() - 1;// write to last row: previous value may have wrapped to next row
                    Cell cell = putValue(row, col, values[col]);
    // ...
                    if ((cell.row != row || cell.column != col) && col != values.length - 1) {
}
```

- `CommandLine.populateCommand → CommandLine.parse`:
```java
public static T populateCommand(T command, String... args) {
        CommandLine cli = toCommandLine(command, new DefaultFactory());
        cli.parse(args);
}
```

- `CommandLine.parse → Interpreter.parse`:
```java
public List<CommandLine> parse(String... args) {
        return interpreter.parse(args);
}
```

- `CommandLine.getUsageMessage → CommandLine.usage`:
```java
public String getUsageMessage() {
        return usage(new StringBuilder(), getHelp()).toString();
}
```

- `CommandLine.usage → EnvironmentVariablesRenderer.render`:
```java
private StringBuilder usage(StringBuilder sb, Help help) {
    for (String key : getHelpSectionKeys()) {
        IHelpSectionRenderer renderer = getHelpSectionMap().get(key);
        if (renderer != null) { sb.append(renderer.render(help)); }
    }
    return sb;
}
```

- `CommandLine.execute → TextBasedUnknownOptionHandler.handleParseException`:
```java
public int execute(String... args) {
    // ...
    try {
        parseResult[0] = parseArgs(args);
        return enrichForBackwardsCompatibility(getExecutionStrategy()).execute(parseResult[0]);
    } catch (ParameterException ex) {
        return getParameterExceptionHandler().handleParseException(ex, args);
    }
```

- `TextBasedUnknownOptionHandler.handleParseException → CommandLine.usage`:
```java
public int handleParseException(ParameterException ex, String[] args) {
            CommandLine cmd = ex.getCommandLine();
            PrintWriter writer = cmd.getErr();
            CommandLine.Help.ColorScheme colorScheme = cmd.getColorScheme();
    // ...
            if (!UnmatchedArgumentException.printSuggestions(ex, writer)) {
                ex.getCommandLine().usage(writer, colorScheme);
}
```

- `CommandLine.usage → CommandLine.usage`:
```java
public void usage(PrintWriter writer, Help.ColorScheme colorScheme) {
        writer.print(usage(new StringBuilder(), getHelpFactory().create(getCommandSpec(), colorScheme)));
}
```

- `Help.synopsis → Help.detailedSynopsis`:
```java
public String synopsis(int synopsisHeadingLength) {
            Comparator<OptionSpec> sortStrategy = commandSpec.usageMessage().sortSynopsis()
                ? createShortOptionArityAndNameComparator() // alphabetic sort
                : createOrderComparatorIfNecessary(commandSpec.options()); // explicit sort
            boolean clusterBooleanOptions = commandSpec.parser().posixClusteredShortOptionsAllowed();
            return commandSpec.usageMessage().abbreviateSynopsis() ? abbreviatedSynopsis()
                    : detailedSynopsis(synopsisHeadingLength, sortStrategy, clusterBooleanOptions);
}
```

- `Help.detailedSynopsis → Help.makeSynopsisFromParts`:
```java
public String detailedSynopsis(int synopsisHeadingLength, Comparator<OptionSpec> optionSort, boolean clusterBooleanOptions) {
    // ...
            Text positionalParamText = createDetailedSynopsisPositionalsText(argsInGroups);
            Text commandText = createDetailedSynopsisCommandText();
    // ...
            return makeSynopsisFromParts(synopsisHeadingLength, optionText, groupsText, endOfOptionsText, positionalParamText, commandText);
}
```

- `Help.makeSynopsisFromParts → Help.insertSynopsisCommandName`:
```java
protected String makeSynopsisFromParts(int synopsisHeadingLength, Text optionText, Text groupsText, Text endOfOptionsText, Text positionalParamText, Text commandText) {
                text = optionText.concat(groupsText).concat(endOfOptionsText).concat(positionalParamText).concat(commandText);
    // ...
            return insertSynopsisCommandName(synopsisHeadingLength, text);
}
```

- `Help.insertSynopsisCommandName → TextTable.addRowValues`:
```java
protected String insertSynopsisCommandName(int synopsisHeadingLength, Text optionsAndPositionalsAndCommandsDetails) {
            String commandName = commandSpec.qualifiedName();
    // ...
            TextTable textTable = TextTable.forColumnWidths(colorScheme, width());
    // ...
            Text PADDING = Ansi.OFF.new Text(stringOf('X', synopsisHeadingLength), optionsAndPositionalsAndCommandsDetails.colorScheme);
            textTable.addRowValues(PADDING.concat(colorScheme.commandText(commandName)).concat(optionsAndPositionalsAndCommandsDetails));
}
```

- `AutoComplete.main → CommandLine.execute`:
```java
public static void main(String... args) {
    // ...
        };
        int exitCode = new CommandLine(new App())
                .setExecutionExceptionHandler(errorHandler)
                .execute(args);
        if ((exitCode == EXIT_CODE_SUCCESS && exitOnSuccess()) || (exitCode != EXIT_CODE_SUCCESS && exitOnError())) {
    // ...
```

- `UnmatchedOptionTest.expect → UnmatchedOptionTest.expect`:
```java
static void expect(Object userObject, String errorMessage, Class<? extends Exception> cls, String... args) {
        expect(new CommandLine(userObject), errorMessage, cls, args);
}
```

- `UnmatchedOptionTest.expect → CommandLine.parseArgs`:
```java
static void expect(CommandLine cmd, String errorMessage, Class<? extends Exception> cls, String... args) {
        try {
            cmd.parseArgs(args);
            fail("Expected exception");
    // ...
            assertTrue("Wrong exception: " + ex + ", expected " + cls.getName(), cls.isAssignableFrom(ex.getClass()));
            assertEquals(errorMessage, ex.getMessage());
}
```

- `CommandLine.run → CommandLine.run`:
```java
public static void run(R runnable, String... args) {
        run(runnable, System.out, System.err, Help.Ansi.AUTO, args);
}
```

- `CommandLine.run → CommandLine.parseWithHandlers`:
```java
public static void run(R runnable, PrintStream out, PrintStream err, Help.Ansi ansi, String... args) {
        CommandLine cmd = new CommandLine(runnable);
        cmd.parseWithHandlers(new RunLast().useOut(out).useAnsi(ansi), new DefaultExceptionHandler<List<Object>>().useErr(err).useAnsi(ansi), args);
}
```

- `CommandLine.parseWithHandlers → DefaultExceptionHandler.handleParseException`:
```java
@Deprecated public <R> R parseWithHandlers(IParseResultHandler2<R> handler, IExceptionHandler2<R> exceptionHandler, String... args) {
    // ...
    try {
        parseResult = parseArgs(args);
        return handler.handleParseResult(parseResult);
    } catch (ParameterException ex) {
        return exceptionHandler.handleParseException(ex, args);
    }
```

- `DefaultExceptionHandler.handleParseException → DefaultExceptionHandler.internalHandleParseException`:
```java
public R handleParseException(ParameterException ex, String[] args) {
            internalHandleParseException(ex, newPrintWriter(err(), getStderrEncoding()), colorScheme()); return returnResultOrExit(null); }
}
```

- `DefaultExceptionHandler.internalHandleParseException → CommandLine.usage`:
```java
static void internalHandleParseException(ParameterException ex, PrintWriter writer, Help.ColorScheme colorScheme) {
            if (!UnmatchedArgumentException.printSuggestions(ex, writer)) {
                ex.getCommandLine().usage(writer, colorScheme);
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
