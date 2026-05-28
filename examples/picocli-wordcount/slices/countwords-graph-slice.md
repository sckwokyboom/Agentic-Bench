## Graph slice — `countWords`

This is the augmentation block produced by the RAG/graph layer (toy
example for the bench; in real use a generator emits this from the
project's code graph).

### Target node

- method: `example.WordCount#countWords(String text) : int`
- visibility: package-private, `static`
- file: `src/main/java/example/WordCount.java`

### Documented contract (from the surviving Javadoc)

A "word" is a maximal run of non-whitespace characters. Leading and
trailing whitespace is ignored; multiple whitespace characters between
words are treated as a single separator. Returns `0` for `null` or
all-whitespace input.

### Callers (edges from the call graph)

- `example.WordCount#call() : Integer`
  - reads the option `--input` as a `Path`
  - reads the file with `Files.readString(input)`
  - passes the resulting string to `countWords`
  - prints the returned `int` and returns `0`

### Test expectations (from `WordCountTest`)

- `countWords(null)` → `0`
- `countWords("")` → `0`
- `countWords("   ")` → `0`
- `countWords("hello")` → `1`
- `countWords("   hello   ")` → `1`
- `countWords("hello world")` → `2`
- `countWords("the quick brown fox jumps")` → `5`
- `countWords("a\tb\nc")` → `3`  (handles tab and newline as whitespace)

### Standard-library tools already in scope

- `String#trim()`
- `String#isEmpty()`
- `String#split(String regex)` — pattern `"\\s+"` matches one or more
  whitespace characters

### Idiomatic shape

1. Null guard → return `0`.
2. Trim leading/trailing whitespace.
3. If trimmed is empty → return `0`.
4. Split on `"\\s+"` and return the resulting array's length.
