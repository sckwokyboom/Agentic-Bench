# Graph-Tipper Augmentation

> Generated for: original @ 75550581bf63e13f79a330776e9eea3b94f4e5a0379e8cca4a0186d0f148c60e
> Target: picocli.CommandLine$Help$TextTable.putValue
> Budget: 10484 / 20000 tokens
> Consumers: 1 · Path clusters: 10 (covering 1256/1526 chains, 82%)
> Direct tests: 2 · Long-tail singletons: 76

## Target

**File:** `src/main/java/picocli/CommandLine.java` (lines 17414–17416)

**Signature:**
```java
public Cell putValue(int row, int col, Text value)
```

**Current body:**
```java
            public Cell putValue(int row, int col, Text value) {
                throw new UnsupportedOperationException("TODO: implement putValue");
            }
```

## Direct tests

| Test (file:line) | Args | Oracle |
|---|---|---|
| `picocli.HelpTest.testTextTablePutValue_DisallowsInvalidRowIndex` (src/test/java/picocli/HelpTest.java:2775) | (1, 0, Help.Ansi.OFF.text("abc")) | throws IllegalArgumentException.msg == "Cannot write to row 1: rowCount=0" |
| `picocli.HelpTest.testTextTablePutValue_NullOrEmpty` (src/test/java/picocli/HelpTest.java:2786) | (0, 0, Help.Ansi.EMPTY_TEXT) | returns 0 |

**Test sources:**
```java
// src/test/java/picocli/HelpTest.java:2775
void testTextTablePutValue_DisallowsInvalidRowIndex() {
    @SuppressWarnings("deprecation")
    TextTable tt = new TextTable(Help.Ansi.OFF, new Help.Column[] { new Help.Column(30, 2, Help.Column.Overflow.SPAN) });
    try {
        tt.putValue(1, 0, Help.Ansi.OFF.text("abc"));
    } catch (IllegalArgumentException ex) {
        assertEquals("Cannot write to row 1: rowCount=0", ex.getMessage());
    }
}
```

```java
// src/test/java/picocli/HelpTest.java:2786
void testTextTablePutValue_NullOrEmpty() {
    @SuppressWarnings("deprecation")
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

## Consumer contracts

### Consumer 1: picocli.CommandLine$Help$TextTable.addRowValues
**Chains covered:** 1256
**Defined at:** src/main/java/picocli/CommandLine.java:17371

**Body slice around call to target:**
```java
void addRowValues(Text...) {
    if (values.length > columns.length) {
        throw new IllegalArgumentException(values.length + " values don't fit in " + columns.length + " columns");
    }
    addEmptyRow();
    int oldIndent = unindent(values);
    for (int col = 0; col < values.length; col++) {
        // write to last row: previous value may have wrapped to next row
        int row = rowCount() - 1;
        Cell cell = putValue(row, col, values[col]);
        // add row if a value spanned/wrapped and there are still remaining values
        if ((cell.row != row || cell.column != col) && col != values.length - 1) {
            addEmptyRow();
        }
    }
    reindent(oldIndent);
}
```

**Return-value usage (AST-derived):**
- Assigned to local
- Field-read: `row`, `column`
- Used in branch condition

**Exception handling around call:**
- No try/catch → exceptions propagate to caller as-is

**Implied requirements on target:**
- MUST return non-null (else NPE on `row`, `column`)
- Returned object's fields are observed by caller (not opaque): row, column
- Return value participates in caller's control flow
- No try/catch around call — exceptions propagate to caller as-is

#### 4.4.1.a Cluster: CommandLine.parseArgs path (498 chains)

**Entry-point:** `picocli.CommandLine.parseArgs`
**Path:** CommandLine.parseArgs → Interpreter.parse → Interpreter.validateConstraints → ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 12

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.spring.PicocliSpringFactoryTest.testParseTopLevelCommand` — `picocli-spring-boot-starter/src/test/java/picocli/spring/PicocliSpringFactoryTest.java:36`

**Differential matrix (5 representatives of 498):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.spring.PicocliSpringFactoryTest.testParseTopLevelCommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "abc" |
| `picocli.spring.PicocliSpringFactoryTest.testParseSubCommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "abc" |
| `picocli.spring.PicocliSpringFactoryTest.testParseSubSubCommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "abc" |
| `picocli.spring.boot.autoconfigure.PicocliAutoConfigurationTest.defaultPicocliSpringFactory` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertTrue(factory instanceof PicocliSpringFactory) |
| `picocli.spring.boot.autoconfigure.example.test.ExampleTest.testParsingCommandLineArgs` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "abc" |

**+ 493 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 498 members share arg0

#### 4.4.1.b Cluster: CommandLine.populateCommand path (302 chains)

**Entry-point:** `picocli.CommandLine.populateCommand`
**Path:** CommandLine.populateCommand → CommandLine.parse → Interpreter.parse → Interpreter.validateConstraints → ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 13

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.DefaultProviderEnvironmentTest.testIssue962DefaultNotUsedIfArgumentSpecifiedOnCommandLine` — `picocli-tests-java567/src/test/java/picocli/DefaultProviderEnvironmentTest.java:310`

**Differential matrix (5 representatives of 302):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.DefaultProviderEnvironmentTest.testIssue962DefaultNotUsedIfArgumentSpecifiedOnCommandLine` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns (Integer) 987 |
| `picocli.DefaultProviderEnvironmentTest.testIssue961DefaultNotUsedIfArgumentSpecifiedOnCommandLine` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns (Integer) 987 |
| `picocli.DefaultProviderEnvironmentTest.testNullDefault` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns null |
| `picocli.DefaultProviderEnvironmentTest.testDefaultValueWithVariable` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 123 |
| `picocli.DefaultProviderEnvironmentTest.testDefaultValueWithVariableFallback` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 555 |

**+ 297 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 302 members share arg0

#### 4.4.1.c Cluster: CommandLine.getUsageMessage path (162 chains)

**Entry-point:** `picocli.CommandLine.getUsageMessage`
**Path:** CommandLine.getUsageMessage → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 6

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.DefaultProviderEnvironmentTest.testIssue616DefaultProviderWithShowDefaultValues` — `picocli-tests-java567/src/test/java/picocli/DefaultProviderEnvironmentTest.java:275`

**Differential matrix (5 representatives of 162):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.DefaultProviderEnvironmentTest.testIssue616DefaultProviderWithShowDefaultValues` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.MapOptionsOptionalTest.testMapFallbackValueDescriptionVariable` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.DefaultProviderTest.testIssue616DefaultProviderWithShowDefaultValues` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.ArgGroupHelpRegressionTest.testRegression988` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.ArgGroupTest.testArgGroupHeaderLocalization` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |

**+ 157 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 162 members share arg0

#### 4.4.1.d Cluster: CommandLine.execute path (141 chains)

**Entry-point:** `picocli.CommandLine.execute`
**Path:** CommandLine.execute → TextBasedUnknownOptionHandler.handleParseException → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 8

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.codegen.docgen.manpage.Issue2145.testManPageGenAsSubcommand` — `picocli-codegen/src/test/java/picocli/codegen/docgen/manpage/Issue2145.java:19`

**Differential matrix (5 representatives of 141):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.codegen.docgen.manpage.Issue2145.testManPageGenAsSubcommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 0 |
| `picocli.codegen.docgen.manpage.ManPageGeneratorTest.testManPageGeneratorAsSubcommandHelp` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.codegen.docgen.manpage.ManPageGeneratorTest.testManPageGeneratorAsSubcommandParentHelp` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.codegen.docgen.manpage.ManPageGeneratorTest.testManPageGeneratorAsSubcommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 0 |
| `picocli.codegen.docgen.manpage.ManPageGeneratorTest.testNamelessCommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 0 |

**+ 136 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 141 members share arg0

#### 4.4.1.e Cluster: Help.synopsis path (44 chains)

**Entry-point:** `picocli.CommandLine$Help.synopsis`
**Path:** Help.synopsis → Help.detailedSynopsis → Help.makeSynopsisFromParts → Help.insertSynopsisCommandName → TextTable.addRowValues → TextTable.putValue
**Depth:** 6

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.ArgGroupTest.testIssue722` — `src/test/java/picocli/ArgGroupTest.java:2389`

**Differential matrix (5 representatives of 44):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.ArgGroupTest.testIssue722` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.ArgGroupTest.testIssue746ArgGroupWithDefaultValuesSynopsis` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.HelpAnsiTest.testSystemPropertiesOverrideDefaultColorScheme` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns ansi.new Text("@\|bold <main class>\|@ [@\|yellow -v\|@] [@\|yellow -c\|@=@\|italic <count>\|@] @\|yellow FILE\|@..." + LINESEP) |
| `picocli.HelpAnsiTest.testSystemPropertiesOverrideExplicitColorScheme` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns ansi.new Text("@\|faint,bg(magenta) <main class>\|@ [@\|bg(red) -v\|@] [@\|bg(red) -c\|@=@\|bg(green) <count>\|@] @\|reverse FILE\|@..." + LINESEP) |
| `picocli.HelpAnsiTest.testAbreviatedSynopsis_withParameters` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "<main class> [OPTIONS] [<files>...]" + LINESEP |

**+ 39 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 44 members share arg0

#### 4.4.1.f Cluster: CommandLine.parse path (36 chains)

**Entry-point:** `picocli.CommandLine.parse`
**Path:** CommandLine.parse → Interpreter.parse → Interpreter.validateConstraints → ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 12

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.CommandLineTest.testCommandLine_isUsageHelpRequested_trueWhenSpecified` — `src/test/java/picocli/CommandLineTest.java:698`

**Differential matrix (5 representatives of 36):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.CommandLineTest.testCommandLine_isUsageHelpRequested_trueWhenSpecified` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertTrue("usage help requested") |
| `picocli.CommandLineTest.testCommandLine_isVersionHelpRequested_trueWhenSpecified` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertTrue("version info requested") |
| `picocli.CommandLineTest.testCommandLine_isUsageHelpRequested_falseWhenNotSpecified` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertFalse("usage help requested") |
| `picocli.CommandLineTest.testCommandLine_isVersionHelpRequested_falseWhenNotSpecified` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertFalse("version info requested") |
| `picocli.CommandLineTest.testParseSubCommands` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "command count" |

**+ 31 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 36 members share arg0

#### 4.4.1.g Cluster: CommandLine.usage path (20 chains)

**Entry-point:** `picocli.CommandLine.usage`
**Path:** CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 7

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.CommandLineTest.testUsageObjectPrintstreamColorschemeRequiresAnnotatedCommand` — `src/test/java/picocli/CommandLineTest.java:1891`

**Differential matrix (5 representatives of 20):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.CommandLineTest.testUsageObjectPrintstreamColorschemeRequiresAnnotatedCommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | <no assertion found> |
| `picocli.HelpAnsiTest.testUsageWithCustomColorScheme` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns Ansi.ON.new Text(expected).toString() |
| `picocli.Issue1420Test.testingWithResourceBundle1` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expectedText |
| `picocli.HelpSubCommandTest.testUsageTextWithHiddenSubcommand` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.HelpSubCommandTest.testUsageNoHeaderIfAllSubcommandHidden` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |

**+ 15 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 20 members share arg0

#### 4.4.1.h Cluster: AutoComplete.main path (20 chains)

**Entry-point:** `picocli.AutoComplete.main`
**Path:** AutoComplete.main → CommandLine.execute → TextBasedUnknownOptionHandler.handleParseException → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 9

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.AutoCompleteSystemExitTest.testAutoCompleteAppHelp` — `picocli-tests-java567/src/test/java/picocli/AutoCompleteSystemExitTest.java:526`

**Differential matrix (5 representatives of 20):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.AutoCompleteSystemExitTest.testAutoCompleteAppHelp` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns args[0] |
| `picocli.AutoCompleteSystemExitTest.testAutoCompleteAppHelp_NoSystemExit` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns args[0] |
| `picocli.AutoCompleteSystemExitTest.testAutoCompleteRequiresCommandLineFQCN` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.AutoCompleteSystemExitTest.testAutoCompleteRequiresCommandLineFQCN_NoSystemExit` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.AutoCompleteSystemExitTest.testAutoCompleteAppCannotInstantiate` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | assertTrue(actual.startsWith("java.lang.NoSuchMethodException: picocli.AutoCompleteSystemExitTest$1TestApp.<init>()")) |

**+ 15 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 20 members share arg0

#### 4.4.1.i Cluster: UnmatchedOptionTest.expect path (17 chains)

**Entry-point:** `picocli.UnmatchedOptionTest.expect`
**Path:** UnmatchedOptionTest.expect → CommandLine.parseArgs → Interpreter.parse → Interpreter.validateConstraints → ParseResult.validateGroups → GroupMatchContainer.updateUnmatchedGroups → Assert.assertTrue → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 14

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.UnmatchedOptionTest.testSingleValuePositionalDoesNotConsumeActualOption` — `src/test/java/picocli/UnmatchedOptionTest.java:52`

**Differential matrix (5 representatives of 17):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.UnmatchedOptionTest.testSingleValuePositionalDoesNotConsumeActualOption` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 3 |
| `picocli.UnmatchedOptionTest.testMultiValuePositionalDoesNotConsumeActualOption` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 3 |
| `picocli.UnmatchedOptionTest.testMultiValueVarArgPositionalDoesNotConsumeActualOption` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 3 |
| `picocli.UnmatchedOptionTest.testMultiValuePositionalArity2_NDoesNotConsumeActualOption` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns 3 |
| `picocli.UnmatchedOptionTest.testSingleValueOptionDoesNotConsumeActualOptionSimple` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | <no assertion found> |

**+ 12 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 17 members share arg0

#### 4.4.1.j Cluster: CommandLine.run path (16 chains)

**Entry-point:** `picocli.CommandLine.run`
**Path:** CommandLine.run → CommandLine.parseWithHandlers → DefaultExceptionHandler.handleParseException → DefaultExceptionHandler.internalHandleParseException → CommandLine.usage → EnvironmentVariablesRenderer.render → TextTable.addRowValues → TextTable.putValue
**Depth:** 11

**Static slice (Tier 2):**

arg0:
  ← <UNRESOLVED: METHOD_CALL> op 1

arg1:
  ← <loop col: 0 < ... col < values.length>

arg2:
  ← <UNRESOLVED: BRANCH_EXPLOSION>

**Primary representative:** `picocli.ExecuteLegacyTest.testRun1WithInvalidInput` — `picocli-tests-java567/src/test/java/picocli/ExecuteLegacyTest.java:698`

**Differential matrix (5 representatives of 16):**

| Test | Sliced args | Oracle |
|---|---|---|
| `picocli.ExecuteLegacyTest.testRun1WithInvalidInput` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns MYCALLABLE_INVALID_INPUT |
| `picocli.ExecuteLegacyTest.testRun1WithHelpRequest` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns "" |
| `picocli.ExecuteLegacyTest.testExecutionExceptionIfRunnableThrowsExecutionException` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | throws ExecutionException.msg == "abc" |
| `picocli.ExecuteLegacyTest.testParameterExceptionIfRunnablePrintsUsageHelp` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |
| `picocli.CommandMethodTest.testSubcommandMethodInvalidInputHandling` | (<UNRESOLVED: METHOD_CALL> op 1, <loop col: 0 < ... col < values.length>, <UNRESOLVED: NOT_FOUND>[<loop col: 0 < ... col < values.length>]) | returns expected |

**+ 11 more tests with similar profile** (see JSON sidecar)

**Behavior signals (from differential analysis):**
- `arg1_is_loop_var`: arg1 iterates over 0 < ... col < values.length
- `arg2_requires_dynamic_value`: arg2 unresolved (BRANCH_EXPLOSION); inspect direct tests / test method literals for actual values
- `cluster_partial_resolution`: 1/3 args statically resolved
- `arg0_invariant_in_cluster`: All 16 members share arg0

## Long tail

76 additional uncovered singleton paths (each represents 1 chain). See `<hash>.json` → `clusters[].singletons` for the full list.

## Local Context

### Sibling members used by target
```java
java.lang.StringBuilder(java.lang.StringBuilder)
            public StringBuilder toString(StringBuilder text) {
                int columnCount = this.columns.length;
                StringBuilder row = new StringBuilder(tableWidth);
                for (int i = 0; i < columnValues.size(); i++) {
                    Text column = columnValues.get(i);
                    row.append(column.toString());
                    row.append(new String(spaces(columns[i % columnCount].width - column.length)));
                    if (i % columnCount == columnCount - 1) {
                        int lastChar = row.length() - 1;
                        while (lastChar >= 0 && row.charAt(lastChar) == ' ') {lastChar--;} // rtrim
                        row.setLength(lastChar + 1);
                        text.append(row.toString()).append(System.getProperty("line.separator"));
                        row.setLength(0);
                    }
                }
                return text;
            }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$Ansi,int)
            @Deprecated public static TextTable forDefaultColumns(Ansi ansi, int usageHelpWidth) {
                // TODO split out the 1 (for long column indent) and 3 (should be description indent)
                return forDefaultColumns(Help.defaultColorScheme(ansi), UsageMessageSpec.DEFAULT_USAGE_LONG_OPTIONS_WIDTH + 4, usageHelpWidth);
            }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$ColorScheme,int,int)
            public static TextTable forDefaultColumns(ColorScheme colorScheme, int longOptionsColumnWidth, int usageHelpWidth) {
                // "* -c, --create                Creates a ...."
                int descriptionWidth = usageHelpWidth - 5 - longOptionsColumnWidth;
                return forColumns(colorScheme,
                        new Column(2,                0, TRUNCATE), // "*"
                        new Column(2,                0, SPAN), // "-c"
                        new Column(1,                0, TRUNCATE), // ","
                        new Column(longOptionsColumnWidth, 1, SPAN),  // " --create"
                        new Column(descriptionWidth, 1, WRAP)); // " Creates a ..."
            }
int(picocli.CommandLine$Help$Ansi$Text)
            private int length(Text str) {
                return str.getCJKAdjustedLength();
            }
int(picocli.CommandLine$Help$Ansi$Text,int,int)
            private int length(Text str, int from, int length) {
                if (!adjustLineBreaksForWideCJKCharacters) { return length - from; }
                return str.getCJKAdjustedLength(from, length);
            }
void(picocli.CommandLine$Help$ColorScheme,picocli.CommandLine$Help$Column[])
            protected TextTable(ColorScheme colorScheme, Column[] columns) {
                this.colorScheme = Assert.notNull(colorScheme, "ansi");
                this.columns = Assert.notNull(columns, "columns").clone();
                if (columns.length == 0) { throw new IllegalArgumentException("At least one column is required"); }
                int totalWidth = 0;
                for (Column col : columns) { totalWidth += col.width; }
                tableWidth = totalWidth;
            }
picocli.CommandLine$Help$TextTable(boolean)
            public TextTable setAdjustLineBreaksForWideCJKCharacters(boolean adjustLineBreaksForWideCJKCharacters) {
                this.adjustLineBreaksForWideCJKCharacters = adjustLineBreaksForWideCJKCharacters;
                return this;
            }
void(picocli.CommandLine$Help$Ansi$Text,picocli.CommandLine$Help$Ansi$Text,int,picocli.CommandLine$Help$TextTable$Count)
            private void copy(Text value, Text destination, int offset, Count count) {
                int length = Math.min(value.length, destination.maxLength - offset);
                value.getStyledChars(value.from, length, destination, offset);
                count.columnCount += length(value, value.from, length);
                count.charCount += length;
            }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$Ansi,int[])
            @Deprecated public static TextTable forColumnWidths(Ansi ansi, int... columnWidths) {
                return forColumnWidths(Help.defaultColorScheme(ansi), columnWidths);
            }
int(java.text.BreakIterator,picocli.CommandLine$Help$Ansi$Text,picocli.CommandLine$Help$Ansi$Text,int)
            private int copy(BreakIterator line, Text text, Text columnValue, int offset) {
                // Deceive the BreakIterator to ensure no line breaks after '-' character
                line.setText(text.plainString().replace("-", "\u00ff"));
                Count count = new Count();
                for (int start = line.first(), end = line.next(); end != BreakIterator.DONE; start = end, end = line.next()) {
                    Text word = text.substring(start, end); //.replace("\u00ff", "-"); // not needed
                    if (columnValue.maxLength >= offset + count.columnCount + length(word)) {
                        copy(word, columnValue, offset + count.charCount, count);
                    } else {
                        break;
                    }
                }
                if (count.charCount == 0 && length(text) + offset > columnValue.maxLength) {
                    // The value is a single word that is too big to be written to the column. Write as much as we can.
                    copy(text, columnValue, offset, count);
                }
                return count.charCount;
            }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$ColorScheme,int[])
            public static TextTable forColumnWidths(ColorScheme colorScheme, int... columnWidths) {
                Column[] columns = new Column[columnWidths.length];
                for (int i = 0; i < columnWidths.length; i++) {
                    columns[i] = new Column(columnWidths[i], 0, i == columnWidths.length - 1 ? WRAP : SPAN);
                }
                return new TextTable(colorScheme, columns);
            }
picocli.CommandLine$Help$Column[]()
            public Column[] columns() { return columns.clone(); }
void()
            public void addEmptyRow() {
                for (Column column : columns) {
                    columnValues.add(colorScheme.ansi().new Text(column.width, colorScheme));
                }
            }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$Ansi,picocli.CommandLine$Help$Column[])
            @Deprecated public static TextTable forColumns(Ansi ansi, Column... columns) { return new TextTable(ansi, columns); }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$ColorScheme,picocli.CommandLine$Help$Column[])
            public static TextTable forColumns(ColorScheme colorScheme, Column... columns) { return new TextTable(colorScheme, columns); }
void(java.lang.String[])
            public void addRowValues(String... values) {
                final int numColumns = values.length;
                Text[][] cells = new Text[numColumns][]; // an array of columns
                int maxRows = 0;
                for (int col = 0; col < numColumns; col++) {
                    cells[col] = values[col] == null
                            ? new Text[] {Ansi.EMPTY_TEXT}
                            : colorScheme.text(values[col]).splitLines();
                    maxRows = Math.max(maxRows, cells[col].length);
                }
                Text[] rowValues = new Text[numColumns];
                for (int row = 0; row < maxRows; row++) {
                    Arrays.fill(rowValues, Ansi.EMPTY_TEXT);
                    for (int col = 0; col < numColumns; col++) {
                        if (row < cells[col].length) {
                            rowValues[col] = cells[col][row];
                        }
                    }
                    addRowValues(rowValues);
                }
            }
boolean()
            public boolean isAdjustLineBreaksForWideCJKCharacters() { return adjustLineBreaksForWideCJKCharacters; }
int()
            public int rowCount() { return columnValues.size() / columns.length; }
void(int)
            private void reindent(int oldIndent) {
                if (columns.length <= LONG_OPTION_COLUMN) { return; }
                columns[LONG_OPTION_COLUMN].indent = oldIndent;
            }
int(picocli.CommandLine$Help$Ansi$Text,picocli.CommandLine$Help$Ansi$Text,int)
            private int copy(Text value, Text destination, int offset) {
                Count count = new Count();
                copy(value, destination, offset, count);
                return count.charCount;
            }
picocli.CommandLine$Help$Ansi$Text(int,int)
            @Deprecated public Text cellAt(int row, int col) { return textAt(row, col); }
int(picocli.CommandLine$Help$Ansi$Text[])
            private int unindent(Text[] values) {
                if (columns.length <= LONG_OPTION_COLUMN) { return 0; }
                int oldIndent = columns[LONG_OPTION_COLUMN].indent;
                if ("=".equals(values[OPTION_SEPARATOR_COLUMN].toString())) {
                    columns[LONG_OPTION_COLUMN].indent = 0;
                }
                return oldIndent;
            }
void(picocli.CommandLine$Help$Ansi,picocli.CommandLine$Help$Column[])
            @Deprecated protected TextTable(Ansi ansi, Column[] columns) { this(Help.defaultColorScheme(ansi), columns); }
void(picocli.CommandLine$Help$Ansi$Text[])
            public void addRowValues(Text... values) {
                if (values.length > columns.length) {
                    throw new IllegalArgumentException(values.length + " values don't fit in " +
                            columns.length + " columns");
                }
                addEmptyRow();
                int oldIndent = unindent(values);
                for (int col = 0; col < values.length; col++) {
                    int row = rowCount() - 1;// write to last row: previous value may have wrapped to next row
                    Cell cell = putValue(row, col, values[col]);

                    // add row if a value spanned/wrapped and there are still remaining values
                    if ((cell.row != row || cell.column != col) && col != values.length - 1) {
                        addEmptyRow();
                    }
                }
                reindent(oldIndent);
            }
java.lang.String()
            public String toString() { return toString(new StringBuilder()).toString(); }
picocli.CommandLine$Help$TextTable(picocli.CommandLine$Help$Ansi,int,int)
            @Deprecated public static TextTable forDefaultColumns(Ansi ansi, int longOptionsColumnWidth, int usageHelpWidth) {
                return forDefaultColumns(Help.defaultColorScheme(ansi), longOptionsColumnWidth, usageHelpWidth);
            }
void(int,int)
                public Cell(int column, int row) { this.column = column; this.row = row; }
picocli.CommandLine$Help$Column[] columns
int indentWrappedLines
```

## Negative Memory
_(reserved — not populated in V1)_
