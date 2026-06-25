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

    private static final int CAP = 200;
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
        String s;
        if (o == null) {
            s = "null";
        } else {
            try { s = String.valueOf(o); } catch (Throwable t) { s = o.getClass().getName() + "@?"; }
        }
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
