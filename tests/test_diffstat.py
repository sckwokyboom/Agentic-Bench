# tests/test_diffstat.py
from abench.diffstat import parse_diffstat

PATCH = """diff --git a/foo.py b/foo.py
index e69de29..d95f3ad 100644
--- a/foo.py
+++ b/foo.py
@@ -0,0 +1,2 @@
+def foo():
+    return 1
diff --git a/bar.py b/bar.py
index 1111111..2222222 100644
--- a/bar.py
+++ b/bar.py
@@ -1,2 +1,1 @@
-old line one
-old line two
+new line
"""


def test_parse_diffstat_counts_files_and_lines():
    files, added, removed = parse_diffstat(PATCH)
    assert files == 2
    assert added == 3      # +def foo, +return 1, +new line
    assert removed == 2    # -old line one, -old line two


def test_parse_diffstat_empty():
    assert parse_diffstat("") == (0, 0, 0)
