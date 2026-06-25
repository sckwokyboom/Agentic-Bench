package abench.probe;

import java.io.File;
import java.lang.instrument.Instrumentation;
import java.util.*;
import java.util.jar.JarFile;
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

        // CRITICAL: the advice is inlined into the TARGET class, which gradle
        // loads on an isolated test classloader that does NOT see this agent's
        // system-classloader classes. So the inlined calls to Capture/Summary
        // would hit a (swallowed) NoClassDefFoundError → silent empty capture.
        // Put the agent jar on the BOOTSTRAP search so the helpers resolve from
        // any classloader. Capture is lazy/property-driven so whichever copy runs
        // opens the same file.
        try {
            File self = new File(RuntimeProbeAgent.class.getProtectionDomain()
                    .getCodeSource().getLocation().toURI());
            inst.appendToBootstrapClassLoaderSearch(new JarFile(self));
        } catch (Exception e) {
            System.err.println("[probe] bootstrap-inject FAILED: " + e);
        }

        Capture.init(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));
        System.err.println("[probe] premain targets=" + targets
                + " out=" + System.getProperty("runtime.probe.out"));
        Capture.write("{\"probe\":\"premain\",\"targets\":\"" + Capture.esc(String.valueOf(targets)) + "\"}");

        new AgentBuilder.Default()
                .disableClassFormatChanges()
                .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
                .with(AgentBuilder.Listener.StreamWriting.toSystemError().withErrorsOnly())
                .type(namedOneOf(targets.keySet().toArray(new String[0])))
                .transform((builder, typeDesc, classLoader, module, pd) -> {
                    Capture.write("{\"probe\":\"transform\",\"type\":\"" + Capture.esc(typeDesc.getName()) + "\"}");
                    return builder.visit(Advice.to(ProbeAdvice.class)
                            .on(namedOneOf(targets.getOrDefault(typeDesc.getName(), Set.of())
                                    .toArray(new String[0]))));
                })
                .installOn(inst);
        System.err.println("[probe] agent installed");
    }
}
