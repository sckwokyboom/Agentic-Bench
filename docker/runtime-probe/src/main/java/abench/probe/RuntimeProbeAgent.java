package abench.probe;

import java.lang.instrument.Instrumentation;
import java.util.*;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.namedOneOf;

/**
 * premain agent. {@code agentArgs} = comma-separated target method FQNs, e.g.
 * {@code picocli.CommandLine$Help$TextTable.putValue}. Instruments ONLY those
 * methods (selective → cheap).
 *
 * Byte Buddy + this agent stay on the 'app' (system) classloader; the advice
 * (ProbeAdvice) is fully self-contained with JDK-only classes, so it resolves
 * from the instrumented class's (gradle test) classloader without any bootstrap
 * injection. The capture file path is read by the advice from
 * {@code -Druntime.probe.out}.
 */
public class RuntimeProbeAgent {

    public static void premain(String agentArgs, Instrumentation inst) {
        Map<String, Set<String>> targets = new HashMap<>();   // className -> method names
        for (String t : (agentArgs == null ? "" : agentArgs).split(",")) {
            t = t.trim();
            if (t.isEmpty()) continue;
            int dot = t.lastIndexOf('.');
            if (dot <= 0 || dot == t.length() - 1) continue;
            targets.computeIfAbsent(t.substring(0, dot), k -> new HashSet<>()).add(t.substring(dot + 1));
        }
        if (targets.isEmpty()) return;

        // Mode selects the advice. "single" (default, Plan 2 / phased-runtime): self-contained
        // ProbeAdvice writes {method,args,stack}+{throw} per target. "chain"
        // (phased-runtime-chain): CorridorAdvice feeds the bootstrap Recorder, which keeps a
        // per-thread shadow stack and dumps the active corridor WITH per-frame args on target
        // entry. The instrument set (above) is the target in single mode, the corridor in chain.
        String mode = System.getProperty("runtime.probe.mode", "single");
        Class<?> adviceClass = "chain".equals(mode) ? CorridorAdvice.class : ProbeAdvice.class;

        System.err.println("[probe] premain mode=" + mode + " instrument=" + targets
                + " targets=" + System.getProperty("runtime.probe.targets")
                + " out=" + System.getProperty("runtime.probe.out"));

        new AgentBuilder.Default()
                .disableClassFormatChanges()
                .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
                .with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
                .type(namedOneOf(targets.keySet().toArray(new String[0])))
                .transform((builder, typeDesc, classLoader, module, pd) -> {
                    System.err.println("[probe] transform " + typeDesc.getName());
                    return builder.visit(Advice.to(adviceClass)
                            .on(namedOneOf(targets.getOrDefault(typeDesc.getName(), Set.of())
                                    .toArray(new String[0]))));
                })
                .installOn(inst);
        System.err.println("[probe] agent installed (advice=" + adviceClass.getSimpleName() + ")");
    }
}
