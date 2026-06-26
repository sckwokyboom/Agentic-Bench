package abench.probe.rt;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Bootstrap-resident (JDK-only, NO Byte Buddy) per-thread shadow call-stack. The agent's
 * inlined advice (in picocli classes on the gradle test loader) calls these static methods —
 * resolvable because this class is on the bootstrap loader, a parent of every loader. Keeping
 * Byte Buddy OUT of bootstrap avoids the loader-constraint LinkageError from the earlier spike.
 *
 * <p>On each instrumented method: {@code enter} pushes (method, argsPreview); when a configured
 * TARGET is entered, the current stack is dumped = the active corridor, each frame WITH its args.
 * {@code exit} pops and records the frame's return/throw (keyed by activation id) so the host can
 * attach e.g. an enclosing method's returned value to its corridor frame.
 *
 * <p>Every method is best-effort and never throws into instrumented code.
 */
public final class Recorder {
    private Recorder() {}

    private static final int CAP = 200;          // max chars per rendered value
    private static final int MAX_DEPTH = 2;      // nested-object recursion depth
    private static final int MAX_ELEMS = 8;      // array/collection/map elements shown
    private static final int MAX_FIELDS = 10;    // object fields shown in a reflective dump
    private static volatile Path out =
            Paths.get(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));
    private static volatile Set<String> targets =
            parse(System.getProperty("runtime.probe.targets", ""));
    private static final AtomicLong SEQ = new AtomicLong();

    private static final class Frame {
        final long id;
        final String method;
        final String args;
        Frame(long id, String method, String args) { this.id = id; this.method = method; this.args = args; }
    }

    private static final ThreadLocal<ArrayDeque<Frame>> STACK = ThreadLocal.withInitial(ArrayDeque::new);

    /** Test hook: set output + trigger methods explicitly (props are read at class init). */
    public static void configureForTest(Path o, Set<String> t) {
        out = o;
        targets = new HashSet<>(t);
        STACK.get().clear();
    }

    public static void enter(String method, Object[] args) {
        try {
            STACK.get().push(new Frame(SEQ.incrementAndGet(), method, previewArgs(args)));
            if (targets.contains(method)) dump(method);
        } catch (Throwable ignored) {}
    }

    public static void exit(Object returned, Throwable thrown) {
        try {
            Frame f = STACK.get().poll();           // pop the frame we are leaving
            if (f == null) return;
            write("{\"act\":" + f.id + ",\"method\":\"" + esc(f.method) + "\",\"exit\":true,"
                    + (thrown != null ? "\"throw\":\"" + esc(preview(thrown)) + "\"}"
                                      : "\"ret\":\"" + esc(preview(returned)) + "\"}"));
        } catch (Throwable ignored) {}
    }

    private static void dump(String target) {
        StringBuilder sb = new StringBuilder("{\"target\":\"").append(esc(target)).append("\",\"corridor\":[");
        boolean first = true;
        for (Frame f : STACK.get()) {               // iteration order: top (target) -> bottom (caller)
            if (!first) sb.append(",");
            first = false;
            sb.append("{\"act\":").append(f.id)
              .append(",\"method\":\"").append(esc(f.method))
              .append("\",\"args\":").append(f.args).append("}");
        }
        write(sb.append("]}").toString());
    }

    private static Set<String> parse(String s) {
        Set<String> o = new HashSet<>();
        for (String t : s.split(",")) {
            t = t.trim();
            if (!t.isEmpty()) o.add(t);
        }
        return o;
    }

    private static String previewArgs(Object[] args) {
        if (args == null || args.length == 0) return "[]";
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < args.length; i++) {
            if (i > 0) b.append(",");
            b.append("\"").append(esc(preview(args[i]))).append("\"");
        }
        return b.append("]").toString();
    }

    private static String preview(Object o) {
        return summarize(o, MAX_DEPTH);
    }

    /**
     * LLM-friendly value rendering. Primitives/String/enum render directly; arrays,
     * collections and maps show their (capped) contents; an object with a real
     * (overridden) toString uses it; an object with only the DEFAULT toString
     * ({@code Class@hex}) — or one whose toString throws — is reflected into
     * {@code ClassName{field=value, …}} so the model still sees what it is and what
     * it holds. Bounded by depth/element/field/length caps; never throws.
     */
    static String summarize(Object o, int depth) {
        try {
            if (o == null) return "null";
            Class<?> c = o.getClass();
            if (o instanceof CharSequence || o instanceof Number || o instanceof Boolean
                    || o instanceof Character || o instanceof Enum) {
                return cap(String.valueOf(o));
            }
            if (c.isArray()) {
                int n = java.lang.reflect.Array.getLength(o);
                int show = Math.min(n, MAX_ELEMS);
                StringBuilder b = new StringBuilder(c.getComponentType().getSimpleName())
                        .append("[").append(n).append("]{");
                for (int i = 0; i < show; i++) {
                    if (i > 0) b.append(", ");
                    b.append(depth <= 0 ? "…" : summarize(java.lang.reflect.Array.get(o, i), depth - 1));
                }
                if (n > show) b.append(", …+").append(n - show);
                return cap(b.append("}").toString());
            }
            if (o instanceof java.util.Map) {
                java.util.Map<?, ?> m = (java.util.Map<?, ?>) o;
                StringBuilder b = new StringBuilder("Map(").append(m.size()).append("){");
                int i = 0;
                for (java.util.Map.Entry<?, ?> e : m.entrySet()) {
                    if (i >= MAX_ELEMS) { b.append(", …"); break; }
                    if (i > 0) b.append(", ");
                    b.append(depth <= 0 ? "…"
                            : summarize(e.getKey(), depth - 1) + "=" + summarize(e.getValue(), depth - 1));
                    i++;
                }
                return cap(b.append("}").toString());
            }
            if (o instanceof java.util.Collection) {
                java.util.Collection<?> col = (java.util.Collection<?>) o;
                StringBuilder b = new StringBuilder(c.getSimpleName()).append("(").append(col.size()).append("){");
                int i = 0;
                for (Object e : col) {
                    if (i >= MAX_ELEMS) { b.append(", …"); break; }
                    if (i > 0) b.append(", ");
                    b.append(depth <= 0 ? "…" : summarize(e, depth - 1));
                    i++;
                }
                return cap(b.append("}").toString());
            }
            String s = safeToString(o);
            String dflt = c.getName() + "@" + Integer.toHexString(System.identityHashCode(o));
            if (s != null && !s.equals(dflt)) return cap(s);     // a real, overridden toString
            return cap(fieldDump(o, c, depth));                  // default/failed toString → fields
        } catch (Throwable t) {
            return o.getClass().getSimpleName() + "@?";
        }
    }

    private static String fieldDump(Object o, Class<?> c, int depth) {
        StringBuilder b = new StringBuilder(c.getSimpleName()).append("{");
        int i = 0;
        for (java.lang.reflect.Field f : c.getDeclaredFields()) {
            int mod = f.getModifiers();
            if (java.lang.reflect.Modifier.isStatic(mod) || f.isSynthetic()) continue;
            if (i >= MAX_FIELDS) { b.append(", …"); break; }
            Object v;
            try { f.setAccessible(true); v = f.get(o); }
            catch (Throwable t) { continue; }     // inaccessible (module system) → skip
            if (i > 0) b.append(", ");
            b.append(f.getName()).append("=").append(depth <= 0 ? "…" : summarize(v, depth - 1));
            i++;
        }
        return b.append("}").toString();
    }

    private static String safeToString(Object o) {
        try { return o.toString(); } catch (Throwable t) { return null; }
    }

    private static String cap(String s) {
        return s.length() > CAP ? s.substring(0, CAP) + "…(+" + (s.length() - CAP) + ")" : s;
    }

    private static String esc(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", " ").replace("\r", " ").replace("\t", " ");
    }

    private static synchronized void write(String line) {
        try {
            Files.write(out, (line + "\n").getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Throwable ignored) {}
    }
}
