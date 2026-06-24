package abench.probe;

import net.bytebuddy.asm.Advice;
import net.bytebuddy.implementation.bytecode.assign.Assigner;

/**
 * Inlined into the target method by Byte Buddy. On entry captures the call
 * corridor (stack AT entry — the target IS on the stack now, so the path is real
 * even for assertion bugs) + safe arg summaries. On exit captures the return or
 * thrown summary. All best-effort: never lets the probe break the method.
 */
public class ProbeAdvice {

    @Advice.OnMethodEnter
    static void enter(@Advice.Origin("#t.#m") String method,
                      @Advice.AllArguments Object[] args) {
        try {
            StringBuilder a = new StringBuilder("[");
            for (int i = 0; i < args.length; i++) {
                if (i > 0) a.append(",");
                a.append('"').append(Capture.esc(Summary.of(args[i]))).append('"');
            }
            a.append("]");

            StringBuilder st = new StringBuilder("[");
            int kept = 0;
            for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
                String cn = f.getClassName();
                if (cn.startsWith("abench.probe") || cn.startsWith("java.") || cn.startsWith("jdk.")
                        || cn.startsWith("net.bytebuddy") || cn.startsWith("sun.")
                        || cn.startsWith("org.gradle") || cn.startsWith("worker.org")) continue;
                if (kept > 0) st.append(",");
                st.append('"').append(Capture.esc(cn + "." + f.getMethodName() + ":" + f.getLineNumber())).append('"');
                if (++kept >= 25) break;
            }
            st.append("]");

            Capture.write("{\"method\":\"" + Capture.esc(method) + "\",\"args\":" + a + ",\"stack\":" + st + "}");
        } catch (Throwable ignored) {}
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    static void exit(@Advice.Origin("#t.#m") String method,
                     @Advice.Return(readOnly = true, typing = Assigner.Typing.DYNAMIC) Object ret,
                     @Advice.Thrown Throwable thrown) {
        try {
            String r = thrown != null
                    ? "\"throw\":\"" + Capture.esc(thrown.getClass().getSimpleName()
                        + (thrown.getMessage() != null ? ": " + thrown.getMessage() : "")) + "\""
                    : "\"return\":\"" + Capture.esc(Summary.of(ret)) + "\"";
            Capture.write("{\"method\":\"" + Capture.esc(method) + "\",\"exit\":true," + r + "}");
        } catch (Throwable ignored) {}
    }
}
