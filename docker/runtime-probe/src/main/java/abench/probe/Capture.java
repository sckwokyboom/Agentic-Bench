package abench.probe;

import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/**
 * Appends one JSON object per captured call to the configured file. Thread-safe;
 * best-effort (never throws into instrumented code).
 */
public final class Capture {
    private static Writer out;
    private Capture() {}

    public static synchronized void init(String path) {
        try {
            Path p = Paths.get(path).toAbsolutePath();
            if (p.getParent() != null) Files.createDirectories(p.getParent());
            out = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(p.toFile(), true), StandardCharsets.UTF_8));
        } catch (Exception e) {
            out = null;   // degrade silently — the run must not fail because of the probe
        }
    }

    public static synchronized void write(String json) {
        // Lazy self-init: with bootstrap injection there can be a second copy of
        // this class (a different classloader) whose init() was never called by
        // premain — open the file from the property on first write so it still
        // captures. Append mode lets multiple copies share the file.
        if (out == null) init(System.getProperty("runtime.probe.out", "runtime-capture.jsonl"));
        if (out == null) return;
        try { out.write(json); out.write('\n'); out.flush(); } catch (IOException ignored) {}
    }

    /** Minimal JSON string escaping. */
    public static String esc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> b.append("\\\"");
                case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n");
                case '\r' -> b.append("\\r");
                case '\t' -> b.append("\\t");
                default -> { if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c); }
            }
        }
        return b.toString();
    }
}
