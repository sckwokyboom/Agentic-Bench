package abench.probe;

import net.bytebuddy.asm.Advice;
import net.bytebuddy.implementation.bytecode.assign.Assigner;

/**
 * Inlined into each allowlisted corridor method (chain mode). Calls ONLY the bootstrap
 * {@link abench.probe.rt.Recorder} — JDK-resolvable from any classloader — never an app-loader
 * helper (that was the swallowed NoClassDefFoundError in the single-target spike). The Recorder
 * maintains the per-thread shadow stack and dumps the active corridor when a TARGET is entered.
 */
public class CorridorAdvice {

    @Advice.OnMethodEnter
    static void enter(@Advice.Origin("#t.#m") String method,
                      @Advice.AllArguments Object[] args) {
        abench.probe.rt.Recorder.enter(method, args);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    static void exit(@Advice.Return(typing = Assigner.Typing.DYNAMIC) Object ret,
                     @Advice.Thrown Throwable thrown) {
        abench.probe.rt.Recorder.exit(ret, thrown);
    }
}
