# Runtime evidence probe (spike — Plan 1)

A selective Byte Buddy Java agent that, during a sandbox gradle test run, captures
for a single target method: the **call corridor** (stack at entry) + best-effort
**argument strings**, and on exit the **return/throw**. One JSON line per event to
`-Druntime.probe.out`. Used to de-risk the "diff-aware runtime evidence" ablation
(spec: `docs/superpowers/specs/2026-06-24-runtime-evidence-probe-design.md`).

## Build + run

```bash
docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .   # bakes the agent jar
bash docker/runtime-probe/spike.sh                                     # default putValue test
bash docker/runtime-probe/spike.sh picocli.HelpTest.testDemoUsage      # override test
```

## Injection

Attach via **`JAVA_TOOL_OPTIONS=-javaagent:/opt/runtime-probe/agent.jar=<targets> -Druntime.probe.out=<file>`**
(env-based → the forked gradle Test JVM reads it). The gradle `--init-script` path
(`probe-init.gradle`, kept for reference) was **not** confirmed to reach the fork;
JAVA_TOOL_OPTIONS is the reliable channel.

## GO/NO-GO result — **GO** (2026-06-25)

`bash docker/runtime-probe/spike.sh` on the stripped putValue fixture captured a
real corridor + args + throw:

```json
{"method":"picocli.CommandLine$Help$TextTable.putValue","args":["0","0",""],
 "stack":["picocli.CommandLine$Help$TextTable.putValue:17415",
          "picocli.CommandLine$Help$TextTable.addRowValues:17380",
          "picocli.CommandLine$Help.join:16325","…",
          "picocli.CommandLine.usage:2795",
          "picocli.HelpTest.testCatUsageFormat:2331", "org.junit…"]}
{"method":"…putValue","exit":true,"throw":"java.lang.UnsupportedOperationException: TODO: implement putValue"}
```

Conclusion: the corridor is real (test frame present), args are readable. Proceed
to **Plan 2** (host pipeline: parse → rank → diagnostic card → `phased-runtime`).

## Hard-won classloader lesson (for Plan 2)

Byte Buddy `Advice` is **inlined into the target class**, which gradle loads on an
**isolated test classloader**. That CL cannot see the `-javaagent` agent's `app`-CL
classes. Consequences seen during the spike:
- Advice calling helper classes (`Capture`/`Summary`) → swallowed `NoClassDefFoundError`
  → silent empty capture.
- `appendToBootstrapClassLoaderSearch(fat jar)` → Byte Buddy ends up on two loaders
  → `LinkageError: loader constraint violation` on `AgentBuilder.type(...)`; and
  package-private helpers → `IllegalAccessError` across loaders.
- **Working approach (current):** the advice is **fully self-contained, JDK-only**
  (Files/Paths/Thread/StringBuilder — all bootstrap-visible). Byte Buddy stays on
  `app`. No bootstrap injection.

## Plan-2 refinements noticed

- **Trim framework frames** from the corridor: drop `org.junit.*` / runner frames,
  keep app frames (picocli + the test) — the high-signal part.
- **Richer, safe arg summaries**: the spike uses inline `String.valueOf` (cheap,
  but calls `toString`). Plan 2 should use the safe summarizer (`Summary.java`,
  already written + unit-tested) — to inject it into the inlined advice it must be
  on the **bootstrap** loader **without** Byte Buddy (a separate tiny helper jar,
  bootstrap-appended), since the advice can't reach `app`-CL helpers.
- Dedup + rank captures (capture-all-then-rank), cap to a tight card.
