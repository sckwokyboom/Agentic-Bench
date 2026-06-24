package abench.probe;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class SummaryTest {
    @Test void primitivesAndNull() {
        assertEquals("42", Summary.of(42));
        assertEquals("true", Summary.of(true));
        assertEquals("null", Summary.of(null));
    }

    @Test void stringsAreQuotedAndCapped() {
        assertEquals("\"abc\"", Summary.of("abc"));
        String s = Summary.of("x".repeat(500));
        assertTrue(s.startsWith("\"" + "x".repeat(200)), s);
        assertTrue(s.contains("…(+300 chars)"), s);
    }

    @Test void collectionsShowSizeAndHead() {
        assertEquals("[size=3 1, 2, 3]", Summary.of(List.of(1, 2, 3)));
        assertEquals("int[size=4 9, 8, 7, …]", Summary.of(new int[]{9, 8, 7, 6}));
    }

    @Test void otherObjectsAreClassPlusIdentity() {
        String s = Summary.of(new Object());
        assertTrue(s.startsWith("Object@"), s);   // class@hash, never toString
    }
}
