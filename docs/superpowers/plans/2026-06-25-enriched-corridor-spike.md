# Enriched Corridor — per-frame runtime values (spike)

> **For agentic workers:** this is a SPIKE (go/no-go) — a vertical slice to de-risk ONE
> technical unknown before any pipeline work. Verify by running, not only by unit tests.
> Builds on the runtime-evidence probe (Plan 1 GO) + host pipeline (Plan 2, `phased-runtime`).

## Hypothesis under test

Passing the agent the **active call corridor target→test with per-frame argument (and
return) values** — not just the target method's args — helps it fix the real contract
faster. This spike proves we can *capture* that cheaply and safely inside the sandbox.
Whether it *helps* is the later A/B (`phased-runtime-chain` vs `phased-runtime` vs `phased`).

This is the cheapest level of the larger evidence-engine vision (the v3 design we
sketched) — a per-thread runtime call-stack recorder, event-mode-lite — NO operand stack,
NO shadow provenance, NO backward slicing, NO static PDG, NO trace-diff, NO external tool
server. Those are built only if this wins.

## The one risk this spike de-risks

`Thread.getStackTrace()` gives only `Class.method:line` — it CANNOT read ancestor frames'
arguments. So per-frame values require instrumenting those methods and holding their args
in a **per-thread shadow stack** (push on enter / pop on exit; dump when the target fires).
picocli's corridor runs through loops (`addRowValues` per row, `putValue` per cell), so a
"log each call, stitch host-side" scheme would be ambiguous across concurrent activations —
the live stack is the only unambiguous source.

That shadow stack must be reachable from advice **inlined into picocli classes on the
gradle test classloader**. The Plan-1 lesson: app-loader helpers → swallowed
`NoClassDefFoundError`; Byte Buddy in a bootstrap fat-jar → `LinkageError` (loader
constraint). **Resolution to validate here:** a tiny **bootstrap-resident recorder jar,
JDK-only, with NO Byte Buddy**. Bootstrap is a parent of every loader → the inlined advice
resolves `Recorder` from picocli's test loader; keeping Byte Buddy out of bootstrap avoids
the loader-constraint violation. GO = this holds in the sandbox with real captures.

## Design (locked defaults)

- **Instrument:** target + its corridor methods (allowlist). For putValue, the observed
  corridor (Plan-1 capture): `putValue`, `addRowValues` (TextTable), `join` (Help),
  `usage` (CommandLine). One uniform advice (enter→`Recorder.enter`, exit→`Recorder.exit`).
- **Dump trigger:** the target(s) only (`-Druntime.probe.targets`). On target *enter*,
  Recorder serializes the current shadow stack = active corridor, each frame WITH its args.
- **Returns:** captured on each frame's *exit* as separate events (keyed by an activation
  id), so the host can attach e.g. `addRowValues`'s returned `Cell` to its corridor frame.
  (At target-enter no enclosing frame has returned yet — returns necessarily arrive later.)
- **Mutant-only:** values come from the agent's run, never the original → no oracle leak.
- **Volume:** allowlist (≤~5 methods), not the whole package → tiny trace, exactly the chain.

## Out of scope (defer until/unless this wins)

Operand stack / shadow provenance / ValueID / DATA-edges; backward dynamic slicing; static
candidate graph + hybrid pruning; original↔mutant trace-diff (baseline run + alignment +
oracle-leak risk); MCP server (the controller already injects the card into DIAGNOSE).

## File structure

- Create: `docker/runtime-probe/recorder/` — a SECOND tiny gradle module producing the
  bootstrap recorder jar (`runtime-probe-recorder.jar`), JDK-only, no deps.
  - `recorder/build.gradle`, `recorder/settings.gradle`
  - `recorder/src/main/java/abench/probe/rt/Recorder.java`
  - `recorder/src/test/java/abench/probe/rt/RecorderTest.java`
- Create: `docker/runtime-probe/src/main/java/abench/probe/CorridorAdvice.java` — enter/exit
  advice that calls the bootstrap `Recorder`.
- Modify: `docker/runtime-probe/src/main/java/abench/probe/RuntimeProbeAgent.java` — accept
  a multi-method allowlist; install `CorridorAdvice` (alongside / instead of `ProbeAdvice`).
- Modify: `docker/runtime-probe/spike.sh` — `-Xbootclasspath/a:recorder.jar` +
  `-javaagent:agent.jar=<allowlist>` + `-Druntime.probe.targets=` + `-Druntime.probe.out=`.
- Modify: `docker/Dockerfile.sandbox` — build + bake `recorder.jar` next to `agent.jar`.

---

## Task 1: Bootstrap recorder (shadow stack) — TDD

**Files:** `docker/runtime-probe/recorder/` (new module)

- [ ] **Step 1: Module skeleton**

`recorder/settings.gradle`:
```groovy
rootProject.name = 'runtime-probe-recorder'
```
`recorder/build.gradle` (JDK-only, no Byte Buddy; uses the same gradle 8.14 wrapper as the parent — copy `gradlew`+`gradle/` from `docker/runtime-probe`):
```groovy
plugins { id 'java' }
repositories { mavenCentral() }
dependencies {
    testImplementation platform('org.junit:junit-bom:5.10.2')
    testImplementation 'org.junit.jupiter:junit-jupiter'
    testRuntimeOnly 'org.junit.platform:junit-platform-launcher'
}
tasks.withType(JavaCompile).configureEach { options.release = 21 }
test { useJUnitPlatform() }
jar { archiveBaseName = 'runtime-probe-recorder'; archiveVersion = '' }
```

- [ ] **Step 2: Failing test** — `recorder/src/test/java/abench/probe/rt/RecorderTest.java`

```java
package abench.probe.rt;

import org.junit.jupiter.api.*;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class RecorderTest {
    @Test
    void dumps_active_corridor_with_per_frame_args_and_exit_returns(@TempDir Path dir) throws Exception {
        Path out = dir.resolve("cap.jsonl");
        Recorder.configureForTest(out, Set.of("X.target"));

        Recorder.enter("X.usage", new Object[]{"cat"});         // outermost
        Recorder.enter("X.addRowValues", new Object[]{"row0"});
        Recorder.enter("X.target", new Object[]{0, 0, ""});     // TARGET → triggers a dump
        Recorder.exit(null, new RuntimeException("boom"));      // target throws
        Recorder.exit("Cell[0,1]", null);                       // addRowValues returns a Cell
        Recorder.exit("usage-text", null);

        List<String> lines = Files.readAllLines(out);
        // one corridor dump (target → callers), with each frame's args
        String dump = lines.stream().filter(l -> l.contains("\"corridor\"")).findFirst().orElseThrow();
        assertTrue(dump.contains("X.target") && dump.contains("\"0\",\"0\",\"\""));
        assertTrue(dump.contains("X.addRowValues") && dump.contains("row0"));
        assertTrue(dump.contains("X.usage") && dump.contains("cat"));
        // exit events carry the throw + returns, keyed by activation id
        assertTrue(lines.stream().anyMatch(l -> l.contains("\"throw\"") && l.contains("boom")));
        assertTrue(lines.stream().anyMatch(l -> l.contains("\"ret\"") && l.contains("Cell[0,1]")));
    }
}
```

- [ ] **Step 3: Implement** — `recorder/src/main/java/abench/probe/rt/Recorder.java`

```java
package abench.probe.rt;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Bootstrap-resident (JDK-only, NO Byte Buddy) per-thread shadow call-stack. The agent's
 *  inlined advice (in picocli classes on the gradle test loader) calls these static methods —
 *  resolvable because this class is on the bootstrap loader, a parent of every loader. Keeping
 *  Byte Buddy OUT of bootstrap avoids the loader-constraint LinkageError from the Plan-1 spike.
 *  Every method is best-effort and never throws into instrumented code. */
public final class Recorder {
    private Recorder() {}

    private static final int CAP = 200;
    private static volatile Path out = Paths.get(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));
    private static volatile Set<String> targets = parse(System.getProperty("runtime.probe.targets", ""));
    private static final AtomicLong SEQ = new AtomicLong();

    private static final class Frame {
        final long id; final String method; final String args;
        Frame(long id, String method, String args) { this.id = id; this.method = method; this.args = args; }
    }
    private static final ThreadLocal<ArrayDeque<Frame>> STACK = ThreadLocal.withInitial(ArrayDeque::new);

    /** Test hook: set output + trigger methods explicitly (props are read at class init). */
    public static void configureForTest(Path o, Set<String> t) { out = o; targets = new HashSet<>(t); }

    public static void enter(String method, Object[] args) {
        try {
            STACK.get().push(new Frame(SEQ.incrementAndGet(), method, previewArgs(args)));
            if (targets.contains(method)) dump(method);
        } catch (Throwable ignored) {}
    }

    public static void exit(Object returned, Throwable thrown) {
        try {
            Frame f = STACK.get().poll();
            if (f == null) return;
            write("{\"act\":" + f.id + ",\"method\":\"" + esc(f.method) + "\",\"exit\":true,"
                + (thrown != null ? "\"throw\":\"" + esc(preview(thrown)) + "\"}"
                                  : "\"ret\":\"" + esc(preview(returned)) + "\"}"));
        } catch (Throwable ignored) {}
    }

    private static void dump(String target) {
        StringBuilder sb = new StringBuilder("{\"target\":\"").append(esc(target)).append("\",\"corridor\":[");
        boolean first = true;
        for (Frame f : STACK.get()) {                       // iteration = top (target) → bottom (caller)
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"act\":").append(f.id).append(",\"method\":\"").append(esc(f.method))
              .append("\",\"args\":").append(f.args).append("}");
        }
        write(sb.append("]}").toString());
    }

    private static Set<String> parse(String s) {
        Set<String> o = new HashSet<>();
        for (String t : s.split(",")) { t = t.trim(); if (!t.isEmpty()) o.add(t); }
        return o;
    }
    private static String previewArgs(Object[] args) {
        if (args == null || args.length == 0) return "[]";
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < args.length; i++) { if (i > 0) b.append(","); b.append("\"").append(esc(preview(args[i]))).append("\""); }
        return b.append("]").toString();
    }
    private static String preview(Object o) {
        String s;
        if (o == null) s = "null";
        else { try { s = String.valueOf(o); } catch (Throwable t) { s = o.getClass().getName() + "@?"; } }
        return s.length() > CAP ? s.substring(0, CAP) + "…(+" + (s.length() - CAP) + ")" : s;
    }
    private static String esc(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ").replace("\r", " ").replace("\t", " ");
    }
    private static synchronized void write(String line) {
        try {
            Files.write(out, (line + "\n").getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Throwable ignored) {}
    }
}
```

- [ ] **Step 4: Pass** — `cd docker/runtime-probe/recorder && ./gradlew test` → green; `./gradlew jar` → `build/libs/runtime-probe-recorder.jar`.

---

## Task 2: Corridor advice + multi-method agent

**Files:** `CorridorAdvice.java` (new), `RuntimeProbeAgent.java` (modify)

- [ ] **Step 1:** `docker/runtime-probe/src/main/java/abench/probe/CorridorAdvice.java`

```java
package abench.probe;

import net.bytebuddy.asm.Advice;
import net.bytebuddy.implementation.bytecode.assign.Assigner;

/** Inlined into each allowlisted method. Calls ONLY the bootstrap Recorder (JDK-resolvable
 *  from any loader) — never an app-loader helper. */
public class CorridorAdvice {
    @Advice.OnMethodEnter
    static void enter(@Advice.Origin("#t.#m") String method, @Advice.AllArguments Object[] args) {
        abench.probe.rt.Recorder.enter(method, args);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    static void exit(@Advice.Return(typing = Assigner.Typing.DYNAMIC) Object ret,
                     @Advice.Thrown Throwable thrown) {
        abench.probe.rt.Recorder.exit(ret, thrown);
    }
}
```

> **Spike risk to confirm:** `@Advice.Return(typing = DYNAMIC)` on a `void` corridor method —
> Byte Buddy should bind `null`. If it rejects void methods, split into two advices (one with
> `@Advice.Return`, one without) selected by a returns-value matcher, OR drop returns for void
> frames. Verify in Task 4.

- [ ] **Step 2:** In `RuntimeProbeAgent.premain`, install `CorridorAdvice` on the allowlist
(reuse the existing `Map<className, Set<method>>` parse of `agentArgs`; just more entries),
and pass the recorder's targets via the existing `-Druntime.probe.targets`. The agent jar
build (`./gradlew jar`) is unchanged — Byte Buddy stays app-only, `recorder.jar` is separate.

- [ ] **Step 3:** `cd docker/runtime-probe && ./gradlew jar` → `runtime-probe-agent.jar` builds.

---

## Task 3: Bootstrap wiring + bake

**Files:** `spike.sh`, `docker/Dockerfile.sandbox`

- [ ] **Step 1:** `spike.sh` sets (note the allowlist FQNs + targets):
```bash
ALLOW="picocli.CommandLine\$Help\$TextTable.putValue,picocli.CommandLine\$Help\$TextTable.addRowValues,picocli.CommandLine\$Help.join,picocli.CommandLine.usage"
export JAVA_TOOL_OPTIONS="-Xbootclasspath/a:/opt/runtime-probe/recorder.jar \
  -javaagent:/opt/runtime-probe/agent.jar=${ALLOW} \
  -Druntime.probe.targets=picocli.CommandLine\$Help\$TextTable.putValue \
  -Druntime.probe.out=${OUT}"
```
- [ ] **Step 2:** `Dockerfile.sandbox` builds BOTH jars (recorder + agent) in-image and copies
to `/opt/runtime-probe/recorder.jar` and `/opt/runtime-probe/agent.jar`.

---

## Task 4: GO / NO-GO

- [ ] Run `bash docker/runtime-probe/spike.sh` on the stripped putValue fixture (default test
`picocli.HelpTest.testCatUsageFormat`).
- [ ] **GO requires** the capture JSONL contains, with NO `NoClassDefFoundError` /
`LinkageError` / verifier errors in stderr:
  - one `corridor` dump with frames `putValue → addRowValues → join → usage`, **each with its
    own runtime args** (e.g. putValue `["0","0",""]`, addRowValues with its row text);
  - exit events carrying the target `throw` and at least one enclosing **return** (e.g.
    `addRowValues` → a `Cell`).
- [ ] Confirm volume is small (allowlist only) and the `void`-return binding worked (or record
the fallback taken).

**If NO-GO** (bootstrap recorder still unreachable / loader error): fallback is the
self-contained-advice + host-correlation scheme (each method writes its own args line; stitch
by thread+activation host-side) — accept the loop-ambiguity caveat. Record which path won in
`README.md`, as Plan 1 did.

---

## If GO → follow-up (separate plan, mirrors Plan 2)

Host pipeline: extend `runtime_evidence.py` to parse the `corridor` dump + join exit `ret`/
`throw` by `act` → an **enriched card** (each hop: `method(args) → ret`), and add condition
`phased-runtime-chain`. Then the A/B: `phased` vs `phased-runtime` (target args) vs
`phased-runtime-chain` (per-frame args+returns) — comparable by trace (prompts are now visible).

## Self-review

- **Risk-first:** the single unknown (bootstrap shadow-stack reachable from inlined advice, no
  Byte Buddy on bootstrap) is exactly what Task 4 proves; everything else is mechanical.
- **Reuses GO'd pieces:** same gradle wrapper, same self-contained-advice discipline (advice
  calls only bootstrap/JDK), same `JAVA_TOOL_OPTIONS` channel, same capture-file convention.
- **Validity:** mutant-only (no original baseline) → no oracle leak; evidence-not-fix card.
- **No placeholders:** Recorder + advice + test are complete; the allowlist FQNs are the real
  Plan-1-observed corridor.
- **Honest scope:** returns of enclosing frames arrive post-target (captured via exit events,
  joined host-side), not at the dump instant — stated, not hidden.
