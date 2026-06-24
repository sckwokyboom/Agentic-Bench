package abench.probe;

import java.lang.instrument.Instrumentation;
import java.util.*;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.namedOneOf;

/**
 * premain agent. {@code agentArgs} = comma-separated target method FQNs, e.g.
 * {@code picocli.CommandLine$Help$TextTable.putValue}. Instruments ONLY those
 * methods (selective → cheap), writing capture events to the file named by
 * {@code -Druntime.probe.out=...}.
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

        Capture.init(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));

        new AgentBuilder.Default()
                .disableClassFormatChanges()
                .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
                .type(namedOneOf(targets.keySet().toArray(new String[0])))
                .transform((builder, typeDesc, classLoader, module, pd) ->
                        builder.visit(Advice.to(ProbeAdvice.class)
                                .on(namedOneOf(targets.getOrDefault(typeDesc.getName(), Set.of())
                                        .toArray(new String[0])))))
                .installOn(inst);
    }
}
