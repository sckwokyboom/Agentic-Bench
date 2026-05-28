# putValue — graph slice (placeholder)

This file holds the RAG/graph slice used by the `augmented` condition.
In a real run, your RAG/graph system writes this artefact here before
`abench run`. The harness appends the file's contents to the user
prompt verbatim under the `augmented` condition; it does **not** parse
the structure — formatting is up to your generator.

For a handmade smoke run, replace this file with a hand-written hint
following the same shape as the WordCount example
([`examples/picocli-wordcount/slices/countwords-graph-slice.md`](../../../examples/picocli-wordcount/slices/countwords-graph-slice.md)):

- target node (method, file, visibility)
- documented contract
- callers (edges from the call graph)
- test expectations
- standard-library tools in scope
- idiomatic shape

Until this file is replaced by a real slice, the `augmented` condition
just feeds the agent this placeholder text — which is fine for a
plumbing-only smoke run but doesn't represent the intended treatment.
