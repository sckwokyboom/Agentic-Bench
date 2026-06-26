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
        Object boom = new Object() {
            int v = 1;
            @Override public String toString() { throw new RuntimeException("no"); }
        };
        String big = "a".repeat(500);
        Recorder.enter("X.t", new Object[]{big, boom});         // must not throw
        Recorder.exit(null, null);
        String dump = Files.readAllLines(out).stream().filter(l -> l.contains("corridor")).findFirst().orElseThrow();
        assertTrue(dump.contains("…(+"), dump);                 // long value capped
        // toString threw → fell back to a reflective field dump, did not break capture
        assertTrue(dump.contains("v=1"), dump);
    }

    @Test
    void summarize_renders_arrays_collections_maps_with_caps() {
        assertEquals("null", Recorder.summarize(null, 2));
        String arr = Recorder.summarize(new String[]{"a", "b"}, 2);
        assertTrue(arr.contains("[2]") && arr.contains("a") && arr.contains("b"), arr);
        String lst = Recorder.summarize(java.util.List.of("x", "y", "z"), 2);
        assertTrue(lst.contains("(3)") && lst.contains("x") && lst.contains("y"), lst);
        String map = Recorder.summarize(java.util.Map.of("k", 1), 2);
        assertTrue(map.contains("Map(1)") && map.contains("k") && map.contains("1"), map);
        String[] big = new String[50];
        java.util.Arrays.fill(big, "z");
        assertTrue(Recorder.summarize(big, 2).contains("…+"), "long array must be capped");
    }

    @Test
    void summarize_uses_real_toString_but_field_dumps_default_objects() {
        assertEquals("hello", Recorder.summarize("hello", 2));               // String
        assertTrue(Recorder.summarize(java.time.DayOfWeek.MONDAY, 2).contains("MONDAY"));  // enum
        // an object whose class does NOT override toString → reflect its fields so the
        // model still sees what it is + what it holds (the picocli Text[]/object case)
        Object noToString = new Object() { int x = 7; String name = "n"; };
        String s = Recorder.summarize(noToString, 2);
        assertTrue(s.contains("x=7"), s);
        assertTrue(s.contains("name=") && s.contains("n"), s);
    }
}
