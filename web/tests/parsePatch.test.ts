import { parsePatch } from "../src/lib/parsePatch";

const sample = `diff --git a/foo.py b/foo.py
index 1..2 100644
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,2 @@
-old
+new
 same
diff --git a/bar.py b/bar.py
new file mode 100644
--- /dev/null
+++ b/bar.py
@@ -0,0 +1,1 @@
+hello
`;

test("splits per-file and counts +/-", () => {
  const files = parsePatch(sample);
  expect(files).toHaveLength(2);
  expect(files[0]!.path).toBe("foo.py");
  expect(files[0]!.added).toBe(1);
  expect(files[0]!.removed).toBe(1);
  expect(files[1]!.path).toBe("bar.py");
  expect(files[1]!.added).toBe(1);
  expect(files[1]!.removed).toBe(0);
});

test("empty patch → empty array", () => {
  expect(parsePatch("")).toEqual([]);
});
