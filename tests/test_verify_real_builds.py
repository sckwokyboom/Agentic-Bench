"""REAL Gradle/Maven build smoke tests — exercise the actual build toolchain to
prove detect_verify + run_verify work end-to-end.

These build tiny real Java projects and run `gradle test` / `mvn test`. They skip
if a tool is absent (so CI elsewhere is unaffected). The FIRST run downloads
JUnit + toolchain deps, so the per-test verify timeout is generous (600s).

Notes on the build fixtures (these surface the output the verify parsers read):
- Modern Gradle (9.x) does NOT print the "<N> tests completed, <M> failed"
  summary to the console by default — it only writes the HTML/XML report. The
  parser (parse_gradle_output) needs that line, so the fixture build scripts add
  an `afterSuite` hook that prints it. This is the standard idiom for surfacing
  the summary; it does not change the pass/fail outcome.
- Maven is run as `mvn test` (NOT `mvn -q test`): `-q` suppresses the Surefire
  "Tests run: ..." summary line that parse_maven_surefire needs, so a genuinely
  green build would come back unparseable. Plain `mvn test` prints it.
"""
import shutil
import textwrap
from pathlib import Path

import pytest

from abench.verify import detect_verify, run_verify

GRADLE = shutil.which("gradle")
MVN = shutil.which("mvn")
JAVA = shutil.which("java")

# A `test {}` block that runs JUnit AND prints the root-suite summary line
# ("<N> tests completed, <M> failed") that parse_gradle_output looks for.
_GRADLE_TEST_BLOCK = """
        test {
            useJUnit()
            afterSuite { desc, result ->
                if (!desc.parent) {
                    println "${result.testCount} tests completed, ${result.failedTestCount} failed"
                }
            }
        }
"""


@pytest.mark.skipif(not (GRADLE and JAVA), reason="gradle/java not on PATH")
def test_real_gradle_project_detects_and_runs(tmp_path):
    (tmp_path / "settings.gradle").write_text("rootProject.name='demo'\n")
    (tmp_path / "build.gradle").write_text(textwrap.dedent("""
        plugins { id 'java' }
        repositories { mavenCentral() }
        dependencies { testImplementation 'junit:junit:4.13.2' }
    """) + textwrap.dedent(_GRADLE_TEST_BLOCK))
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(textwrap.dedent("""
        package demo; import org.junit.Test; import static org.junit.Assert.*;
        public class AppTest { @Test public void ok(){ assertEquals(2, 1+1); } }
    """))
    d = detect_verify(tmp_path)
    assert d.system == "gradle"
    v = run_verify(tmp_path, "gradle test", timeout_s=600)
    assert v.status == "passed", v.message
    assert v.passed_count and v.passed_count >= 1


@pytest.mark.skipif(not (MVN and JAVA), reason="mvn/java not on PATH")
def test_real_maven_project_detects_and_runs(tmp_path):
    (tmp_path / "pom.xml").write_text(textwrap.dedent("""
        <project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
        <groupId>demo</groupId><artifactId>demo</artifactId><version>1</version>
        <dependencies><dependency><groupId>junit</groupId><artifactId>junit</artifactId>
        <version>4.13.2</version><scope>test</scope></dependency></dependencies></project>
    """))
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(textwrap.dedent("""
        package demo; import org.junit.Test; import static org.junit.Assert.*;
        public class AppTest { @Test public void ok(){ assertEquals(2, 1+1); } }
    """))
    d = detect_verify(tmp_path)
    assert d.system == "maven"
    v = run_verify(tmp_path, "mvn test", timeout_s=600)
    assert v.status == "passed", v.message
    assert v.passed_count and v.passed_count >= 1


@pytest.mark.skipif(not (GRADLE and JAVA), reason="gradle/java not on PATH")
def test_picocli_like_ambiguous_picks_gradle_not_maven(tmp_path):
    # Gradle project that ALSO ships a stray (broken) pom.xml → must pick gradle, not mvn.
    (tmp_path / "settings.gradle").write_text("rootProject.name='demo'\n")
    (tmp_path / "build.gradle").write_text(textwrap.dedent("""
        plugins { id 'java' }
        repositories { mavenCentral() }
        dependencies { testImplementation 'junit:junit:4.13.2' }
    """) + textwrap.dedent(_GRADLE_TEST_BLOCK))
    (tmp_path / "pom.xml").write_text("<project><broken/>")  # would fail `mvn test`
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(
        "package demo; import org.junit.Test; import static org.junit.Assert.*;"
        " public class AppTest { @Test public void ok(){ assertEquals(2,1+1);} }")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.ambiguous is True
    v = run_verify(tmp_path, d.command, timeout_s=600)
    assert v.status == "passed", v.message
