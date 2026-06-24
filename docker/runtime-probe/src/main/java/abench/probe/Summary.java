package abench.probe;

import java.util.Collection;
import java.lang.reflect.Array;

/**
 * Side-effect-free, bounded summaries of runtime values for the probe.
 * NEVER calls {@code toString()} (cost/side-effect risk), never deep-traverses,
 * never holds object references (args are mutable — summarize at capture time).
 */
public final class Summary {
    private static final int STR_CAP = 200;   // max chars of a string before eliding
    private static final int HEAD = 3;        // collection/array elements shown
    private Summary() {}

    public static String of(Object v) {
        if (v == null) return "null";
        if (v instanceof String s) return cap(s);
        if (v instanceof Number || v instanceof Boolean || v instanceof Character) return v.toString();
        if (v instanceof CharSequence cs) return cap(cs.toString());
        if (v.getClass().isArray()) return array(v);
        if (v instanceof Collection<?> c) return collection(c);
        return id(v);
    }

    private static String cap(String s) {
        if (s.length() <= STR_CAP) return "\"" + s + "\"";
        return "\"" + s.substring(0, STR_CAP) + "…(+" + (s.length() - STR_CAP) + " chars)\"";
    }

    private static String collection(Collection<?> c) {
        StringBuilder b = new StringBuilder("[size=").append(c.size());
        int i = 0;
        for (Object e : c) {
            if (i >= HEAD) { b.append(", …"); break; }
            b.append(i == 0 ? " " : ", ").append(scalar(e));
            i++;
        }
        return b.append("]").toString();
    }

    private static String array(Object a) {
        int n = Array.getLength(a);
        StringBuilder b = new StringBuilder(a.getClass().getComponentType().getSimpleName())
                .append("[size=").append(n);
        for (int i = 0; i < n; i++) {
            if (i >= HEAD) { b.append(", …"); break; }
            b.append(i == 0 ? " " : ", ").append(scalar(Array.get(a, i)));
        }
        return b.append("]").toString();
    }

    /** Element form (no recursion into nested collections/objects beyond identity). */
    private static String scalar(Object e) {
        if (e == null) return "null";
        if (e instanceof Number || e instanceof Boolean || e instanceof Character) return e.toString();
        if (e instanceof CharSequence cs) return cap(cs.toString());
        return id(e);
    }

    private static String id(Object v) {
        return v.getClass().getSimpleName() + "@" + Integer.toHexString(System.identityHashCode(v));
    }
}
