package abench.probe.rt;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
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
        Recorder.enter("X.target", new Object[]{0, 0, ""});     // TARGET -> triggers a dump
        Recorder.exit(null, new RuntimeException("boom"));      // target throws
        Recorder.exit("Cell[0,1]", null);                       // addRowValues returns a Cell
        Recorder.exit("usage-text", null);

        List<String> lines = Files.readAllLines(out);
        // one corridor dump (target -> callers), with each frame's args
        String dump = lines.stream().filter(l -> l.contains("\"corridor\"")).findFirst().orElseThrow();
        assertTrue(dump.contains("X.target") && dump.contains("\"0\",\"0\",\"\""), dump);
        assertTrue(dump.contains("X.addRowValues") && dump.contains("row0"), dump);
        assertTrue(dump.contains("X.usage") && dump.contains("cat"), dump);
        // exit events carry the throw + returns, keyed by activation id
        assertTrue(lines.stream().anyMatch(l -> l.contains("\"throw\"") && l.contains("boom")), lines.toString());
        assertTrue(lines.stream().anyMatch(l -> l.contains("\"ret\"") && l.contains("Cell[0,1]")), lines.toString());
    }

    @Test
    void non_target_enter_does_not_dump(@TempDir Path dir) throws Exception {
        Path out = dir.resolve("cap.jsonl");
        Recorder.configureForTest(out, Set.of("X.target"));
        Recorder.enter("X.other", new Object[]{1});
        Recorder.exit(42, null);
        List<String> lines = Files.exists(out) ? Files.readAllLines(out) : List.of();
        assertTrue(lines.stream().noneMatch(l -> l.contains("\"corridor\"")), lines.toString());
        assertTrue(lines.stream().anyMatch(l -> l.contains("\"ret\"") && l.contains("42")), lines.toString());
    }

    @Test
    void preview_caps_long_values_and_survives_toString_failure(@TempDir Path dir) throws Exception {
        Path out = dir.resolve("cap.jsonl");
        Recorder.configureForTest(out, Set.of("X.t"));
        Object boom = new Object() { @Override public String toString() { throw new RuntimeException("no"); } };
        String big = "a".repeat(500);
        Recorder.enter("X.t", new Object[]{big, boom});         // must not throw
        Recorder.exit(null, null);
        String dump = Files.readAllLines(out).stream().filter(l -> l.contains("corridor")).findFirst().orElseThrow();
        assertTrue(dump.contains("…(+"), dump);                 // long value capped
        // toString failure degraded to a class-name marker, did not break capture
        assertTrue(dump.contains("@?"), dump);
    }
}
