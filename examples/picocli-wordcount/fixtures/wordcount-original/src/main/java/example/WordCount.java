package example;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.Callable;

import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

@Command(
    name = "wordcount",
    mixinStandardHelpOptions = true,
    description = "Counts words in a text file."
)
public class WordCount implements Callable<Integer> {

    @Option(names = {"-i", "--input"}, required = true,
            description = "Input file.")
    Path input;

    @Override
    public Integer call() throws Exception {
        String text = Files.readString(input);
        int count = countWords(text);
        System.out.println(count);
        return 0;
    }

    /**
     * Count the words in {@code text}.
     *
     * <p>A "word" is a maximal run of non-whitespace characters. Leading
     * and trailing whitespace is ignored; multiple whitespace characters
     * between words are treated as a single separator. Returns {@code 0}
     * for {@code null} or all-whitespace input.
     *
     * @param text input text, may be {@code null}
     * @return number of words in {@code text}
     */
    static int countWords(String text) {
        if (text == null) {
            return 0;
        }
        String trimmed = text.trim();
        if (trimmed.isEmpty()) {
            return 0;
        }
        return trimmed.split("\\s+").length;
    }

    public static void main(String[] args) {
        System.exit(new CommandLine(new WordCount()).execute(args));
    }
}
