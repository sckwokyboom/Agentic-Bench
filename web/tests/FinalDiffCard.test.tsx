import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import FinalDiffCard from "../src/components/FinalDiffCard";

const patch = `diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-old
+new
`;

test("renders parsed diff", async () => {
  mswServer.use(http.get("/api/runs/exp/cond/0/patch", () =>
    new HttpResponse(patch, { headers: { "content-type": "text/plain" } })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <FinalDiffCard name="exp" condition="cond" rep={0} />
    </QueryClientProvider>,
  );
  await waitFor(() =>
    expect(screen.getByText(/Final diff/)).toBeInTheDocument(),
  );
  expect(screen.getByText("foo.py")).toBeInTheDocument();
});

const fourFilePatch = ["a", "b", "c", "d"]
  .map((n) => `diff --git a/${n}.py b/${n}.py
--- a/${n}.py
+++ b/${n}.py
@@ -1,1 +1,1 @@
-old
+new
`)
  .join("");

test("shows all 4 files in a short 4-file diff (no silent truncation)", async () => {
  mswServer.use(http.get("/api/runs/exp/cond/1/patch", () =>
    new HttpResponse(fourFilePatch, { headers: { "content-type": "text/plain" } })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <FinalDiffCard name="exp" condition="cond" rep={1} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText(/4 files/)).toBeInTheDocument());
  // The 4th file must be visible — it was previously dropped by slice(0,3)
  // with no "show all" toggle to reveal it.
  expect(screen.getByText("d.py")).toBeInTheDocument();
});
