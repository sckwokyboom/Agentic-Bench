# Runtime Evidence Probe — Spike Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove we can cheaply capture *readable, real* runtime evidence — the actual `test → putValue` call corridor plus the argument values putValue received — during a sandbox gradle test run, via a selective Java agent on one method.

**Architecture:** A tiny Byte Buddy Java agent instruments ONLY the configured target method(s). On each call it snapshots the stack *at entry* (the target is on the stack at that instant → the corridor is real even for assertion bugs) and a safe summary of the arguments, appending one JSON line per call to a capture file in the workdir. The agent is attached to gradle's forked Test JVM via a gradle `--init-script` (no per-project `build.gradle` edit). This plan ends at a **GO/NO-GO gate**: inspect the capture and decide whether to build the host pipeline (Plan 2).

**Tech Stack:** Java 21, Byte Buddy + Gradle Shadow (fat agent jar), Gradle init script (`-javaagent`), the existing docker sandbox + picocli fixture.

**This is Plan 1 of 2.** Plan 2 (capture-parser → ranker → diagnostic card → `phased-runtime` diagnose integration) is written *after* this gate passes, against the capture format this spike actually produces. Do NOT build the host pipeline here.

---

## File Structure

- Create: `docker/runtime-probe/build.gradle` — minimal Gradle build producing the shaded agent jar (Byte Buddy bundled, `Premain-Class` manifest).
- Create: `docker/runtime-probe/settings.gradle` — single-project settings.
- Create: `docker/runtime-probe/src/main/java/abench/probe/RuntimeProbeAgent.java` — `premain`, target parsing, agent install.
- Create: `docker/runtime-probe/src/main/java/abench/probe/ProbeAdvice.java` — `@OnMethodEnter`/`@OnMethodExit` capture.
- Create: `docker/runtime-probe/src/main/java/abench/probe/Summary.java` — safe value summarizer (no `toString`, no deep traversal).
- Create: `docker/runtime-probe/src/main/java/abench/probe/Capture.java` — thread-safe JSONL append + hand-rolled JSON escaping.
- Create: `docker/runtime-probe/src/test/java/abench/probe/SummaryTest.java` — JUnit test for the summarizer.
- Create: `docker/runtime-probe/probe-init.gradle` — the gradle init script that injects `-javaagent` into Test tasks.
- Modify: `docker/Dockerfile.sandbox` — build + bake the agent jar and init script into the image.
- Create: `docker/runtime-probe/README.md` — how to build/run the spike + the GO/NO-GO criteria.

No host-side (`abench/`) changes in this plan — that's Plan 2.

---

## Phase 0 — Ground the target test

- [ ] **Step 1: Find a failing test that actually calls putValue**

The probe needs one covering test to exercise. `coverage.json` lists putValue's coverers.

Run:
```bash
cd /Users/sckwoky/Projects/Agentic-Bench
python3 -c "import json; c=json.load(open('experiments/picocli-putValue/overlays/impact-artifacts/.impact/coverage.json')); k='picocli.CommandLine\$Help\$TextTable.putValue'; print('\n'.join(c.get(k, [])[:10]))"
```
Expected: a list like `picocli.HelpTest.testX`, `picocli.TextTableTest.testY`, … . **Record the first test class** (e.g. `picocli.HelpTest`) — call it `<TARGET_TEST_CLASS>` below. (In the stripped fixture putValue throws, so every coverer fails — any one is fine.)

---

## Task 1: Agent project skeleton + shaded jar build

**Files:**
- Create: `docker/runtime-probe/settings.gradle`
- Create: `docker/runtime-probe/build.gradle`

- [ ] **Step 1: settings.gradle**

```groovy
rootProject.name = 'runtime-probe'
```

- [ ] **Step 2: build.gradle** (Byte Buddy + Shadow fat jar with the agent manifest)

```groovy
plugins {
    id 'java'
    id 'com.github.johnrengelman.shadow' version '8.1.1'
}
repositories { mavenCentral() }
dependencies {
    implementation 'net.bytebuddy:byte-buddy:1.14.18'
    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.2'
}
java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }
test { useJUnitPlatform() }
jar {
    manifest {
        attributes(
            'Premain-Class': 'abench.probe.RuntimeProbeAgent',
            'Can-Retransform-Classes': 'true',
            'Can-Redefine-Classes': 'true'
        )
    }
}
shadowJar {
    archiveBaseName = 'runtime-probe-agent'
    archiveClassifier = ''
    archiveVersion = ''
    manifest { inheritFrom project.tasks.jar.manifest }
}
build.dependsOn shadowJar
```

- [ ] **Step 3: Verify the project configures**

Run: `cd docker/runtime-probe && gradle help -q`
Expected: no errors (gradle resolves the Shadow plugin + Byte Buddy). If `gradle` is absent, use the picocli fixture's `./gradlew` wrapper copied in, or document the required gradle ≥8 in the README.

- [ ] **Step 4: Commit**

```bash
git add docker/runtime-probe/settings.gradle docker/runtime-probe/build.gradle
git commit -m "feat(probe): runtime-probe agent project skeleton (Byte Buddy + Shadow)"
```

---

## Task 2: Safe value summarizer (TDD)

The summarizer must never call `toString()` (side-effect/cost risk), never deep-traverse, never hold object references.

**Files:**
- Create: `docker/runtime-probe/src/main/java/abench/probe/Summary.java`
- Test: `docker/runtime-probe/src/test/java/abench/probe/SummaryTest.java`

- [ ] **Step 1: Write the failing test**

```java
package abench.probe;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class SummaryTest {
    @Test void primitivesAndNull() {
        assertEquals("42", Summary.of(42));
        assertEquals("true", Summary.of(true));
        assertEquals("null", Summary.of(null));
    }
    @Test void stringsAreQuotedAndCapped() {
        assertEquals("\"abc\"", Summary.of("abc"));
        String s = Summary.of("x".repeat(500));
        assertTrue(s.startsWith("\"" + "x".repeat(200)));
        assertTrue(s.contains("…(+300 chars)"));
    }
    @Test void collectionsShowSizeAndHead() {
        assertEquals("[size=3 1, 2, 3]", Summary.of(List.of(1, 2, 3)));
        assertEquals("int[size=4 9, 8, 7, …]", Summary.of(new int[]{9, 8, 7, 6}));
    }
    @Test void otherObjectsAreClassPlusIdentity() {
        Object o = new Object();
        String s = Summary.of(o);
        assertTrue(s.startsWith("Object@"));   // no toString, just class@hash
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/runtime-probe && gradle test --tests abench.probe.SummaryTest`
Expected: FAIL — `Summary` does not exist / compile error.

- [ ] **Step 3: Write minimal implementation**

```java
package abench.probe;
import java.util.Collection;
import java.lang.reflect.Array;

/** Side-effect-free, bounded summaries of runtime values. No toString, no deep
 *  traversal, no holding references. */
public final class Summary {
    private static final int STR_CAP = 200;
    private static final int HEAD = 3;
    private Summary() {}

    public static String of(Object v) {
        if (v == null) return "null";
        if (v instanceof String s) return cap(s);
        if (v instanceof Number || v instanceof Boolean || v instanceof Character) return v.toString();
        if (v instanceof CharSequence cs) return cap(cs.toString());
        if (v.getClass().isArray()) return array(v);
        if (v instanceof Collection<?> c) return collection(c);
        return v.getClass().getSimpleName() + "@" + Integer.toHexString(System.identityHashCode(v));
    }

    private static String cap(String s) {
        if (s.length() <= STR_CAP) return "\"" + s + "\"";
        return "\"" + s.substring(0, STR_CAP) + "…(+" + (s.length() - STR_CAP) + " chars)\"";
    }
    private static String collection(Collection<?> c) {
        StringBuilder b = new StringBuilder("[size=").append(c.size());
        int i = 0; boolean any = false;
        for (Object e : c) { if (i++ == 0) b.append(" "); else if (i <= HEAD) b.append(", ");
            if (i <= HEAD) { b.append(scalar(e)); any = true; } else { b.append(", …"); break; } }
        if (!any && c.isEmpty()) {} return b.append("]").toString();
    }
    private static String array(Object a) {
        int n = Array.getLength(a);
        String comp = a.getClass().getComponentType().getSimpleName();
        StringBuilder b = new StringBuilder(comp).append("[size=").append(n);
        for (int i = 0; i < Math.min(n, HEAD); i++) b.append(i == 0 ? " " : ", ").append(scalar(Array.get(a, i)));
        if (n > HEAD) b.append(", …");
        return b.append("]").toString();
    }
    /** Scalar form for collection/array elements (avoid recursion depth). */
    private static String scalar(Object e) {
        if (e == null) return "null";
        if (e instanceof Number || e instanceof Boolean || e instanceof Character) return e.toString();
        if (e instanceof CharSequence cs) return cap(cs.toString());
        return e.getClass().getSimpleName() + "@" + Integer.toHexString(System.identityHashCode(e));
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd docker/runtime-probe && gradle test --tests abench.probe.SummaryTest`
Expected: PASS (4 tests). Adjust the `[size=3 1, 2, 3]` spacing in the test/impl if the exact format differs — keep them in sync.

- [ ] **Step 5: Commit**

```bash
git add docker/runtime-probe/src/main/java/abench/probe/Summary.java docker/runtime-probe/src/test/java/abench/probe/SummaryTest.java
git commit -m "feat(probe): safe value summarizer (no toString/deep-dump) + tests"
```

---

## Task 3: Capture writer + probe advice + agent entrypoint

**Files:**
- Create: `docker/runtime-probe/src/main/java/abench/probe/Capture.java`
- Create: `docker/runtime-probe/src/main/java/abench/probe/ProbeAdvice.java`
- Create: `docker/runtime-probe/src/main/java/abench/probe/RuntimeProbeAgent.java`

- [ ] **Step 1: Capture.java — thread-safe JSONL append**

```java
package abench.probe;
import java.io.*; import java.nio.file.*; import java.nio.charset.StandardCharsets;

/** Appends one JSON object per captured call to the configured file. Thread-safe;
 *  best-effort (never throws into instrumented code). */
public final class Capture {
    private static Writer out;
    private Capture() {}
    static synchronized void init(String path) {
        try { Files.createDirectories(Paths.get(path).toAbsolutePath().getParent());
              out = new BufferedWriter(new OutputStreamWriter(
                  new FileOutputStream(path, true), StandardCharsets.UTF_8)); }
        catch (Exception e) { out = null; }
    }
    static synchronized void write(String json) {
        if (out == null) return;
        try { out.write(json); out.write('\n'); out.flush(); } catch (IOException ignored) {}
    }
    /** Minimal JSON string escaping. */
    static String esc(String s) {
        StringBuilder b = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) { char c = s.charAt(i);
            switch (c) { case '"' -> b.append("\\\""); case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n"); case '\r' -> b.append("\\r"); case '\t' -> b.append("\\t");
                default -> { if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c); } } }
        return b.toString();
    }
}
```

- [ ] **Step 2: ProbeAdvice.java — capture stack + args at entry, return/throw at exit**

```java
package abench.probe;

/** Inlined into the target method. Captures the corridor (stack AT entry) + arg
 *  summaries; on exit, the return/throw summary. All best-effort. */
public class ProbeAdvice {
    @net.bytebuddy.asm.Advice.OnMethodEnter
    static long enter(@net.bytebuddy.asm.Advice.Origin("#t.#m") String method,
                      @net.bytebuddy.asm.Advice.AllArguments Object[] args) {
        try {
            StringBuilder a = new StringBuilder("[");
            for (int i = 0; i < args.length; i++) { if (i > 0) a.append(","); a.append('"').append(Capture.esc(Summary.of(args[i]))).append('"'); }
            a.append("]");
            StringBuilder st = new StringBuilder("[");
            StackTraceElement[] frames = Thread.currentThread().getStackTrace();
            int kept = 0;
            for (StackTraceElement f : frames) {
                String cn = f.getClassName();
                if (cn.startsWith("abench.probe") || cn.startsWith("java.") || cn.startsWith("jdk.")
                    || cn.startsWith("net.bytebuddy") || cn.startsWith("sun.") || cn.startsWith("worker.org")) continue;
                if (kept > 0) st.append(",");
                st.append('"').append(Capture.esc(cn + "." + f.getMethodName() + ":" + f.getLineNumber())).append('"');
                if (++kept >= 25) break;
            }
            st.append("]");
            Capture.write("{\"method\":\"" + Capture.esc(method) + "\",\"args\":" + a + ",\"stack\":" + st + "}");
        } catch (Throwable ignored) {}
        return System.nanoTime();
    }
    @net.bytebuddy.asm.Advice.OnMethodExit(onThrowable = Throwable.class)
    static void exit(@net.bytebuddy.asm.Advice.Origin("#t.#m") String method,
                     @net.bytebuddy.asm.Advice.Return(typing = net.bytebuddy.implementation.bytecode.assign.Assigner.Typing.DYNAMIC) Object ret,
                     @net.bytebuddy.asm.Advice.Thrown Throwable thrown) {
        try {
            String r = thrown != null ? "\"throw\":\"" + Capture.esc(thrown.getClass().getSimpleName()
                          + (thrown.getMessage() != null ? ": " + thrown.getMessage() : "")) + "\""
                       : "\"return\":\"" + Capture.esc(Summary.of(ret)) + "\"";
            Capture.write("{\"method\":\"" + Capture.esc(method) + "\",\"exit\":true," + r + "}");
        } catch (Throwable ignored) {}
    }
}
```

- [ ] **Step 3: RuntimeProbeAgent.java — premain + selective install**

```java
package abench.probe;
import java.lang.instrument.Instrumentation;
import java.util.*;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** premain agent. agentArgs = comma-separated target method FQNs, e.g.
 *  "picocli.CommandLine$Help$TextTable.putValue". Instruments ONLY those. */
public class RuntimeProbeAgent {
    public static void premain(String agentArgs, Instrumentation inst) {
        Map<String, Set<String>> targets = new HashMap<>();   // className -> methodNames
        for (String t : (agentArgs == null ? "" : agentArgs).split(",")) {
            t = t.trim(); if (t.isEmpty()) continue;
            int dot = t.lastIndexOf('.');
            targets.computeIfAbsent(t.substring(0, dot), k -> new HashSet<>()).add(t.substring(dot + 1));
        }
        if (targets.isEmpty()) return;
        Capture.init(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));
        new AgentBuilder.Default()
            .disableClassFormatChanges()
            .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
            .type(namedOneOf(targets.keySet().toArray(new String[0])))
            .transform((b, td, cl, mod, pd) ->
                b.visit(Advice.to(ProbeAdvice.class)
                    .on(namedOneOf(targets.get(td.getName()).toArray(new String[0])))))
            .installOn(inst);
    }
}
```

- [ ] **Step 4: Build the agent jar**

Run: `cd docker/runtime-probe && gradle shadowJar -q && ls -la build/libs/runtime-probe-agent.jar`
Expected: the jar exists. Verify the manifest:
`unzip -p build/libs/runtime-probe-agent.jar META-INF/MANIFEST.MF | grep Premain-Class`
Expected: `Premain-Class: abench.probe.RuntimeProbeAgent`.

- [ ] **Step 5: Commit**

```bash
git add docker/runtime-probe/src/main/java/abench/probe/Capture.java docker/runtime-probe/src/main/java/abench/probe/ProbeAdvice.java docker/runtime-probe/src/main/java/abench/probe/RuntimeProbeAgent.java
git commit -m "feat(probe): capture writer + entry/exit advice + selective premain agent"
```

---

## Task 4: Gradle init-script injection

**Files:**
- Create: `docker/runtime-probe/probe-init.gradle`

- [ ] **Step 1: probe-init.gradle**

```groovy
// Adds the runtime probe -javaagent to every Test task's FORKED jvm (not the daemon).
// Config via env so no build.gradle edit is needed.
def agentJar = System.getenv('RUNTIME_PROBE_JAR')
def targets  = System.getenv('RUNTIME_PROBE_TARGETS')
def outFile  = System.getenv('RUNTIME_PROBE_OUT')
if (agentJar && targets && outFile) {
    allprojects { p ->
        p.tasks.withType(Test).configureEach { t ->
            t.jvmArgs "-javaagent:${agentJar}=${targets}"
            t.systemProperty 'runtime.probe.out', outFile
            t.outputs.upToDateWhen { false }   // always re-run so the probe always fires
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add docker/runtime-probe/probe-init.gradle
git commit -m "feat(probe): gradle init-script that injects -javaagent into Test JVMs"
```

---

## Task 5: Bake the agent into the sandbox image

**Files:**
- Modify: `docker/Dockerfile.sandbox`

- [ ] **Step 1: Inspect the current Dockerfile to find the JDK/gradle stage**

Run: `grep -n "JDK\|jdk\|gradle\|COPY\|RUN" docker/Dockerfile.sandbox | head -30`
Expected: find where JDK 21 is available (needed to build the jar) and a good place to COPY artifacts.

- [ ] **Step 2: Add a build + bake step** (place after JDK 21 is on PATH)

```dockerfile
# ── Runtime evidence probe (spike) ─────────────────────────────────────────
# Build the Byte Buddy agent jar once and bake it + the init script in, so the
# phased-runtime suite command can attach it to the gradle Test JVM.
COPY docker/runtime-probe /opt/runtime-probe-src
RUN cd /opt/runtime-probe-src && gradle --no-daemon shadowJar \
    && mkdir -p /opt/runtime-probe \
    && cp build/libs/runtime-probe-agent.jar /opt/runtime-probe/agent.jar \
    && cp probe-init.gradle /opt/runtime-probe/probe-init.gradle \
    && rm -rf /opt/runtime-probe-src ~/.gradle/caches/build-cache-1
ENV RUNTIME_PROBE_JAR=/opt/runtime-probe/agent.jar
ENV RUNTIME_PROBE_INIT=/opt/runtime-probe/probe-init.gradle
```
(If `gradle` isn't in the image, add an install step or build the jar on the host in Task 3 and `COPY` the prebuilt jar instead — note whichever you chose in the README.)

- [ ] **Step 3: Rebuild the image**

Run: `docker build -t abench-sandbox:latest -f docker/Dockerfile.sandbox .`
Expected: builds; the jar lands at `/opt/runtime-probe/agent.jar`. Verify:
`docker run --rm abench-sandbox:latest sh -c 'ls -la /opt/runtime-probe && unzip -p /opt/runtime-probe/agent.jar META-INF/MANIFEST.MF | grep Premain'`
Expected: jar present + `Premain-Class` line.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.sandbox
git commit -m "build(sandbox): bake runtime-probe agent jar + init script into the image"
```

---

## Task 6: Run the spike + GO/NO-GO

**Files:** none (empirical run + inspection).

- [ ] **Step 1: Run one covering test under the probe, in the sandbox**

Use the stripped putValue fixture workdir (the method throws → the test fails → we capture the call + the throw). Run the agent-attached suite for `<TARGET_TEST_CLASS>` from Phase 0:

```bash
docker run --rm \
  -v "$(pwd)/experiments/picocli-putValue/<stripped-fixture-dir>:/work" -w /work \
  -e RUNTIME_PROBE_TARGETS='picocli.CommandLine$Help$TextTable.putValue' \
  -e RUNTIME_PROBE_OUT='/work/.runtime-capture.jsonl' \
  abench-sandbox:latest \
  ./gradlew :test --tests '<TARGET_TEST_CLASS>' --continue \
    --init-script /opt/runtime-probe/probe-init.gradle -Dorg.gradle.daemon=false
```
Expected: the test runs and fails (putValue throws). Replace `<stripped-fixture-dir>` with the actual stripped workdir used by the bench (the one with putValue stubbed).

- [ ] **Step 2: Inspect the capture**

Run: `head -5 experiments/picocli-putValue/<stripped-fixture-dir>/.runtime-capture.jsonl`
Expected: JSONL lines like:
```json
{"method":"...TextTable.putValue","args":["0","1","\"a long line…\""],"stack":["picocli.CommandLine$Help$TextTable.addRowValues:88","picocli.HelpTest.testWrap:31",...]}
{"method":"...TextTable.putValue","exit":true,"throw":"UnsupportedOperationException: not implemented"}
```

- [ ] **Step 3: Evaluate the GO/NO-GO criteria** (write findings into `docker/runtime-probe/README.md`)

GO if ALL of:
1. `-javaagent` actually reached the forked Test JVM (capture file is non-empty).
2. The `stack` array contains a **real corridor**: the target method's caller(s) AND a recognizable **test frame** (`<TARGET_TEST_CLASS>....`).
3. The `args` are **readable** (summarized, not garbage / not megabyte dumps).
4. Overhead is acceptable (the single test class still finishes in a sane time).

NO-GO / iterate if: agent didn't attach (init-script didn't reach the fork — try `test.jvmArgumentProviders` or `JAVA_TOOL_OPTIONS` fallback, document); stack has no test frame (filter too aggressive — relax the skip list); args unreadable (tighten `Summary`).

- [ ] **Step 4: Write the README with build/run instructions + the recorded findings + a sample capture line**

```bash
# (author docker/runtime-probe/README.md: how to build the jar, run the spike,
#  the GO/NO-GO result, and a real captured line to hand to Plan 2 as the fixture)
git add docker/runtime-probe/README.md
git commit -m "docs(probe): spike run instructions + GO/NO-GO findings + sample capture"
```

---

## Gate → Plan 2

- [ ] **Step 1: Decision**

If **GO**: the real capture format now exists. Hand the sample `.runtime-capture.jsonl` to Plan 2 (capture-parser → dedup/ranker → diagnostic card → `phased-runtime` diagnose integration), which is written against this exact format. Invoke the writing-plans skill again for Plan 2.

If **NO-GO**: record why in the README. Fall back to the spec's S1 (no-instrumentation failure-corridor card from JUnit XML + offline impact) as the ablation, or revise the capture approach. Do NOT build Plan 2's pipeline on a broken capture.

---

## Self-Review

**Spec coverage (vs `2026-06-24-runtime-evidence-probe-design.md`):**
- "Runtime probe (Byte Buddy, target-only, stack-at-entry + args)" → Tasks 1–3. ✓
- "Safe value summarizer (no toString/deep)" → Task 2. ✓
- "Injection via gradle --init-script + -javaagent" → Tasks 4, baked in 5, exercised in 6. ✓
- "Capture-all (per call), readable" → Task 6 GO criteria. ✓
- "De-risk via putValue vertical slice; GO/NO-GO gate" → Tasks 6 + Gate. ✓
- Retrieval/ranker/card/diagnose-integration/`phased-runtime` condition → **deliberately Plan 2** (needs the real format). Noted, not a gap.
- Invariants (public tests only, evidence-not-fix, provenance, metric-neutral) → apply to Plan 2's card; the spike only captures, so N/A here.

**Placeholder scan:** `<TARGET_TEST_CLASS>` and `<stripped-fixture-dir>` are resolved by concrete commands (Phase 0 Step 1; the bench's known stripped fixture) before use — not unresolved placeholders. No TBD/TODO. Code blocks are complete.

**Type consistency:** `Summary.of` / `Capture.esc` / `Capture.write` / `Capture.init` signatures are used consistently across Advice + agent. Manifest `Premain-Class` matches `RuntimeProbeAgent.premain`. Env var names (`RUNTIME_PROBE_JAR/TARGETS/OUT/INIT`) consistent across init-script, Dockerfile, run command.

Known live risk (correctly deferred to the empirical gate, not a plan defect): whether `--init-script` reaches the *forked* Test JVM in this gradle/sandbox combo — Task 6 Step 3 lists the fallbacks.
