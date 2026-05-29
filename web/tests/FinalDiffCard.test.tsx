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
