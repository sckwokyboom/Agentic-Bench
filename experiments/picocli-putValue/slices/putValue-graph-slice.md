# Graph-Tipper Augmentation

> Target: picocli.CommandLine$Help$TextTable.putValue

## Target

**File:** `src/main/java/picocli/CommandLine.java` (lines 17414–17416)

**Signature:**
```java
public Cell putValue(int row, int col, Text value)
```

**Current body:**
```java
            public Cell putValue(int row, int col, Text value) {
                throw new UnsupportedOperationException("TODO");
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

## Local Context

### Sibling members used by target
```java
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
            @Deprecated public static TextTable forDefaultColumns(Ansi ansi, int usageHelpWidth) {
                // TODO split out the 1 (for long column indent) and 3 (should be description indent)
                return forDefaultColumns(Help.defaultColorScheme(ansi), UsageMessageSpec.DEFAULT_USAGE_LONG_OPTIONS_WIDTH + 4, usageHelpWidth);
            }
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
            private int length(Text str) {
                return str.getCJKAdjustedLength();
            }
            private int length(Text str, int from, int length) {
                if (!adjustLineBreaksForWideCJKCharacters) { return length - from; }
                return str.getCJKAdjustedLength(from, length);
            }
            protected TextTable(ColorScheme colorScheme, Column[] columns) {
                this.colorScheme = Assert.notNull(colorScheme, "ansi");
                this.columns = Assert.notNull(columns, "columns").clone();
                if (columns.length == 0) { throw new IllegalArgumentException("At least one column is required"); }
                int totalWidth = 0;
                for (Column col : columns) { totalWidth += col.width; }
                tableWidth = totalWidth;
            }
            public TextTable setAdjustLineBreaksForWideCJKCharacters(boolean adjustLineBreaksForWideCJKCharacters) {
                this.adjustLineBreaksForWideCJKCharacters = adjustLineBreaksForWideCJKCharacters;
                return this;
            }
            private void copy(Text value, Text destination, int offset, Count count) {
                int length = Math.min(value.length, destination.maxLength - offset);
                value.getStyledChars(value.from, length, destination, offset);
                count.columnCount += length(value, value.from, length);
                count.charCount += length;
            }
            @Deprecated public static TextTable forColumnWidths(Ansi ansi, int... columnWidths) {
                return forColumnWidths(Help.defaultColorScheme(ansi), columnWidths);
            }
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
            public static TextTable forColumnWidths(ColorScheme colorScheme, int... columnWidths) {
                Column[] columns = new Column[columnWidths.length];
                for (int i = 0; i < columnWidths.length; i++) {
                    columns[i] = new Column(columnWidths[i], 0, i == columnWidths.length - 1 ? WRAP : SPAN);
                }
                return new TextTable(colorScheme, columns);
            }
            public Column[] columns() { return columns.clone(); }
            public void addEmptyRow() {
                for (Column column : columns) {
                    columnValues.add(colorScheme.ansi().new Text(column.width, colorScheme));
                }
            }
            @Deprecated public static TextTable forColumns(Ansi ansi, Column... columns) { return new TextTable(ansi, columns); }
            public static TextTable forColumns(ColorScheme colorScheme, Column... columns) { return new TextTable(colorScheme, columns); }
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
            public boolean isAdjustLineBreaksForWideCJKCharacters() { return adjustLineBreaksForWideCJKCharacters; }
            public int rowCount() { return columnValues.size() / columns.length; }
            private void reindent(int oldIndent) {
                if (columns.length <= LONG_OPTION_COLUMN) { return; }
                columns[LONG_OPTION_COLUMN].indent = oldIndent;
            }
            private int copy(Text value, Text destination, int offset) {
                Count count = new Count();
                copy(value, destination, offset, count);
                return count.charCount;
            }
            @Deprecated public Text cellAt(int row, int col) { return textAt(row, col); }
            private int unindent(Text[] values) {
                if (columns.length <= LONG_OPTION_COLUMN) { return 0; }
                int oldIndent = columns[LONG_OPTION_COLUMN].indent;
                if ("=".equals(values[OPTION_SEPARATOR_COLUMN].toString())) {
                    columns[LONG_OPTION_COLUMN].indent = 0;
                }
                return oldIndent;
            }
            @Deprecated protected TextTable(Ansi ansi, Column[] columns) { this(Help.defaultColorScheme(ansi), columns); }
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
            public String toString() { return toString(new StringBuilder()).toString(); }
            @Deprecated public static TextTable forDefaultColumns(Ansi ansi, int longOptionsColumnWidth, int usageHelpWidth) {
                return forDefaultColumns(Help.defaultColorScheme(ansi), longOptionsColumnWidth, usageHelpWidth);
            }
                public Cell(int column, int row) { this.column = column; this.row = row; }
```

## Observed behaviour (baseline runtime examples — NOT an oracle)

_Captured from the existing implementation; use as behavioural hints, verify intent against the tests._

- `putValue(0, 0, XXXXXXX<main class> [-b]... [-a=ARG]... [-c=ARG]... [-d=ARG ARG]...) => Cell{column=0, row=0}`
- `putValue(0, 3, ARG) => Cell{column=3, row=0}`
- `putValue(0, 1, -a) => Cell{column=1, row=0}`
- `putValue(1, 0, abc) => throws IllegalArgumentException: Cannot write to row 1: rowCount=0`
- `putValue(0, 2, =) => Cell{column=2, row=0}`
