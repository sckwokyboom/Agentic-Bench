package abench.probe;

import net.bytebuddy.asm.Advice;

/**
 * Inlined into the target method by Byte Buddy. SELF-CONTAINED: uses ONLY JDK
 * classes (java.*, all on the bootstrap loader → resolvable from the target's
 * classloader). It must NOT call helper classes (Capture/Summary) — those live on
 * the agent's 'app' loader, which the instrumented class's (gradle test) loader
 * can't see, so such calls would throw a swallowed NoClassDefFoundError → silent
 * empty capture. Everything is therefore inlined here. (The safe summarizer in
 * Summary.java is reserved for Plan 2, injected via a bootstrap helper jar.)
 *
 * On entry: capture the call corridor (stack AT entry — the target is on the
 * stack now, so the test → … → target path is real) + best-effort arg strings.
 * On exit: the thrown summary (or exitOk). All best-effort; never breaks the method.
 */
public class ProbeAdvice {

    @Advice.OnMethodEnter
    static void enter(@Advice.Origin("#t.#m") String method,
                      @Advice.AllArguments Object[] args) {
        try {
            StringBuilder sb = new StringBuilder("{\"method\":\"");
            sb.append(method.replace("\\", "\\\\").replace("\"", "\\\"")).append("\",\"args\":[");
            for (int i = 0; i < args.length; i++) {
                if (i > 0) sb.append(",");
                Object a = args[i];
                String s;
                if (a == null) {
                    s = "null";
                } else {
                    try { s = String.valueOf(a); } catch (Throwable t) { s = a.getClass().getName() + "@?"; }
                }
                if (s.length() > 200) s = s.substring(0, 200) + "…(+" + (s.length() - 200) + ")";
                s = s.replace("\\", "\\\\").replace("\"", "\\\"")
                     .replace("\n", " ").replace("\r", " ").replace("\t", " ");
                sb.append("\"").append(s).append("\"");
            }
            sb.append("],\"stack\":[");
            int kept = 0;
            for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
                String cn = f.getClassName();
                if (cn.startsWith("java.") || cn.startsWith("jdk.") || cn.startsWith("sun.")
                        || cn.startsWith("net.bytebuddy") || cn.startsWith("abench.probe")
                        || cn.startsWith("org.gradle") || cn.startsWith("worker.org")) continue;
                if (kept > 0) sb.append(",");
                sb.append("\"").append(cn).append(".").append(f.getMethodName())
                  .append(":").append(f.getLineNumber()).append("\"");
                if (++kept >= 25) break;
            }
            sb.append("]}\n");
            java.nio.file.Files.write(
                java.nio.file.Paths.get(System.getProperty("runtime.probe.out", "runtime-capture.jsonl")),
                sb.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8),
                java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (Throwable ignored) {}
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    static void exit(@Advice.Origin("#t.#m") String method,
                     @Advice.Thrown Throwable thrown) {
        try {
            String r;
            if (thrown != null) {
                String msg = thrown.getClass().getName()
                        + (thrown.getMessage() != null ? ": " + thrown.getMessage() : "");
                if (msg.length() > 200) msg = msg.substring(0, 200) + "…";
                msg = msg.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ").replace("\r", " ");
                r = "\"throw\":\"" + msg + "\"";
            } else {
                r = "\"exitOk\":true";
            }
            String line = "{\"method\":\"" + method.replace("\\", "\\\\").replace("\"", "\\\"")
                    + "\",\"exit\":true," + r + "}\n";
            java.nio.file.Files.write(
                java.nio.file.Paths.get(System.getProperty("runtime.probe.out", "runtime-capture.jsonl")),
                line.getBytes(java.nio.charset.StandardCharsets.UTF_8),
                java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
        } catch (Throwable ignored) {}
    }
}
