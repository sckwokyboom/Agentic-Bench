package example;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class WordCountTest {

    @Test
    void emptyAndNull() {
        assertEquals(0, WordCount.countWords(""));
        assertEquals(0, WordCount.countWords("   "));
        assertEquals(0, WordCount.countWords(null));
    }

    @Test
    void singleWord() {
        assertEquals(1, WordCount.countWords("hello"));
        assertEquals(1, WordCount.countWords("   hello   "));
    }

    @Test
    void multipleWords() {
        assertEquals(2, WordCount.countWords("hello world"));
        assertEquals(5, WordCount.countWords("the quick brown fox jumps"));
        assertEquals(3, WordCount.countWords("a\tb\nc"));
    }
}
