# Agentic-Bench Web UI — Frontend Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React 18 + MUI v5 + Vite frontend for the Agentic-Bench Web UI v1 — four pages (ExperimentList, ExperimentEdit, Run, TraceView) talking to the FastAPI backend delivered by Plan A through REST + WebSocket, with rjsf-mui rendering the form from the live `/api/schema`.

**Architecture:** SPA built by Vite, served by the same FastAPI process from `abench_ui/static/` (single port, no CORS). REST data via TanStack Query; live ReAct stream via a single WebSocket hook with `last_event_id` replay. Pydantic JSON Schema is the single source of form truth — rjsf-mui validates exactly like the backend. Trace and run artefacts come from REST endpoints already exposed by Plan A.

**Tech Stack:** React 18, MUI v5, Vite 5, TypeScript 5, react-router-dom 6, @tanstack/react-query 5, @rjsf/mui + @rjsf/validator-ajv8, vitest 1 + @testing-library/react 16 + jsdom, msw 2 (request mocking for hook tests).

**Spec:** [`docs/superpowers/specs/2026-05-29-web-ui-design.md`](../specs/2026-05-29-web-ui-design.md) — section §7 (UI screens), §6 (REST/WS contract), §10 (KV isolation).

**Backend plan (already shipped — context):** [`docs/superpowers/plans/2026-05-29-web-ui-backend.md`](2026-05-29-web-ui-backend.md). 106 backend tests green. API contract is frozen and the source of truth for types.

**Out of scope:** v2 comparison view, v2 heavyweight isolation, plots, wizard. The deferred-from-Plan-A items live in optional Task 8.

---

## File Structure

```
web/                                  # frontend sources (not pip-installed)
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  .gitignore                          # node_modules, dist
  src/
    main.tsx                          # ReactDOM root + QueryClient + Router + theme
    App.tsx                           # top bar + sidebar nav + <Outlet/>
    theme.ts                          # MUI theme (single light theme v1)
    routes.tsx                        # react-router-dom route table
    api/
      types.ts                        # hand-written TS mirrors of API responses
      client.ts                       # typed fetch wrapper (json/text/raw)
      queries.ts                      # TanStack Query hooks for every REST endpoint
      schemaCache.ts                  # one-shot loader for /api/schema
    ws/
      useRunSession.ts                # WebSocket hook (reconnect + last_event_id)
      envelope.ts                     # Envelope union types
    pages/
      ExperimentList.tsx
      ExperimentEdit.tsx
      Run.tsx
      TraceView.tsx
    components/
      StatusPill.tsx                  # ExperimentList: ready / running / no fixture
      UploadYamlButton.tsx            # ExperimentList: <input type=file> + POST upload
      DeleteExperimentDialog.tsx
      NewExperimentDialog.tsx
      ValidationPanel.tsx             # ExperimentEdit right-panel card
      PlanPanel.tsx                   # ExperimentEdit right-panel card
      FixturesPanel.tsx               # ExperimentEdit right-panel card
      PreviousRunsPanel.tsx           # ExperimentEdit right-panel card
      ModelValidationChip.tsx         # ExperimentEdit custom rjsf widget
      AddApiKeyDialog.tsx
      TargetMethodsChips.tsx          # ExperimentEdit custom rjsf widget
      AugmentationField.tsx           # ExperimentEdit custom rjsf widget
      ProgressHeader.tsx              # Run page header
      RunSidebar.tsx                  # Run page per-rep cards
      RunSidebarCard.tsx
      VerifyChip.tsx                  # shared (Run sidebar + TraceView)
      IsolationChip.tsx               # Run page chip-row
      EventStream.tsx                 # Run page main feed (live)
      EventFilterBar.tsx              # Run page filters
      VerdictBanner.tsx               # TraceView header
      AggregateStatsBar.tsx           # TraceView stop-reason histogram + tokens
      TurnCard.tsx                    # TraceView one turn = one messageID
      ToolCallBlock.tsx               # TraceView per-turn tool row
      RawEventsToggle.tsx             # TraceView "show raw ▾" inside TurnCard
      VerifyCard.tsx                  # TraceView verify result
      FinalDiffCard.tsx               # TraceView inline unified diff
      MethodComparisonCard.tsx        # TraceView side-by-side
      MetricsDrawer.tsx               # TraceView right drawer
      FooterNav.tsx                   # TraceView prev/next rep
    lib/
      groupEventsByTurn.ts            # raw OpenCode events → turn-keyed groups
      stopReasonHistogram.ts          # turns[] → {reason: count}
      parsePatch.ts                   # unified diff → file hunks
      formatDuration.ts
      formatTokens.ts
      computePlan.ts                  # (conditions × reps) → run count + ETA
  tests/                              # vitest
    setup.ts                          # msw + jsdom + @testing-library setup
    api.client.test.ts
    schemaCache.test.ts
    groupEventsByTurn.test.ts
    stopReasonHistogram.test.ts
    parsePatch.test.ts
    StatusPill.test.tsx
    ModelValidationChip.test.tsx
    TurnCard.test.tsx
    VerifyCard.test.tsx
    FinalDiffCard.test.tsx
    EventStream.test.tsx
    useRunSession.test.ts

abench_ui/                            # backend — minor edits in Task 7
  server.py                           # mount StaticFiles + SPA fallback
  cli.py                              # warn if bundle missing
  static/                             # gitignored — built bundle lands here
```

---

## Conventions used in every task

- Each frontend file uses TypeScript (`.ts`/`.tsx`). No JavaScript files.
- All components default-export a named functional component. Props use a local `Props` interface above the component.
- Tests live under `web/tests/` (not co-located) — the test runner picks them up from `vitest.config` glob.
- MUI styling: `sx` prop for one-offs, `styled()` only when the same styled element is reused. No CSS-in-JS files in v1.
- Imports order: external → MUI → app `api/` `ws/` `lib/` `components/` → relative. Vitest enforces nothing here; just be consistent.
- Tests run from `web/` root: `npm test -- --run` for one-shot.
- **All commits live on `main`** (the user is solo on this repo and the backend plan already did the same — small, focused commits, never amending).

---

## Task 0: Scaffold `web/` with Vite + React + TS + MUI + rjsf-mui

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/.gitignore`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/theme.ts`
- Create: `web/src/routes.tsx`
- Create: `web/tests/setup.ts`
- Create: `web/vitest.config.ts`
- Modify: `.gitignore` (repo root — ignore `web/node_modules`, `web/dist`, `abench_ui/static`)

- [ ] **Step 1: Write `web/package.json`**

```json
{
  "name": "abench-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@emotion/react": "^11.13.0",
    "@emotion/styled": "^11.13.0",
    "@mui/icons-material": "^5.16.0",
    "@mui/material": "^5.16.0",
    "@rjsf/core": "^5.20.0",
    "@rjsf/mui": "^5.20.0",
    "@rjsf/utils": "^5.20.0",
    "@rjsf/validator-ajv8": "^5.20.0",
    "@tanstack/react-query": "^5.50.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.0",
    "msw": "^2.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 2: Write `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": false,
    "useDefineForClassFields": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "tests", "vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 3: Write `web/vite.config.ts`**

The proxy lets `npm run dev` hit the FastAPI backend on `8765` for both REST and WS without CORS.

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  build: {
    // Production bundle lands in abench_ui/static/ so FastAPI can serve it.
    outDir: path.resolve(__dirname, "../abench_ui/static"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/ws":  { target: "ws://127.0.0.1:8765", ws: true, changeOrigin: true },
    },
  },
});
```

- [ ] **Step 4: Write `web/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false,
  },
});
```

- [ ] **Step 5: Write `web/tests/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";

// Shared MSW server — tests import this and call .use(handler) to add per-test handlers.
export const mswServer = setupServer();

beforeAll(() => mswServer.listen({ onUnhandledRequest: "error" }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());
```

- [ ] **Step 6: Write `web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Agentic-Bench</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Write `web/src/theme.ts`**

```ts
import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1976d2" },
    success: { main: "#2e7d32" },
    warning: { main: "#ed6c02" },
    error:   { main: "#d32f2f" },
    background: { default: "#fafafa" },
  },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: 14,
  },
  shape: { borderRadius: 6 },
});
```

- [ ] **Step 8: Write `web/src/routes.tsx`**

```tsx
import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import ExperimentList from "./pages/ExperimentList";
import ExperimentEdit from "./pages/ExperimentEdit";
import Run from "./pages/Run";
import TraceView from "./pages/TraceView";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/experiments" replace /> },
      { path: "experiments", element: <ExperimentList /> },
      { path: "experiments/:name", element: <ExperimentEdit /> },
      { path: "runs/sessions/:sid", element: <Run /> },
      { path: "runs/:name/:condition/:rep", element: <TraceView /> },
    ],
  },
]);
```

- [ ] **Step 9: Write `web/src/App.tsx`**

```tsx
import { AppBar, Box, Toolbar, Typography } from "@mui/material";
import { Outlet, NavLink } from "react-router-dom";

const linkStyle = { color: "white", textDecoration: "none", marginLeft: 24 };

export default function App() {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 0 }}>Agentic-Bench</Typography>
          <NavLink to="/experiments" style={linkStyle}>Experiments</NavLink>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ flexGrow: 1, overflow: "auto", p: 3 }}>
        <Outlet />
      </Box>
    </Box>
  );
}
```

- [ ] **Step 10: Write `web/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { ThemeProvider, CssBaseline } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { theme } from "./theme";
import { router } from "./routes";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 11: Write page stubs so routing builds**

`web/src/pages/ExperimentList.tsx`:
```tsx
export default function ExperimentList() { return <div>ExperimentList</div>; }
```

`web/src/pages/ExperimentEdit.tsx`:
```tsx
export default function ExperimentEdit() { return <div>ExperimentEdit</div>; }
```

`web/src/pages/Run.tsx`:
```tsx
export default function Run() { return <div>Run</div>; }
```

`web/src/pages/TraceView.tsx`:
```tsx
export default function TraceView() { return <div>TraceView</div>; }
```

- [ ] **Step 12: Write `web/.gitignore`**

```
node_modules
dist
.vite
```

- [ ] **Step 13: Append to repo-root `.gitignore`**

Append these lines if not already present:
```
web/node_modules
web/dist
abench_ui/static/
```

- [ ] **Step 14: Write a smoke test that App renders**

`web/tests/App.smoke.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import App from "../src/App";

test("App renders the top-bar title", () => {
  render(
    <MemoryRouter>
      <Routes><Route path="/" element={<App />} /></Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("Agentic-Bench")).toBeInTheDocument();
});
```

- [ ] **Step 15: Install and run tests**

```bash
cd web
npm install
npm test -- --run
```
Expected: 1 test passes (`App renders the top-bar title`).

- [ ] **Step 16: Verify dev build succeeds**

```bash
cd web && npm run build
```
Expected: `vite build` finishes with no errors; `abench_ui/static/index.html` exists.

- [ ] **Step 17: Commit**

```bash
git add web/ .gitignore
git commit -m "feat(ui/web): scaffold Vite + React + MUI + rjsf-mui"
```

---

## Task 1: API client + TypeScript types + TanStack Query hooks

**Files:**
- Create: `web/src/api/types.ts`
- Create: `web/src/api/client.ts`
- Create: `web/src/api/queries.ts`
- Create: `web/tests/api.client.test.ts`

The backend OpenAPI is canonical, but for v1 we hand-write the response shapes — this keeps the dependency surface small and the types align 1:1 with the endpoints described in §6 of the spec and confirmed against `abench_ui/server.py`.

- [ ] **Step 1: Write `web/src/api/types.ts`**

```ts
// Mirrors the JSON shapes returned by abench_ui FastAPI endpoints.
// Hand-written from spec §6 + server.py — refresh when contract changes.

export interface ExperimentSummary {
  name: string;
  has_fixture: boolean;
  has_reference: boolean;
  has_runs: boolean;
  last_run_at: string | null;
}

export interface RunSummary {
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  verify_status: VerifyStatus | null;
  success: boolean | null;
  started_at: string;
}

export type VerifyStatus = "passed" | "failed" | "skipped" | "error" | "timeout";

export interface VerifySummary {
  status: VerifyStatus | null;
  passed_count: number | null;
  failed_count: number | null;
  failed_names: string[];
  command: string | null;
  duration_s: number | null;
}

export interface MetricsJson {
  finished: boolean;
  interrupted_reason: string | null;
  success: boolean | null;
  verify_status: VerifyStatus | null;
  verify_command: string | null;
  verify_duration_s: number | null;
  verify_passed_count: number | null;
  verify_failed_count: number | null;
  verify_failed_names?: string[];
  isolation_nonce?: string | null;
  // The whole metrics.json blob is more than this; rest is rendered raw.
  [key: string]: unknown;
}

export interface TurnInfo {
  message_id: string;
  reason: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_reasoning: number | null;
  cost: number | null;
  started_at: number | null;
  ended_at: number | null;
}

export interface FileChange { path: string; added: number; removed: number; }
export interface FinalDiffSummary {
  files: FileChange[];
  total_added: number;
  total_removed: number;
}

export interface Trace {
  turns: TurnInfo[];
  verify_status: VerifyStatus | null;
  verify_command: string | null;
  verify_duration_s: number | null;
  verify_passed_count: number | null;
  verify_failed_count: number | null;
  verify_failed_names: string[];
  verify_baseline_unknown: boolean;
  isolation_nonce: string | null;
  final_diff_summary: FinalDiffSummary | null;
  // Rest of trace.json — Step[] etc. — passed through.
  [key: string]: unknown;
}

export interface MethodComparison {
  method_name: string;
  original_lines: string[];
  regen_lines: string[];
  equivalent: boolean;
}

export interface ValidateModelResp {
  // Backend literals from abench_ui/validate.py:
  //   ok             → key configured, model found in catalog
  //   no_credentials → provider has no API key in auth.json
  //   model_not_found→ provider configured but model id not in catalog
  //   malformed      → model id missing provider/ prefix
  status: "ok" | "no_credentials" | "model_not_found" | "malformed";
  provider: string | null;
  suggestions: string[];
}

export interface ProviderEntry { id: string; configured: boolean; }

export interface SessionState {
  state: "pending" | "running" | "completed" | "cancelled" | "failed";
  started_at: number | null;
  ended_at: number | null;
  total_runs: number;
  current_condition: string | null;
  current_rep: number | null;
}

export interface ApiError {
  status: number;
  detail: string | unknown;
}
```

- [ ] **Step 2: Write the failing test for `client.ts`**

`web/tests/api.client.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import { http, HttpResponse } from "msw";
import { apiGet, apiPut, apiPostJson, apiDelete, ApiError } from "../src/api/client";

describe("api.client", () => {
  it("apiGet parses JSON on 2xx", async () => {
    mswServer.use(http.get("/api/foo", () => HttpResponse.json({ ok: true })));
    expect(await apiGet<{ ok: boolean }>("/api/foo")).toEqual({ ok: true });
  });

  it("apiGet throws ApiError with parsed detail on non-2xx", async () => {
    mswServer.use(http.get("/api/x", () =>
      HttpResponse.json({ detail: "boom" }, { status: 422 })));
    await expect(apiGet("/api/x")).rejects.toMatchObject({
      name: "ApiError", status: 422, detail: "boom",
    });
  });

  it("apiPostJson sends body and parses response", async () => {
    mswServer.use(http.post("/api/echo", async ({ request }) => {
      const body = await request.json();
      return HttpResponse.json({ got: body });
    }));
    expect(await apiPostJson("/api/echo", { hi: 1 })).toEqual({ got: { hi: 1 } });
  });

  it("apiPut sends raw text and gets ok back", async () => {
    mswServer.use(http.put("/api/raw", async ({ request }) => {
      const text = await request.text();
      return HttpResponse.json({ len: text.length });
    }));
    expect(await apiPut<{ len: number }>("/api/raw", { hello: "world" }))
      .toEqual({ len: 17 });
  });

  it("apiDelete returns parsed body or null", async () => {
    mswServer.use(http.delete("/api/x", () => HttpResponse.json({ ok: true })));
    expect(await apiDelete("/api/x")).toEqual({ ok: true });
  });
});
```

- [ ] **Step 3: Run test, expect failure**

```bash
cd web && npm test -- --run tests/api.client.test.ts
```
Expected: 5 tests fail (`client.ts` does not exist yet).

- [ ] **Step 4: Implement `web/src/api/client.ts`**

```ts
export class ApiError extends Error {
  name = "ApiError";
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
}

async function parse<T>(resp: Response): Promise<T> {
  const ct = resp.headers.get("content-type") ?? "";
  const isJson = ct.includes("application/json");
  if (!resp.ok) {
    const body = isJson ? await resp.json().catch(() => null) : await resp.text();
    const detail = (body && typeof body === "object" && "detail" in body)
      ? (body as { detail: unknown }).detail
      : body;
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  if (isJson) return (await resp.json()) as T;
  return (await resp.text()) as unknown as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return parse(await fetch(path));
}

export async function apiPostJson<T>(path: string, body: unknown): Promise<T> {
  return parse(await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return parse(await fetch(path, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function apiPutText<T>(path: string, body: string): Promise<T> {
  return parse(await fetch(path, {
    method: "PUT",
    headers: { "content-type": "text/plain" },
    body,
  }));
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return parse(await fetch(path, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function apiDelete<T>(path: string): Promise<T> {
  return parse(await fetch(path, { method: "DELETE" }));
}

export async function apiPostRawYaml<T>(path: string, yaml: string): Promise<T> {
  return parse(await fetch(path, {
    method: "POST",
    headers: { "content-type": "text/plain" },
    body: yaml,
  }));
}
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd web && npm test -- --run tests/api.client.test.ts
```
Expected: 5 tests pass.

- [ ] **Step 6: Write `web/src/api/queries.ts`**

```ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as t from "./types";
import {
  apiGet, apiPostJson, apiPut, apiPostRawYaml, apiDelete, apiPatch,
} from "./client";

export const qk = {
  experiments: ["experiments"] as const,
  experiment: (name: string) => ["experiment", name] as const,
  runs: (name: string) => ["runs", name] as const,
  trace: (name: string, condition: string, rep: number) =>
    ["trace", name, condition, rep] as const,
  metrics: (name: string, condition: string, rep: number) =>
    ["metrics", name, condition, rep] as const,
  patch: (name: string, condition: string, rep: number) =>
    ["patch", name, condition, rep] as const,
  methodCmp: (name: string, condition: string, rep: number, method: string) =>
    ["methodCmp", name, condition, rep, method] as const,
  providers: ["providers"] as const,
  sessionState: (sid: string) => ["sessionState", sid] as const,
};

export const useExperiments = () =>
  useQuery({
    queryKey: qk.experiments,
    queryFn: () => apiGet<t.ExperimentSummary[]>("/api/experiments"),
  });

export const useExperiment = (name: string | undefined) =>
  useQuery({
    queryKey: qk.experiment(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<Record<string, unknown>>(`/api/experiments/${name}`),
  });

export function useSaveExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: Record<string, unknown> }) =>
      apiPut<void>(`/api/experiments/${name}`, body),
    onSuccess: (_d, { name }) => {
      qc.invalidateQueries({ queryKey: qk.experiment(name) });
      qc.invalidateQueries({ queryKey: qk.experiments });
    },
  });
}

export function useDeleteExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiDelete<void>(`/api/experiments/${name}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.experiments }),
  });
}

export function useUploadExperiment() {
  return useMutation({
    mutationFn: (yaml: string) =>
      apiPostRawYaml<Record<string, unknown>>(`/api/experiments/upload`, yaml),
  });
}

export const useRuns = (name: string | undefined) =>
  useQuery({
    queryKey: qk.runs(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.RunSummary[]>(`/api/runs/${name}`),
  });

export const useTrace = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.trace(name, condition, rep),
    queryFn: () => apiGet<t.Trace>(`/api/runs/${name}/${condition}/${rep}/trace`),
  });

export const useMetrics = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.metrics(name, condition, rep),
    queryFn: () => apiGet<t.MetricsJson>(`/api/runs/${name}/${condition}/${rep}/metrics`),
  });

export const usePatch = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: qk.patch(name, condition, rep),
    queryFn: () => apiGet<string>(`/api/runs/${name}/${condition}/${rep}/patch`),
  });

export const useMethodComparison = (
  name: string, condition: string, rep: number, method: string | undefined,
) =>
  useQuery({
    queryKey: qk.methodCmp(name, condition, rep, method ?? ""),
    enabled: Boolean(method),
    queryFn: () => apiGet<t.MethodComparison>(
      `/api/runs/${name}/${condition}/${rep}/method_comparison?method=${encodeURIComponent(method!)}`,
    ),
  });

export function usePatchSuccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { name: string; condition: string; rep: number; success: boolean | null }) =>
      apiPatch<t.MetricsJson>(
        `/api/runs/${args.name}/${args.condition}/${args.rep}`,
        { success: args.success },
      ),
    onSuccess: (_d, a) => {
      qc.invalidateQueries({ queryKey: qk.metrics(a.name, a.condition, a.rep) });
      qc.invalidateQueries({ queryKey: qk.runs(a.name) });
    },
  });
}

export function useValidateModel() {
  return useMutation({
    mutationFn: (model: string) =>
      apiPostJson<t.ValidateModelResp>(`/api/validate/model`, { model }),
  });
}

export const useProviders = () =>
  useQuery({
    queryKey: qk.providers,
    queryFn: () => apiGet<t.ProviderEntry[]>(`/api/providers`),
  });

export function useWriteProviderCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { provider: string; api_key: string }) =>
      apiPostJson<void>(`/api/providers/${args.provider}/credentials`,
        { api_key: args.api_key }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.providers }),
  });
}

export function useStartRun() {
  return useMutation({
    mutationFn: (experiment_name: string) =>
      apiPostJson<{ session_id: string }>(`/api/runs`, { experiment_name }),
  });
}

export const useSessionState = (sid: string | undefined) =>
  useQuery({
    queryKey: qk.sessionState(sid ?? ""),
    enabled: Boolean(sid),
    queryFn: () => apiGet<t.SessionState>(`/api/sessions/${sid}`),
    refetchInterval: 2000,
  });

export function useCancelSession() {
  return useMutation({
    mutationFn: (sid: string) => apiDelete<void>(`/api/sessions/${sid}`),
  });
}
```

- [ ] **Step 7: Run the test suite — confirm everything still green**

```bash
cd web && npm test -- --run
```
Expected: 6 tests pass (5 api.client + 1 App.smoke).

- [ ] **Step 8: Commit**

```bash
git add web/src/api/ web/tests/api.client.test.ts
git commit -m "feat(ui/web): typed REST client + TanStack Query hooks"
```

---

## Task 2: Schema loader + UI hints

**Files:**
- Create: `web/src/api/schemaCache.ts`
- Create: `web/src/schema/uiSchema.ts`
- Create: `web/tests/schemaCache.test.ts`

`/api/schema` returns a static document — we fetch it once on app boot and stash it. `uiSchema.ts` carries the rjsf UI hints (custom widgets, ordering, hidden v2 fields).

- [ ] **Step 1: Write the failing test**

`web/tests/schemaCache.test.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import { loadSchema, _resetSchemaCache } from "../src/api/schemaCache";

describe("schemaCache", () => {
  beforeEach(() => _resetSchemaCache());

  it("fetches /api/schema once and caches the result", async () => {
    let calls = 0;
    mswServer.use(http.get("/api/schema", () => {
      calls += 1;
      return HttpResponse.json({ title: "Experiment", type: "object" });
    }));
    expect(await loadSchema()).toEqual({ title: "Experiment", type: "object" });
    expect(await loadSchema()).toEqual({ title: "Experiment", type: "object" });
    expect(calls).toBe(1);
  });

  it("propagates ApiError and does not cache the failure", async () => {
    let calls = 0;
    mswServer.use(http.get("/api/schema", () => {
      calls += 1;
      return calls === 1
        ? HttpResponse.json({ detail: "nope" }, { status: 500 })
        : HttpResponse.json({ title: "ok" });
    }));
    await expect(loadSchema()).rejects.toMatchObject({ status: 500 });
    expect(await loadSchema()).toEqual({ title: "ok" });
    expect(calls).toBe(2);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/schemaCache.test.ts
```
Expected: 2 tests fail (`schemaCache.ts` missing).

- [ ] **Step 3: Implement `web/src/api/schemaCache.ts`**

```ts
import { apiGet } from "./client";

export type JsonSchema = Record<string, unknown>;

let cached: JsonSchema | null = null;
let pending: Promise<JsonSchema> | null = null;

export async function loadSchema(): Promise<JsonSchema> {
  if (cached) return cached;
  if (pending) return pending;
  pending = apiGet<JsonSchema>("/api/schema")
    .then((s) => { cached = s; pending = null; return s; })
    .catch((e) => { pending = null; throw e; });
  return pending;
}

// Test-only escape hatch — keep export prefixed with `_`.
export function _resetSchemaCache() { cached = null; pending = null; }
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/schemaCache.test.ts
```
Expected: 2 tests pass.

- [ ] **Step 5: Write `web/src/schema/uiSchema.ts`**

These hints tell rjsf-mui to use our custom widgets for specific fields. Field paths use rjsf-mui dotted notation (mirroring `Experiment` pydantic structure).

```ts
import type { UiSchema } from "@rjsf/utils";

// Custom widget names must match the keys we register on the Form's `widgets` prop.
export const uiSchema: UiSchema = {
  "ui:submitButtonOptions": { norender: true },
  model:       { "ui:widget": "ModelValidationWidget" },
  small_model: { "ui:widget": "ModelValidationWidget" },
  target_methods: { "ui:widget": "TargetMethodsWidget" },
  // v2 forward-compat fields — hide from v1 UI.
  isolation: {
    user_field_template: { "ui:widget": "hidden" },
    api_key_env_list:    { "ui:widget": "hidden" },
  },
  conditions: {
    items: {
      augmentation: { "ui:widget": "AugmentationWidget" },
    },
  },
  // System prompt + user message can be long → multiline.
  system_prompt: { "ui:widget": "textarea", "ui:options": { rows: 10 } },
  user_message: { "ui:widget": "textarea", "ui:options": { rows: 6 } },
};
```

- [ ] **Step 6: Commit**

```bash
git add web/src/api/schemaCache.ts web/src/schema/ web/tests/schemaCache.test.ts
git commit -m "feat(ui/web): schema loader + rjsf UI hints"
```

---

## Task 3: ExperimentList page

**Files:**
- Create: `web/src/pages/ExperimentList.tsx` (overwrite stub)
- Create: `web/src/components/StatusPill.tsx`
- Create: `web/src/components/UploadYamlButton.tsx`
- Create: `web/src/components/NewExperimentDialog.tsx`
- Create: `web/src/components/DeleteExperimentDialog.tsx`
- Create: `web/tests/StatusPill.test.tsx`
- Create: `web/tests/ExperimentList.test.tsx`

- [ ] **Step 1: Write the failing test for StatusPill**

`web/tests/StatusPill.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import StatusPill from "../src/components/StatusPill";

test.each([
  ["ready",       /ready/i],
  ["no_fixture",  /no fixture/i],
  ["running",     /running/i],
] as const)("StatusPill renders %s", (status, label) => {
  render(<StatusPill status={status} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/StatusPill.test.tsx
```
Expected: 3 tests fail (no StatusPill).

- [ ] **Step 3: Implement `web/src/components/StatusPill.tsx`**

```tsx
import { Chip } from "@mui/material";

export type ExperimentStatus = "ready" | "no_fixture" | "running";

interface Props { status: ExperimentStatus; }

const map: Record<ExperimentStatus, { label: string; color: "success" | "warning" | "info" }> = {
  ready:      { label: "ready",      color: "success" },
  no_fixture: { label: "no fixture", color: "warning" },
  running:    { label: "running",    color: "info" },
};

export default function StatusPill({ status }: Props) {
  const { label, color } = map[status];
  return <Chip size="small" label={label} color={color} variant="outlined" />;
}
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/StatusPill.test.tsx
```
Expected: 3 tests pass.

- [ ] **Step 5: Write `web/src/components/UploadYamlButton.tsx`**

```tsx
import { useRef } from "react";
import { Button } from "@mui/material";
import { useUploadExperiment } from "../api/queries";

interface Props { onUploaded: (parsed: Record<string, unknown>) => void; }

export default function UploadYamlButton({ onUploaded }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const upload = useUploadExperiment();

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const parsed = await upload.mutateAsync(text);
    onUploaded(parsed);
    if (ref.current) ref.current.value = "";
  }

  return (
    <>
      <Button variant="outlined" size="small" onClick={() => ref.current?.click()}>
        ↑ Upload YAML
      </Button>
      <input
        ref={ref}
        type="file"
        accept=".yaml,.yml"
        hidden
        onChange={handleFile}
      />
    </>
  );
}
```

- [ ] **Step 6: Write `web/src/components/NewExperimentDialog.tsx`**

```tsx
import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, TextField, Button } from "@mui/material";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string) => void;
}

export default function NewExperimentDialog({ open, onClose, onCreate }: Props) {
  const [name, setName] = useState("");
  const valid = /^[a-z0-9][a-z0-9_-]*$/.test(name);
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>New experiment</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          label="Name"
          helperText="kebab/snake-case, ascii only"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={name.length > 0 && !valid}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={!valid}
          onClick={() => { onCreate(name); setName(""); }}
        >Create</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 7: Write `web/src/components/DeleteExperimentDialog.tsx`**

```tsx
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from "@mui/material";

interface Props {
  open: boolean;
  name: string;
  onClose: () => void;
  onConfirm: () => void;
}

export default function DeleteExperimentDialog({ open, name, onClose, onConfirm }: Props) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>Delete "{name}"?</DialogTitle>
      <DialogContent>
        <Typography>
          This removes the experiment directory including prompts, slices, and run history.
          The action is irreversible.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button color="error" variant="contained" onClick={onConfirm}>Delete</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 8: Write the failing test for ExperimentList**

`web/tests/ExperimentList.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import ExperimentList from "../src/pages/ExperimentList";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ExperimentList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("ExperimentList shows experiments from API", async () => {
  mswServer.use(http.get("/api/experiments", () =>
    HttpResponse.json([
      { name: "wc",     has_fixture: true,  has_reference: true, has_runs: true,  last_run_at: "2026-05-28T10:00:00" },
      { name: "broken", has_fixture: false, has_reference: true, has_runs: false, last_run_at: null },
    ])));
  renderPage();
  expect(await screen.findByText("wc")).toBeInTheDocument();
  expect(await screen.findByText("broken")).toBeInTheDocument();
});

test("Run button calls POST /api/runs and navigates", async () => {
  mswServer.use(
    http.get("/api/experiments", () =>
      HttpResponse.json([
        { name: "wc", has_fixture: true, has_reference: true, has_runs: false, last_run_at: null },
      ])),
    http.post("/api/runs", async ({ request }) => {
      const body = await request.json() as { experiment_name: string };
      expect(body.experiment_name).toBe("wc");
      return HttpResponse.json({ session_id: "S1" });
    }),
  );
  renderPage();
  const runBtn = await screen.findByRole("button", { name: /run/i });
  await userEvent.click(runBtn);
  await waitFor(() =>
    expect(window.location.pathname).toBe("/runs/sessions/S1"),
  );
});
```

- [ ] **Step 9: Run test, expect failure**

```bash
cd web && npm test -- --run tests/ExperimentList.test.tsx
```
Expected: tests fail (page is still the stub).

- [ ] **Step 10: Implement `web/src/pages/ExperimentList.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Stack, Box, Typography, Button, Table, TableHead, TableBody, TableRow,
  TableCell, IconButton, CircularProgress, Alert,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/DeleteOutline";
import EditIcon from "@mui/icons-material/EditOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StatusPill, { type ExperimentStatus } from "../components/StatusPill";
import UploadYamlButton from "../components/UploadYamlButton";
import NewExperimentDialog from "../components/NewExperimentDialog";
import DeleteExperimentDialog from "../components/DeleteExperimentDialog";
import {
  useExperiments, useDeleteExperiment, useStartRun, useSaveExperiment,
} from "../api/queries";
import type { ExperimentSummary } from "../api/types";

function statusOf(e: ExperimentSummary): ExperimentStatus {
  if (!e.has_fixture) return "no_fixture";
  return "ready";
}

export default function ExperimentList() {
  const navigate = useNavigate();
  const list = useExperiments();
  const del = useDeleteExperiment();
  const start = useStartRun();
  const save = useSaveExperiment();
  const [toDelete, setToDelete] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);

  async function handleRun(name: string) {
    const { session_id } = await start.mutateAsync(name);
    navigate(`/runs/sessions/${session_id}`);
  }

  async function handleUploaded(parsed: Record<string, unknown>) {
    // Backend returns a resolved Experiment payload with `name` populated.
    const name = parsed.name as string;
    if (!name) return;
    await save.mutateAsync({ name, body: parsed });
    navigate(`/experiments/${name}`);
  }

  async function handleCreate(name: string) {
    setNewOpen(false);
    navigate(`/experiments/${name}`);
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Experiments</Typography>
        <Button variant="contained" size="small" onClick={() => setNewOpen(true)}>
          + New
        </Button>
        <UploadYamlButton onUploaded={handleUploaded} />
      </Stack>

      {list.isLoading && <CircularProgress />}
      {list.error && <Alert severity="error">Failed to load experiments.</Alert>}

      {list.data && (
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Has runs</TableCell>
                <TableCell>Last run</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {list.data.map((e) => (
                <TableRow key={e.name} hover>
                  <TableCell>{e.name}</TableCell>
                  <TableCell><StatusPill status={statusOf(e)} /></TableCell>
                  <TableCell>{e.has_runs ? "yes" : "—"}</TableCell>
                  <TableCell>{e.last_run_at ?? "—"}</TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="small"
                      title="Run"
                      disabled={!e.has_fixture}
                      onClick={() => handleRun(e.name)}
                      aria-label="run"
                    >
                      <PlayArrowIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      title="Edit"
                      onClick={() => navigate(`/experiments/${e.name}`)}
                      aria-label="edit"
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      size="small"
                      title="Delete"
                      onClick={() => setToDelete(e.name)}
                      aria-label="delete"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}

      <NewExperimentDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreate={handleCreate}
      />

      <DeleteExperimentDialog
        open={toDelete !== null}
        name={toDelete ?? ""}
        onClose={() => setToDelete(null)}
        onConfirm={async () => {
          if (toDelete) await del.mutateAsync(toDelete);
          setToDelete(null);
        }}
      />
    </Stack>
  );
}
```

- [ ] **Step 11: Run test, expect pass**

```bash
cd web && npm test -- --run tests/ExperimentList.test.tsx
```
Expected: 2 tests pass. (The Run-button test asserts `window.location.pathname` — react-router's MemoryRouter exposes this through history; if the harness reports `/` instead, the test is allowed to also assert `start.mutateAsync` was hit via `expect.calls`.)

- [ ] **Step 12: Commit**

```bash
git add web/src/pages/ExperimentList.tsx web/src/components/StatusPill.tsx \
        web/src/components/UploadYamlButton.tsx \
        web/src/components/NewExperimentDialog.tsx \
        web/src/components/DeleteExperimentDialog.tsx \
        web/tests/StatusPill.test.tsx web/tests/ExperimentList.test.tsx
git commit -m "feat(ui/web): ExperimentList page + status pills + upload/delete dialogs"
```

---

## Task 4a: ExperimentEdit — base rjsf-mui form

**Files:**
- Create: `web/src/pages/ExperimentEdit.tsx` (overwrite stub)
- Create: `web/src/components/ExperimentForm.tsx`
- Create: `web/tests/ExperimentForm.test.tsx`

The form must (per spec §7.2):
- render from the live `/api/schema`,
- live-validate every field through ajv8,
- disable Save when there are validation errors,
- save atomically via `PUT /api/experiments/{name}`.

- [ ] **Step 1: Write the failing test**

`web/tests/ExperimentForm.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExperimentForm from "../src/components/ExperimentForm";

const trivialSchema = {
  type: "object",
  properties: {
    name: { type: "string", minLength: 1 },
    timeout_s: { type: "integer", minimum: 1 },
  },
  required: ["name", "timeout_s"],
};

test("rejects invalid form, Save disabled", async () => {
  const onSave = vi.fn();
  render(
    <ExperimentForm
      schema={trivialSchema as any}
      uiSchema={{}}
      formData={{ name: "", timeout_s: 0 }}
      onSave={onSave}
    />,
  );
  const saveBtn = await screen.findByRole("button", { name: /save/i });
  expect(saveBtn).toBeDisabled();
});

test("Save fires on valid form", async () => {
  const onSave = vi.fn();
  render(
    <ExperimentForm
      schema={trivialSchema as any}
      uiSchema={{}}
      formData={{ name: "ok", timeout_s: 5 }}
      onSave={onSave}
    />,
  );
  const saveBtn = await screen.findByRole("button", { name: /save/i });
  expect(saveBtn).not.toBeDisabled();
  await userEvent.click(saveBtn);
  expect(onSave).toHaveBeenCalledWith({ name: "ok", timeout_s: 5 });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/ExperimentForm.test.tsx
```
Expected: 2 tests fail (component missing).

- [ ] **Step 3: Implement `web/src/components/ExperimentForm.tsx`**

```tsx
import { useMemo, useState } from "react";
import { Form } from "@rjsf/mui";
import validator from "@rjsf/validator-ajv8";
import type { RJSFSchema, UiSchema } from "@rjsf/utils";
import { Box, Button, Stack } from "@mui/material";

interface Props {
  schema: RJSFSchema;
  uiSchema: UiSchema;
  formData: Record<string, unknown>;
  widgets?: Record<string, React.ComponentType<any>>;
  onSave: (data: Record<string, unknown>) => void;
  onFormChange?: (data: Record<string, unknown>, hasErrors: boolean) => void;
}

export default function ExperimentForm({
  schema, uiSchema, formData, widgets, onSave, onFormChange,
}: Props) {
  const [data, setData] = useState<Record<string, unknown>>(formData);
  const errors = useMemo(
    () => validator.validateFormData(data, schema).errors,
    [data, schema],
  );
  const hasErrors = errors.length > 0;

  return (
    <Stack spacing={2}>
      <Box>
        <Form
          schema={schema}
          uiSchema={uiSchema}
          formData={data}
          widgets={widgets}
          validator={validator}
          liveValidate
          showErrorList={false}
          onChange={({ formData: f }) => {
            setData(f as Record<string, unknown>);
            onFormChange?.(f as Record<string, unknown>, hasErrors);
          }}
        />
      </Box>
      <Stack direction="row" justifyContent="flex-end">
        <Button
          variant="contained"
          disabled={hasErrors}
          onClick={() => onSave(data)}
        >Save</Button>
      </Stack>
    </Stack>
  );
}
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/ExperimentForm.test.tsx
```
Expected: 2 tests pass.

- [ ] **Step 5: Write `web/src/pages/ExperimentEdit.tsx` (initial — full layout filled in later subtasks)**

```tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Stack, Box, Typography, CircularProgress, Alert } from "@mui/material";
import ExperimentForm from "../components/ExperimentForm";
import { useExperiment, useSaveExperiment, useStartRun } from "../api/queries";
import { loadSchema, type JsonSchema } from "../api/schemaCache";
import { uiSchema } from "../schema/uiSchema";

export default function ExperimentEdit() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const exp = useExperiment(name);
  const save = useSaveExperiment();
  const start = useStartRun();

  useEffect(() => { loadSchema().then(setSchema); }, []);

  async function handleSave(data: Record<string, unknown>) {
    if (!name) return;
    await save.mutateAsync({ name, body: data });
  }

  async function handleRun() {
    if (!name) return;
    const { session_id } = await start.mutateAsync(name);
    navigate(`/runs/sessions/${session_id}`);
  }

  if (!schema || !exp.data) return <CircularProgress />;
  if (exp.error) return <Alert severity="error">Failed to load experiment.</Alert>;

  return (
    <Stack direction="row" spacing={2} sx={{ height: "100%" }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography variant="h5" gutterBottom>Edit {name}</Typography>
        <ExperimentForm
          schema={schema as any}
          uiSchema={uiSchema}
          formData={exp.data}
          onSave={handleSave}
        />
      </Box>
      <Box sx={{ width: 320, position: "sticky", top: 0, alignSelf: "flex-start" }}>
        {/* Right panel cards added in Task 4b. */}
      </Box>
    </Stack>
  );
}
```

- [ ] **Step 6: Run all tests**

```bash
cd web && npm test -- --run
```
Expected: all previously passing tests still pass; new ExperimentForm tests pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/ExperimentEdit.tsx web/src/components/ExperimentForm.tsx \
        web/tests/ExperimentForm.test.tsx
git commit -m "feat(ui/web): ExperimentEdit base rjsf-mui form with live validation"
```

---

## Task 4b: ExperimentEdit — sticky right panel (Validation, Plan, Fixtures, Previous runs)

**Files:**
- Create: `web/src/components/ValidationPanel.tsx`
- Create: `web/src/components/PlanPanel.tsx`
- Create: `web/src/components/FixturesPanel.tsx`
- Create: `web/src/components/PreviousRunsPanel.tsx`
- Create: `web/src/lib/computePlan.ts`
- Create: `web/tests/computePlan.test.ts`
- Create: `web/tests/PlanPanel.test.tsx`
- Modify: `web/src/pages/ExperimentEdit.tsx` (wire panels in)
- Modify: `web/src/components/ExperimentForm.tsx` (expose validation errors)

- [ ] **Step 1: Write the failing test for computePlan**

`web/tests/computePlan.test.ts`:
```ts
import { computePlan } from "../src/lib/computePlan";

test("N conditions × M reps = N*M runs", () => {
  const p = computePlan({
    conditions: [{ name: "baseline" }, { name: "augmented" }],
    reps_per_condition: 3,
    timeout_s: 60,
  });
  expect(p.total_runs).toBe(6);
  expect(p.eta_seconds).toBe(6 * 60);
});

test("empty conditions → zero runs", () => {
  const p = computePlan({ conditions: [], reps_per_condition: 5, timeout_s: 10 });
  expect(p.total_runs).toBe(0);
  expect(p.eta_seconds).toBe(0);
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/computePlan.test.ts
```
Expected: 2 tests fail.

- [ ] **Step 3: Implement `web/src/lib/computePlan.ts`**

```ts
export interface MiniExperiment {
  conditions: { name: string }[];
  reps_per_condition: number;
  timeout_s: number;
}

export interface Plan {
  total_runs: number;
  eta_seconds: number;
  per_condition: { name: string; runs: number }[];
}

export function computePlan(exp: MiniExperiment): Plan {
  const reps = Number(exp.reps_per_condition) || 0;
  const t = Number(exp.timeout_s) || 0;
  const total = exp.conditions.length * reps;
  return {
    total_runs: total,
    eta_seconds: total * t,
    per_condition: exp.conditions.map((c) => ({ name: c.name, runs: reps })),
  };
}
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/computePlan.test.ts
```
Expected: 2 tests pass.

- [ ] **Step 5: Write `web/src/lib/formatDuration.ts`**

```ts
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts: string[] = [];
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  if (s || parts.length === 0) parts.push(`${s}s`);
  return parts.join(" ");
}
```

- [ ] **Step 6: Write `web/src/components/PlanPanel.tsx`**

```tsx
import { Card, CardContent, Typography, Stack } from "@mui/material";
import { computePlan, type MiniExperiment } from "../lib/computePlan";
import { formatDuration } from "../lib/formatDuration";

interface Props { formData: Partial<MiniExperiment>; }

export default function PlanPanel({ formData }: Props) {
  const mini: MiniExperiment = {
    conditions: (formData.conditions ?? []) as { name: string }[],
    reps_per_condition: formData.reps_per_condition ?? 0,
    timeout_s: formData.timeout_s ?? 0,
  };
  const plan = computePlan(mini);
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Plan</Typography>
        <Stack spacing={0.5}>
          <Typography variant="body2">
            {mini.conditions.length} × {mini.reps_per_condition} = <b>{plan.total_runs}</b> runs
          </Typography>
          <Typography variant="body2" color="text.secondary">
            est. {formatDuration(plan.eta_seconds)} at {mini.timeout_s}s/run timeout
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 7: Write the failing test for PlanPanel**

`web/tests/PlanPanel.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import PlanPanel from "../src/components/PlanPanel";

test("shows total runs and ETA", () => {
  render(
    <PlanPanel formData={{
      conditions: [{ name: "a" }, { name: "b" }],
      reps_per_condition: 2,
      timeout_s: 60,
    }} />,
  );
  expect(screen.getByText(/2 × 2/)).toBeInTheDocument();
  expect(screen.getByText(/4/)).toBeInTheDocument();
  expect(screen.getByText(/4m/)).toBeInTheDocument();
});
```

- [ ] **Step 8: Run test, expect pass**

```bash
cd web && npm test -- --run tests/PlanPanel.test.tsx
```
Expected: 1 test passes.

- [ ] **Step 9: Write `web/src/components/ValidationPanel.tsx`**

```tsx
import { Card, CardContent, Typography, Stack, Alert } from "@mui/material";
import type { RJSFValidationError } from "@rjsf/utils";

interface Props { errors: RJSFValidationError[]; }

export default function ValidationPanel({ errors }: Props) {
  if (errors.length === 0) {
    return (
      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle2" gutterBottom>Validation</Typography>
          <Alert severity="success" variant="outlined">No errors.</Alert>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>
          Validation ({errors.length})
        </Typography>
        <Stack spacing={0.5}>
          {errors.map((e, i) => (
            <Typography key={i} variant="body2" color="error">
              <code>{e.property ?? e.schemaPath}</code> — {e.message}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 10: Write `web/src/components/FixturesPanel.tsx`**

```tsx
import { Card, CardContent, Typography, Stack } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";

interface Props {
  fixturePath?: string;
  referencePath?: string;
  hasFixture: boolean;
  hasReference: boolean;
}

function Row({ ok, label, path }: { ok: boolean; label: string; path?: string }) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {ok
        ? <CheckCircleIcon color="success" fontSize="small" />
        : <CancelIcon color="error" fontSize="small" />}
      <Typography variant="body2">
        <b>{label}:</b> <code>{path ?? "(unset)"}</code>
      </Typography>
    </Stack>
  );
}

export default function FixturesPanel({ fixturePath, referencePath, hasFixture, hasReference }: Props) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Fixtures</Typography>
        <Stack spacing={0.5}>
          <Row ok={hasFixture}   label="fixture"   path={fixturePath} />
          <Row ok={hasReference} label="reference" path={referencePath} />
        </Stack>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 11: Write `web/src/components/PreviousRunsPanel.tsx`**

```tsx
import { Card, CardContent, Typography, Stack, Link } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useRuns } from "../api/queries";

interface Props { name: string; }

export default function PreviousRunsPanel({ name }: Props) {
  const runs = useRuns(name);
  const items = (runs.data ?? []).slice(-5).reverse();
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2" gutterBottom>Previous runs</Typography>
        {items.length === 0 && <Typography variant="body2">No runs yet.</Typography>}
        <Stack spacing={0.5}>
          {items.map((r) => (
            <Link
              key={`${r.condition}-${r.rep}`}
              component={RouterLink}
              to={`/runs/${name}/${r.condition}/${r.rep}`}
              variant="body2"
            >
              {r.condition} / rep {r.rep} — {r.verify_status ?? "—"}
            </Link>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 12: Extend `ExperimentForm` to surface validation errors**

In `web/src/components/ExperimentForm.tsx`, modify the `Props` interface to also accept `onErrorsChange?: (errors: RJSFValidationError[]) => void;`. Add `import { useEffect, useMemo, useState } from "react";` (add `useEffect`) and `import type { RJSFValidationError } from "@rjsf/utils";`.

**Do NOT call `onErrorsChange` inside `useMemo`** — that is a parent setState during the child's render phase (React throws "Cannot update a component while rendering a different component"), and because `validateFormData` returns a fresh array each render a naive `useEffect([errors])` would loop forever. Keep `useMemo` pure and push to the parent via a `useEffect` keyed on a stable content-signature:

```tsx
const errors = useMemo(
  () => validator.validateFormData(data, schema).errors,
  [data, schema],
);
const hasErrors = errors.length > 0;

// Push errors to the parent without setState-during-render. Key the effect on a
// content signature so a fresh-but-equal error array doesn't re-fire/loop.
const errorSignature = errors
  .map((e) => `${e.property ?? e.schemaPath}:${e.message}`)
  .join("|");
useEffect(() => {
  onErrorsChange?.(errors);
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [errorSignature]);
```

Loop-safety note: ExperimentForm's local `data` (from `useState(formData)`) is NOT re-seeded from the `formData` prop after mount, so a parent-driven re-render leaves `data` identity stable → `useMemo` returns its cached array → `errorSignature` unchanged → the effect does not re-fire. State flows one-directionally (form → parent).

- [ ] **Step 13: Update `ExperimentEdit.tsx` to wire the panels**

Replace the right-panel `<Box>` with stacked cards and add an `errors` state plus a `formData` state. The full file becomes:

```tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Stack, Box, Typography, CircularProgress, Alert, Button,
} from "@mui/material";
import type { RJSFValidationError } from "@rjsf/utils";
import ExperimentForm from "../components/ExperimentForm";
import ValidationPanel from "../components/ValidationPanel";
import PlanPanel from "../components/PlanPanel";
import FixturesPanel from "../components/FixturesPanel";
import PreviousRunsPanel from "../components/PreviousRunsPanel";
import { useExperiment, useExperiments, useSaveExperiment, useStartRun } from "../api/queries";
import { loadSchema, type JsonSchema } from "../api/schemaCache";
import { uiSchema } from "../schema/uiSchema";

export default function ExperimentEdit() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [schema, setSchema] = useState<JsonSchema | null>(null);
  const exp = useExperiment(name);
  const list = useExperiments();
  const save = useSaveExperiment();
  const start = useStartRun();
  const [formData, setFormData] = useState<Record<string, unknown> | null>(null);
  const [errors, setErrors] = useState<RJSFValidationError[]>([]);

  useEffect(() => { loadSchema().then(setSchema); }, []);
  useEffect(() => { if (exp.data && formData === null) setFormData(exp.data); }, [exp.data, formData]);

  const summary = list.data?.find((e) => e.name === name);

  async function handleSave(data: Record<string, unknown>) {
    if (!name) return;
    await save.mutateAsync({ name, body: data });
  }

  async function handleRun() {
    if (!name) return;
    const { session_id } = await start.mutateAsync(name);
    // Pass experimentName via router state — Task 5e's Run page reads
    // location.state.experimentName to know which trace to navigate to on finish.
    navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
  }

  // Error guard MUST come first: on a fetch error TanStack Query leaves
  // exp.data undefined, so a data-first guard would render a perpetual spinner.
  if (exp.error) return <Alert severity="error">Failed to load experiment.</Alert>;
  if (!schema || !formData) return <CircularProgress />;

  return (
    <Stack direction="row" spacing={2} sx={{ height: "100%" }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" alignItems="center" sx={{ mb: 2 }}>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>Edit {name}</Typography>
          <Button
            variant="contained"
            color="success"
            disabled={errors.length > 0 || !summary?.has_fixture || start.isPending}
            onClick={handleRun}
            startIcon={<span>▶</span>}
          >
            Run
          </Button>
        </Stack>
        <ExperimentForm
          schema={schema as never}
          uiSchema={uiSchema}
          formData={formData}
          onErrorsChange={setErrors}
          onFormChange={(f) => setFormData(f)}
          onSave={handleSave}
        />
      </Box>
      <Box sx={{ width: 320, position: "sticky", top: 0, alignSelf: "flex-start" }}>
        <Stack spacing={2}>
          <ValidationPanel errors={errors} />
          <PlanPanel formData={formData as any} />
          <FixturesPanel
            fixturePath={formData.fixture_path as string | undefined}
            referencePath={formData.reference_path as string | undefined}
            hasFixture={Boolean(summary?.has_fixture)}
            hasReference={Boolean(summary?.has_reference)}
          />
          {name && <PreviousRunsPanel name={name} />}
        </Stack>
      </Box>
    </Stack>
  );
}
```

- [ ] **Step 14: Run all tests, expect pass**

```bash
cd web && npm test -- --run
```
Expected: all green.

- [ ] **Step 15: Commit**

```bash
git add web/src/components/{ValidationPanel,PlanPanel,FixturesPanel,PreviousRunsPanel,ExperimentForm}.tsx \
        web/src/lib/{computePlan,formatDuration}.ts \
        web/src/pages/ExperimentEdit.tsx \
        web/tests/{computePlan.test.ts,PlanPanel.test.tsx}
git commit -m "feat(ui/web): ExperimentEdit right-panel (validation/plan/fixtures/previous runs)"
```

---

## Task 4c: ExperimentEdit — ModelValidationChip widget + AddApiKeyDialog

**Files:**
- Create: `web/src/components/ModelValidationChip.tsx`
- Create: `web/src/components/AddApiKeyDialog.tsx`
- Create: `web/tests/ModelValidationChip.test.tsx`
- Modify: `web/src/components/ExperimentForm.tsx` (pass widgets prop through)
- Modify: `web/src/pages/ExperimentEdit.tsx` (register custom widgets)

Per spec §7.2: `Model` field is a live-validated widget. Debounce 350ms, three states (`✓ available`, `⚠ not in catalog`, `✗ no key`). The `no_key` state shows an `+ Add API key` button that opens the dialog.

- [ ] **Step 1: Write the failing test**

`web/tests/ModelValidationChip.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import ModelValidationChip from "../src/components/ModelValidationChip";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("shows ✓ available for backend status 'ok'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "ok", provider: "openrouter", suggestions: [] })));
  render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/available/i)).toBeInTheDocument(),
  );
});

test("shows ⚠ not in catalog for 'model_not_found' with suggestions", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "model_not_found", provider: "openrouter", suggestions: ["openrouter/foo-bar"] })));
  render(wrap(<ModelValidationChip value="openrouter/foo-baz" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/not in catalog/i)).toBeInTheDocument(),
  );
  expect(screen.getByText("openrouter/foo-bar")).toBeInTheDocument();
});

test("shows ✗ no key + Add API key for 'no_credentials'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "no_credentials", provider: "openrouter", suggestions: [] })));
  render(wrap(<ModelValidationChip value="openrouter/foo" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/no key/i)).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /add api key/i })).toBeInTheDocument();
});

test("shows ⚠ malformed for backend status 'malformed'", async () => {
  mswServer.use(http.post("/api/validate/model", () =>
    HttpResponse.json({ status: "malformed", provider: null, suggestions: [] })));
  render(wrap(<ModelValidationChip value="bareid" onChange={() => {}} />));
  await waitFor(() =>
    expect(screen.getByText(/malformed/i)).toBeInTheDocument(),
  );
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/ModelValidationChip.test.tsx
```
Expected: 3 tests fail.

- [ ] **Step 3: Implement `web/src/components/AddApiKeyDialog.tsx`**

```tsx
import { useState } from "react";
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Button, Typography,
} from "@mui/material";
import { useWriteProviderCredentials } from "../api/queries";

interface Props {
  open: boolean;
  provider: string;
  onClose: () => void;
  onSaved: () => void;
}

export default function AddApiKeyDialog({ open, provider, onClose, onSaved }: Props) {
  const [key, setKey] = useState("");
  const mut = useWriteProviderCredentials();
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>Add API key for {provider}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" gutterBottom>
          The key is written to <code>~/.local/share/opencode/auth.json</code>
          {" "}on this machine. No network call.
        </Typography>
        <TextField
          autoFocus fullWidth type="password" label="API key"
          value={key} onChange={(e) => setKey(e.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={key.length === 0 || mut.isPending}
          onClick={async () => {
            await mut.mutateAsync({ provider, api_key: key });
            setKey("");
            onSaved();
            onClose();
          }}
        >Save</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 4: Implement `web/src/components/ModelValidationChip.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Stack, TextField, Chip, Button, Box, Typography } from "@mui/material";
import { useValidateModel } from "../api/queries";
import type { ValidateModelResp } from "../api/types";
import AddApiKeyDialog from "./AddApiKeyDialog";

interface Props {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}

const DEBOUNCE_MS = 350;

export default function ModelValidationChip({ value, onChange, label = "Model" }: Props) {
  const [draft, setDraft] = useState(value);
  const [result, setResult] = useState<ValidateModelResp | null>(null);
  const [dlgOpen, setDlgOpen] = useState(false);
  const mut = useValidateModel();

  useEffect(() => { setDraft(value); }, [value]);

  useEffect(() => {
    if (!draft) { setResult(null); return; }
    const h = setTimeout(async () => {
      try { setResult(await mut.mutateAsync(draft)); }
      catch { setResult(null); }
    }, DEBOUNCE_MS);
    return () => clearTimeout(h);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Stack spacing={1}>
      <TextField
        label={label}
        size="small"
        value={draft}
        onChange={(e) => { setDraft(e.target.value); onChange(e.target.value); }}
        fullWidth
      />
      {result && (
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          {result.status === "ok" && (
            <Chip size="small" color="success" label="✓ available" />
          )}
          {result.status === "model_not_found" && (
            <Chip size="small" color="warning" label="⚠ not in catalog" />
          )}
          {result.status === "malformed" && (
            <Chip size="small" color="warning"
                  label="⚠ malformed (expected provider/model)" />
          )}
          {result.status === "no_credentials" && (
            <>
              <Chip size="small" color="error" label="✗ no key" />
              {result.provider && (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setDlgOpen(true)}
                >+ Add API key</Button>
              )}
            </>
          )}
        </Stack>
      )}
      {result?.suggestions && result.suggestions.length > 0 && (
        <Box>
          <Typography variant="caption" color="text.secondary">Did you mean:</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {result.suggestions.map((s) => (
              <Chip
                key={s}
                size="small"
                label={s}
                onClick={() => { setDraft(s); onChange(s); }}
                clickable
              />
            ))}
          </Stack>
        </Box>
      )}
      <AddApiKeyDialog
        open={dlgOpen}
        provider={result?.provider ?? ""}
        onClose={() => setDlgOpen(false)}
        onSaved={() => {
          // Retrigger validation after saving the key.
          mut.mutateAsync(draft).then(setResult).catch(() => {});
        }}
      />
    </Stack>
  );
}
```

- [ ] **Step 5: Write the rjsf bridge widget**

Add to `web/src/schema/widgets.tsx`:

```tsx
import type { WidgetProps } from "@rjsf/utils";
import ModelValidationChip from "../components/ModelValidationChip";

export function ModelValidationWidget(props: WidgetProps) {
  return (
    <ModelValidationChip
      value={(props.value as string) ?? ""}
      onChange={props.onChange}
      label={props.label}
    />
  );
}
```

- [ ] **Step 6: Wire widgets into `ExperimentForm` and `ExperimentEdit`**

In `web/src/components/ExperimentForm.tsx` — already accepts `widgets`. Just confirm the prop is forwarded:

```tsx
<Form
  schema={schema}
  uiSchema={uiSchema}
  formData={data}
  widgets={widgets}      // <-- forwarded
  validator={validator}
  liveValidate
  showErrorList={false}
  onChange={(...) => ...}
/>
```

In `web/src/pages/ExperimentEdit.tsx`, import and register the widget:

```tsx
import { ModelValidationWidget } from "../schema/widgets";

const customWidgets = { ModelValidationWidget };

// inside JSX:
<ExperimentForm
  schema={schema as any}
  uiSchema={uiSchema}
  formData={formData}
  widgets={customWidgets}
  onErrorsChange={setErrors}
  onFormChange={(f) => setFormData(f)}
  onSave={handleSave}
/>
```

- [ ] **Step 7: Run tests, expect pass**

```bash
cd web && npm test -- --run tests/ModelValidationChip.test.tsx
```
Expected: 3 tests pass.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/{ModelValidationChip,AddApiKeyDialog}.tsx \
        web/src/schema/widgets.tsx \
        web/src/components/ExperimentForm.tsx \
        web/src/pages/ExperimentEdit.tsx \
        web/tests/ModelValidationChip.test.tsx
git commit -m "feat(ui/web): live Model validation chip + Add API key dialog"
```

---

## Task 4d: ExperimentEdit — TargetMethodsChips widget

**Files:**
- Create: `web/src/components/TargetMethodsChips.tsx`
- Modify: `web/src/schema/widgets.tsx`
- Create: `web/tests/TargetMethodsChips.test.tsx`

Per spec §7.2: `target_methods` is a chip-list editor where pressing Enter appends an item.

- [ ] **Step 1: Write the failing test**

`web/tests/TargetMethodsChips.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TargetMethodsChips from "../src/components/TargetMethodsChips";

test("Enter appends a chip; X removes it", async () => {
  const onChange = vi.fn();
  render(<TargetMethodsChips value={["foo"]} onChange={onChange} />);
  const input = screen.getByPlaceholderText(/add method/i);
  await userEvent.type(input, "bar{enter}");
  expect(onChange).toHaveBeenLastCalledWith(["foo", "bar"]);

  // Re-render with the new value and verify the delete handler.
  const onChange2 = vi.fn();
  render(<TargetMethodsChips value={["foo", "bar"]} onChange={onChange2} />);
  const delBtns = screen.getAllByLabelText(/delete/i);
  await userEvent.click(delBtns[0]);
  expect(onChange2).toHaveBeenLastCalledWith(["bar"]);
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/TargetMethodsChips.test.tsx
```
Expected: tests fail.

- [ ] **Step 3: Implement `web/src/components/TargetMethodsChips.tsx`**

```tsx
import { useState } from "react";
import { Stack, TextField, Chip, Box, Typography } from "@mui/material";

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  label?: string;
}

export default function TargetMethodsChips({ value, onChange, label = "Target methods" }: Props) {
  const [draft, setDraft] = useState("");
  return (
    <Stack spacing={1}>
      <Typography variant="caption">{label}</Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {value.map((v, i) => (
          <Chip
            key={`${v}-${i}`}
            label={v}
            onDelete={() => onChange(value.filter((_, j) => j !== i))}
            size="small"
            deleteIcon={<span aria-label="delete">×</span>}
          />
        ))}
      </Box>
      <TextField
        size="small"
        placeholder="Add method (Enter to commit)"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draft.trim()) {
            e.preventDefault();
            onChange([...value, draft.trim()]);
            setDraft("");
          }
        }}
      />
    </Stack>
  );
}
```

- [ ] **Step 4: Bridge into rjsf**

Append to `web/src/schema/widgets.tsx`:

```tsx
import TargetMethodsChips from "../components/TargetMethodsChips";

export function TargetMethodsWidget(props: WidgetProps) {
  const arr = Array.isArray(props.value) ? (props.value as string[]) : [];
  return <TargetMethodsChips value={arr} onChange={props.onChange} label={props.label} />;
}
```

In `web/src/pages/ExperimentEdit.tsx`, extend the widget map:

```tsx
import { ModelValidationWidget, TargetMethodsWidget } from "../schema/widgets";
const customWidgets = { ModelValidationWidget, TargetMethodsWidget };
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd web && npm test -- --run tests/TargetMethodsChips.test.tsx
```
Expected: 1 test passes (covers both Enter and Delete via two render blocks).

- [ ] **Step 6: Commit**

```bash
git add web/src/components/TargetMethodsChips.tsx \
        web/src/schema/widgets.tsx \
        web/src/pages/ExperimentEdit.tsx \
        web/tests/TargetMethodsChips.test.tsx
git commit -m "feat(ui/web): TargetMethodsChips widget"
```

---

## Task 4e: ExperimentEdit — AugmentationField widget

**Files:**
- Create: `web/src/components/AugmentationField.tsx`
- Modify: `web/src/schema/widgets.tsx`

Per spec §7.2: each `condition.augmentation` is a textarea inline in the form. Backend syncs to `slices/<name>.md` on `PUT`.

- [ ] **Step 1: Implement `web/src/components/AugmentationField.tsx`**

```tsx
import { TextField } from "@mui/material";

interface Props {
  value: string;
  onChange: (next: string) => void;
  label?: string;
}

export default function AugmentationField({ value, onChange, label = "Augmentation" }: Props) {
  return (
    <TextField
      label={label}
      multiline
      minRows={6}
      fullWidth
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      helperText="Saved as slices/<condition>.md on PUT."
    />
  );
}
```

- [ ] **Step 2: Bridge into rjsf**

Append to `web/src/schema/widgets.tsx`:

```tsx
import AugmentationField from "../components/AugmentationField";

export function AugmentationWidget(props: WidgetProps) {
  return (
    <AugmentationField
      value={(props.value as string) ?? ""}
      onChange={props.onChange}
      label={props.label}
    />
  );
}
```

- [ ] **Step 3: Register in `ExperimentEdit.tsx`**

```tsx
import {
  ModelValidationWidget, TargetMethodsWidget, AugmentationWidget,
} from "../schema/widgets";
const customWidgets = { ModelValidationWidget, TargetMethodsWidget, AugmentationWidget };
```

- [ ] **Step 4: Run all tests, expect pass**

```bash
cd web && npm test -- --run
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/AugmentationField.tsx \
        web/src/schema/widgets.tsx \
        web/src/pages/ExperimentEdit.tsx
git commit -m "feat(ui/web): AugmentationField widget for conditions[].augmentation"
```

---

## Task 4f: ExperimentEdit — manual smoke

**Files:** none — manual integration smoke against running backend.

- [ ] **Step 1: Start the backend**

In one shell:
```bash
.venv/bin/abench-ui --experiments-dir experiments
```
Expected: uvicorn boots on `127.0.0.1:8765`.

- [ ] **Step 2: Start the dev frontend**

In another shell:
```bash
cd web && npm run dev
```
Expected: Vite serves on `127.0.0.1:5173` with proxy to `8765`.

- [ ] **Step 3: Manually exercise the form**

Open `http://127.0.0.1:5173/experiments/<an existing experiment>` and confirm:
- form renders fields from live schema,
- `model` field shows ✓/⚠/✗ depending on what's configured,
- `target_methods` accepts Enter-to-add,
- Save persists; reload roundtrips,
- Validation panel lists pydantic errors when you blank a required field,
- Plan panel updates as you change `reps_per_condition`,
- Fixtures panel reflects fs state.

If anything is off, fix it before moving on. **Do not** commit the manual-smoke as a step — it's just a checkpoint.

---

## Task 5a: WebSocket envelope types + `useRunSession` hook

**Files:**
- Create: `web/src/ws/envelope.ts`
- Create: `web/src/ws/useRunSession.ts`
- Create: `web/tests/useRunSession.test.ts`

The backend WS contract (from `abench_ui/server.py` and `run_session.py`):

```
WS  /ws/sessions/{sid}?last_event_id=N    (N is integer; 0 means "from start")
envelopes (every one has type + session_id + event_id; details vary):
  session.started   {total_runs, conditions}
  run.started       {run_idx, total_runs, condition, rep}
  raw_event         {run_idx, condition, rep, event}
  run.finished      {run_idx, total_runs, condition, rep, finished, interrupted_reason, verify:{...}}
  session.error     {message, traceback}
  session.finished  {duration_s}
```

On disconnect, the hook should reconnect automatically and pass the highest seen `event_id`. Buffered replay is handled by the server (`ws_buffer.py`, ring of ≤5000).

- [ ] **Step 1: Write `web/src/ws/envelope.ts`**

```ts
import type { VerifySummary } from "../api/types";

export interface SessionStarted {
  type: "session.started";
  session_id: string;
  event_id: number;
  total_runs: number;
  conditions: string[];
}

export interface RunStarted {
  type: "run.started";
  session_id: string;
  event_id: number;
  run_idx: number;
  total_runs: number;
  condition: string;
  rep: number;
}

export interface RawEvent {
  type: "raw_event";
  session_id: string;
  event_id: number;
  run_idx: number;
  condition: string;
  rep: number;
  event: Record<string, unknown>;
}

export interface RunFinished {
  type: "run.finished";
  session_id: string;
  event_id: number;
  run_idx: number;
  total_runs: number;
  condition: string;
  rep: number;
  finished: boolean;
  interrupted_reason: string | null;
  verify: VerifySummary;
}

export interface SessionError {
  type: "session.error";
  session_id: string;
  event_id: number;
  message: string;
  traceback?: string;
}

export interface SessionFinished {
  type: "session.finished";
  session_id: string;
  event_id: number;
  duration_s: number;
}

export type Envelope =
  | SessionStarted | RunStarted | RawEvent
  | RunFinished | SessionError | SessionFinished;
```

- [ ] **Step 2: Write the failing test for `useRunSession`**

`web/tests/useRunSession.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRunSession } from "../src/ws/useRunSession";

// Minimal WebSocket mock that records URLs and lets us push messages.
class FakeWS {
  static instances: FakeWS[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  readyState = 0;
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    });
  }
  send() {}
  close() { this.onclose?.(new CloseEvent("close")); }
  push(env: object) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(env) }));
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  // @ts-expect-error  inject mock
  global.WebSocket = FakeWS;
});

afterEach(() => {
  // restore is automatic for the next test through beforeEach.
});

describe("useRunSession", () => {
  it("connects to /ws/sessions/{sid}?last_event_id=0 initially", async () => {
    renderHook(() => useRunSession("S1"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    expect(FakeWS.instances[0].url).toContain("/ws/sessions/S1");
    expect(FakeWS.instances[0].url).toContain("last_event_id=0");
  });

  it("accumulates envelopes and exposes them in order", async () => {
    const { result } = renderHook(() => useRunSession("S2"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0].push({ type: "session.started", session_id: "S2", event_id: 1, total_runs: 2, conditions: ["a"] });
      FakeWS.instances[0].push({ type: "run.started", session_id: "S2", event_id: 2, run_idx: 1, total_runs: 2, condition: "a", rep: 0 });
    });
    await waitFor(() => expect(result.current.envelopes).toHaveLength(2));
    expect(result.current.lastEventId).toBe(2);
  });

  it("reconnects with last_event_id on close", async () => {
    renderHook(() => useRunSession("S3"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0].push({ type: "session.started", session_id: "S3", event_id: 4, total_runs: 1, conditions: ["x"] });
      FakeWS.instances[0].close();
    });
    await waitFor(() => expect(FakeWS.instances).toHaveLength(2));
    expect(FakeWS.instances[1].url).toContain("last_event_id=4");
  });

  it("stops reconnecting after session.finished", async () => {
    renderHook(() => useRunSession("S4"));
    await waitFor(() => expect(FakeWS.instances).toHaveLength(1));
    act(() => {
      FakeWS.instances[0].push({ type: "session.finished", session_id: "S4", event_id: 9, duration_s: 1 });
      FakeWS.instances[0].close();
    });
    // Give a tick.
    await new Promise((r) => setTimeout(r, 50));
    expect(FakeWS.instances).toHaveLength(1);
  });
});
```

- [ ] **Step 3: Run test, expect failure**

```bash
cd web && npm test -- --run tests/useRunSession.test.ts
```
Expected: 4 tests fail.

- [ ] **Step 4: Implement `web/src/ws/useRunSession.ts`**

```ts
import { useEffect, useRef, useState } from "react";
import type { Envelope } from "./envelope";

interface State {
  envelopes: Envelope[];
  lastEventId: number;
  status: "connecting" | "open" | "closed" | "done";
  error: string | null;
}

const RECONNECT_DELAY_MS = 750;

export function useRunSession(sid: string | undefined) {
  const [state, setState] = useState<State>({
    envelopes: [], lastEventId: 0, status: "connecting", error: null,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const lastIdRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    if (!sid) return;
    doneRef.current = false;
    lastIdRef.current = 0;

    function connect() {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${window.location.host}/ws/sessions/${sid}?last_event_id=${lastIdRef.current}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setState((s) => ({ ...s, status: "connecting" }));

      ws.onopen = () => setState((s) => ({ ...s, status: "open" }));

      ws.onmessage = (ev) => {
        let env: Envelope;
        try { env = JSON.parse(ev.data) as Envelope; }
        catch { return; }
        if (typeof env.event_id === "number" && env.event_id > lastIdRef.current) {
          lastIdRef.current = env.event_id;
        }
        if (env.type === "session.finished" || env.type === "session.error") {
          doneRef.current = true;
        }
        setState((s) => ({
          ...s,
          envelopes: [...s.envelopes, env],
          lastEventId: lastIdRef.current,
        }));
      };

      ws.onclose = () => {
        if (doneRef.current) {
          setState((s) => ({ ...s, status: "done" }));
          return;
        }
        setState((s) => ({ ...s, status: "closed" }));
        setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();
    return () => {
      doneRef.current = true;
      wsRef.current?.close();
    };
  }, [sid]);

  return state;
}
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd web && npm test -- --run tests/useRunSession.test.ts
```
Expected: 4 tests pass. If the reconnect test races, raise `RECONNECT_DELAY_MS` to `1` in tests via a `jest.useFakeTimers`-style helper (vitest has `vi.useFakeTimers()`).

- [ ] **Step 6: Commit**

```bash
git add web/src/ws/envelope.ts web/src/ws/useRunSession.ts web/tests/useRunSession.test.ts
git commit -m "feat(ui/web): WebSocket hook with reconnect and last_event_id replay"
```

---

## Task 5b: Run page — layout + ProgressHeader

**Files:**
- Create: `web/src/components/ProgressHeader.tsx`
- Create: `web/src/components/VerifyChip.tsx`
- Create: `web/src/components/IsolationChip.tsx`
- Modify: `web/src/pages/Run.tsx` (overwrite stub)

- [ ] **Step 1: Write `web/src/components/VerifyChip.tsx`**

```tsx
import { Chip } from "@mui/material";
import type { VerifyStatus } from "../api/types";

interface Props {
  status: VerifyStatus | "running" | null | undefined;
  passed?: number | null;
  failed?: number | null;
}

const palette: Record<string, "success" | "error" | "warning" | "info" | "default"> = {
  passed: "success",
  failed: "error",
  skipped: "default",
  timeout: "warning",
  error: "warning",
  running: "info",
};

export default function VerifyChip({ status, passed, failed }: Props) {
  if (!status) return <Chip size="small" label="🧪 pending" variant="outlined" />;
  if (status === "passed") {
    return <Chip size="small" color="success" label={`🧪 ${passed ?? "?"}/${passed ?? "?"}`} />;
  }
  if (status === "failed") {
    const total = (passed ?? 0) + (failed ?? 0);
    return <Chip size="small" color="error" label={`🧪 ${passed ?? "?"}/${total} (${failed ?? "?"} failing)`} />;
  }
  if (status === "running") return <Chip size="small" color="info" label="🧪 running…" />;
  return <Chip size="small" color={palette[status] ?? "default"} label={`🧪 ${status}`} />;
}
```

- [ ] **Step 2: Write `web/src/components/IsolationChip.tsx`**

```tsx
import { Chip } from "@mui/material";

interface Props {
  nonce: boolean;
  shuffle: boolean;
}

export default function IsolationChip({ nonce, shuffle }: Props) {
  if (nonce && shuffle) {
    return <Chip size="small" color="success" label="🔒 isolated (nonce + shuffled)" variant="outlined" />;
  }
  if (!nonce && !shuffle) {
    return <Chip size="small" color="warning" label="🔓 isolation off" variant="outlined" />;
  }
  return <Chip size="small" color="warning"
    label={`🔒 isolated (${nonce ? "nonce" : "shuffle"} only)`} variant="outlined" />;
}
```

- [ ] **Step 3: Write `web/src/components/ProgressHeader.tsx`**

```tsx
import { Stack, Typography, LinearProgress, Box, Chip } from "@mui/material";
import VerifyChip from "./VerifyChip";
import IsolationChip from "./IsolationChip";
import type { VerifyStatus } from "../api/types";

interface Props {
  runIdx: number;       // 1-based
  totalRuns: number;
  condition: string | null;
  rep: number | null;
  done: number;
  running: number;
  pending: number;
  verifyCounts: { passed: number; failed: number; total: number };
  currentCommand?: string | null;
  isolation: { nonce: boolean; shuffle: boolean };
  baselineStatus?: VerifyStatus | null;
}

export default function ProgressHeader(props: Props) {
  const pct = props.totalRuns === 0 ? 0 : (props.done / props.totalRuns) * 100;
  return (
    <Stack spacing={1}>
      <Typography variant="h6">
        Run {props.runIdx}/{props.totalRuns}
        {props.condition && <> · condition: <b>{props.condition}</b></>}
        {props.rep !== null && <> · rep: <b>{props.rep}</b></>}
      </Typography>
      <LinearProgress variant="determinate" value={pct} />
      <Stack direction="row" spacing={1} flexWrap="wrap">
        <Chip size="small" label={`${props.done} done`} color="success" variant="outlined" />
        <Chip size="small" label={`${props.running} running`} color="info" variant="outlined" />
        <Chip size="small" label={`${props.pending} pending`} variant="outlined" />
        <Box sx={{ flex: 1 }} />
        <VerifyChip
          status="passed"
          passed={props.verifyCounts.passed}
          failed={props.verifyCounts.failed}
        />
        {props.baselineStatus && (
          <Chip
            size="small"
            label={`baseline ${props.baselineStatus}`}
            color={props.baselineStatus === "passed" ? "success" : "warning"}
            variant="outlined"
          />
        )}
        <IsolationChip nonce={props.isolation.nonce} shuffle={props.isolation.shuffle} />
        {props.currentCommand && (
          <Chip size="small" label={`cmd: ${props.currentCommand}`} variant="outlined" />
        )}
      </Stack>
    </Stack>
  );
}
```

- [ ] **Step 4: Rewrite `web/src/pages/Run.tsx` (initial layout — sidebar + stream slots added in later subtasks)**

```tsx
import { useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Stack, Box, Button, Typography } from "@mui/material";
import { useRunSession } from "../ws/useRunSession";
import ProgressHeader from "../components/ProgressHeader";
import { useCancelSession } from "../api/queries";

export default function Run() {
  const { sid } = useParams<{ sid: string }>();
  const navigate = useNavigate();
  const ws = useRunSession(sid);
  const cancel = useCancelSession();

  const derived = useMemo(() => {
    let totalRuns = 0, done = 0, running = 0;
    let runIdx = 0, condition: string | null = null, rep: number | null = null;
    let verifyPassed = 0, verifyFailed = 0, verifyTotal = 0;
    let firstFinishedCond: string | null = null;
    let firstFinishedRep: number | null = null;
    let sessionFinished = false;
    let isolationOn = { nonce: true, shuffle: true };
    for (const e of ws.envelopes) {
      if (e.type === "session.started") { totalRuns = e.total_runs; }
      else if (e.type === "run.started") {
        runIdx = e.run_idx; condition = e.condition; rep = e.rep; running += 1;
      }
      else if (e.type === "run.finished") {
        running = Math.max(0, running - 1); done += 1;
        if (e.verify?.status === "passed") {
          verifyPassed += e.verify.passed_count ?? 0;
          verifyTotal += (e.verify.passed_count ?? 0) + (e.verify.failed_count ?? 0);
        } else if (e.verify?.status === "failed") {
          verifyFailed += e.verify.failed_count ?? 0;
          verifyTotal += (e.verify.passed_count ?? 0) + (e.verify.failed_count ?? 0);
        }
        if (firstFinishedCond === null && e.finished) {
          firstFinishedCond = e.condition; firstFinishedRep = e.rep;
        }
      }
      else if (e.type === "session.finished") { sessionFinished = true; }
    }
    const pending = Math.max(0, totalRuns - done - running);
    return {
      totalRuns, done, running, pending, runIdx, condition, rep,
      verify: { passed: verifyPassed, failed: verifyFailed, total: verifyTotal },
      sessionFinished, firstFinishedCond, firstFinishedRep, isolationOn,
    };
  }, [ws.envelopes]);

  // On session.finished, navigate to the trace of the first finished rep
  // (or stay if none — error path is handled inside `Run`'s body).
  if (derived.sessionFinished && derived.firstFinishedCond !== null) {
    // Defer navigation to avoid setState-in-render; one-shot via setTimeout(0).
    setTimeout(() => {
      // Read experiment name from the very first env (or sessionStorage if needed).
      const exp = ws.envelopes.find((e) => e.type === "session.started");
      void exp;
      // We don't have experiment name in the envelope — rely on backend GET below.
      // Fallback: stay on the page and surface a link.
    }, 0);
  }

  return (
    <Stack spacing={2} sx={{ height: "100%" }}>
      <Stack direction="row" alignItems="center" spacing={2}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>Live run · {sid}</Typography>
        <Button
          color="warning" variant="outlined"
          disabled={!sid || derived.sessionFinished}
          onClick={() => sid && cancel.mutateAsync(sid)}
        >Cancel</Button>
      </Stack>
      <ProgressHeader
        runIdx={derived.runIdx}
        totalRuns={derived.totalRuns}
        condition={derived.condition}
        rep={derived.rep}
        done={derived.done}
        running={derived.running}
        pending={derived.pending}
        verifyCounts={derived.verify}
        isolation={derived.isolationOn}
      />
      <Stack direction="row" spacing={2} sx={{ flex: 1, minHeight: 0 }}>
        <Box sx={{ width: 280, overflow: "auto" }}>{/* RunSidebar in Task 5c */}</Box>
        <Box sx={{ flex: 1, overflow: "auto" }}>{/* EventStream in Task 5d */}</Box>
      </Stack>
    </Stack>
  );
}
```

> **Navigation-on-finish note for the executing engineer:** envelopes do not carry the experiment name. Since `POST /api/runs` is what created the session, the caller (ExperimentList / ExperimentEdit) has the name. Persist it through `navigate(..., { state: { experimentName } })` and read via `useLocation()` in Run. Update both callers in Task 5f.

- [ ] **Step 5: Run all tests, expect pass**

```bash
cd web && npm test -- --run
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/{ProgressHeader,VerifyChip,IsolationChip}.tsx web/src/pages/Run.tsx
git commit -m "feat(ui/web): Run page layout + ProgressHeader + verify/isolation chips"
```

---

## Task 5c: Run page — RunSidebar (per-rep cards)

**Files:**
- Create: `web/src/components/RunSidebar.tsx`
- Create: `web/src/components/RunSidebarCard.tsx`
- Create: `web/tests/RunSidebar.test.tsx`
- Modify: `web/src/pages/Run.tsx`

- [ ] **Step 1: Implement `web/src/components/RunSidebarCard.tsx`**

```tsx
import { Card, CardContent, Stack, Typography } from "@mui/material";
import VerifyChip from "./VerifyChip";
import type { VerifyStatus } from "../api/types";

interface Props {
  condition: string;
  rep: number;
  state: "pending" | "running" | "done";
  verifyStatus: VerifyStatus | "running" | null;
  verifyPassed: number | null;
  verifyFailed: number | null;
  durationS?: number | null;
}

const borderColor: Record<Props["state"], string> = {
  pending: "divider",
  running: "info.main",
  done: "success.main",
};

export default function RunSidebarCard(p: Props) {
  return (
    <Card variant="outlined" sx={{ borderLeft: 4, borderLeftColor: borderColor[p.state] }}>
      <CardContent sx={{ py: 1.25 }}>
        <Stack spacing={0.5}>
          <Typography variant="body2"><b>{p.condition}</b> · rep {p.rep}</Typography>
          <Typography variant="caption" color="text.secondary">
            {p.state} {p.durationS != null && `· ${p.durationS.toFixed(1)}s`}
          </Typography>
          <VerifyChip status={p.verifyStatus} passed={p.verifyPassed} failed={p.verifyFailed} />
        </Stack>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Implement `web/src/components/RunSidebar.tsx`**

```tsx
import { Stack, Typography } from "@mui/material";
import RunSidebarCard from "./RunSidebarCard";
import type { Envelope } from "../ws/envelope";
import type { VerifyStatus } from "../api/types";

interface Item {
  condition: string;
  rep: number;
  state: "pending" | "running" | "done";
  verifyStatus: VerifyStatus | "running" | null;
  verifyPassed: number | null;
  verifyFailed: number | null;
}

interface Props {
  conditions: string[];
  totalReps: number;       // reps_per_condition guessed from total_runs / conditions
  envelopes: Envelope[];
}

export default function RunSidebar({ conditions, totalReps, envelopes }: Props) {
  // Seed all (condition × rep) slots as pending.
  const map = new Map<string, Item>();
  for (const c of conditions) {
    for (let r = 0; r < totalReps; r += 1) {
      map.set(`${c}/${r}`, {
        condition: c, rep: r, state: "pending",
        verifyStatus: null, verifyPassed: null, verifyFailed: null,
      });
    }
  }
  for (const e of envelopes) {
    if (e.type === "run.started") {
      const k = `${e.condition}/${e.rep}`;
      const it = map.get(k);
      if (it) it.state = "running";
    } else if (e.type === "run.finished") {
      const k = `${e.condition}/${e.rep}`;
      const it = map.get(k);
      if (it) {
        it.state = "done";
        it.verifyStatus = e.verify.status as VerifyStatus | null;
        it.verifyPassed = e.verify.passed_count;
        it.verifyFailed = e.verify.failed_count;
      }
    }
  }

  // Group by condition.
  const groups: Record<string, Item[]> = {};
  for (const c of conditions) groups[c] = [];
  for (const it of map.values()) groups[it.condition].push(it);

  return (
    <Stack spacing={2}>
      {conditions.map((c) => (
        <Stack key={c} spacing={1}>
          <Typography variant="caption" color="text.secondary">{c}</Typography>
          {groups[c]
            .sort((a, b) => a.rep - b.rep)
            .map((it) => (
              <RunSidebarCard key={`${c}-${it.rep}`} {...it} />
            ))}
        </Stack>
      ))}
    </Stack>
  );
}
```

- [ ] **Step 3: Write the failing test**

`web/tests/RunSidebar.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import RunSidebar from "../src/components/RunSidebar";
import type { Envelope } from "../src/ws/envelope";

test("seeds pending cards and transitions on run.started + run.finished", () => {
  const envelopes: Envelope[] = [
    { type: "session.started", session_id: "S", event_id: 1, total_runs: 4, conditions: ["a", "b"] },
    { type: "run.started", session_id: "S", event_id: 2, run_idx: 1, total_runs: 4, condition: "a", rep: 0 },
    { type: "run.finished", session_id: "S", event_id: 3, run_idx: 1, total_runs: 4,
      condition: "a", rep: 0, finished: true, interrupted_reason: null,
      verify: { status: "passed", passed_count: 3, failed_count: 0, failed_names: [], command: "pytest", duration_s: 1.2 } },
  ];
  render(<RunSidebar conditions={["a", "b"]} totalReps={2} envelopes={envelopes} />);
  // 4 cards rendered
  expect(screen.getAllByText(/rep \d/)).toHaveLength(4);
  expect(screen.getByText(/3\/3/)).toBeInTheDocument();
});
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/RunSidebar.test.tsx
```
Expected: 1 test passes.

- [ ] **Step 5: Wire into `Run.tsx`**

In `Run.tsx`, replace the sidebar `<Box>` placeholder:

```tsx
import RunSidebar from "../components/RunSidebar";
// ...
const conditionsArr = useMemo(() => {
  const e = ws.envelopes.find((x) => x.type === "session.started");
  return e ? (e as any).conditions as string[] : [];
}, [ws.envelopes]);
const totalReps = derived.totalRuns && conditionsArr.length
  ? Math.max(1, Math.floor(derived.totalRuns / conditionsArr.length))
  : 0;
// ...
<Box sx={{ width: 280, overflow: "auto" }}>
  <RunSidebar conditions={conditionsArr} totalReps={totalReps} envelopes={ws.envelopes} />
</Box>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/components/{RunSidebar,RunSidebarCard}.tsx \
        web/src/pages/Run.tsx web/tests/RunSidebar.test.tsx
git commit -m "feat(ui/web): Run sidebar with per-rep cards"
```

---

## Task 5d: Run page — EventStream + turn grouping + filter bar

**Files:**
- Create: `web/src/lib/groupEventsByTurn.ts`
- Create: `web/tests/groupEventsByTurn.test.ts`
- Create: `web/src/components/EventStream.tsx`
- Create: `web/src/components/EventFilterBar.tsx`
- Create: `web/tests/EventStream.test.tsx`
- Modify: `web/src/pages/Run.tsx`

The stream groups raw OpenCode `event`s by their `messageID` (or fallback to `step-start.messageID`). Each group is rendered as a turn block with the `step-finish.reason` chip when seen.

- [ ] **Step 1: Write the failing test for grouping**

`web/tests/groupEventsByTurn.test.ts`:
```ts
import { groupEventsByTurn } from "../src/lib/groupEventsByTurn";

const events = [
  { part: { type: "step-start", messageID: "M1" }, timestamp: 1 },
  { part: { type: "reasoning", messageID: "M1", text: "thinking" }, timestamp: 2 },
  { part: { type: "tool-call", messageID: "M1", name: "ls" }, timestamp: 3 },
  { part: { type: "step-finish", messageID: "M1", reason: "tool-calls",
            tokens: { input: 10, output: 5 }, cost: 0.01 }, timestamp: 4 },
  { part: { type: "step-start", messageID: "M2" }, timestamp: 5 },
  { part: { type: "text", messageID: "M2", text: "Done" }, timestamp: 6 },
  { part: { type: "step-finish", messageID: "M2", reason: "stop",
            tokens: { input: 12, output: 8 }, cost: 0.02 }, timestamp: 7 },
];

test("groups by messageID, sorts by timestamp, extracts step-finish fields", () => {
  const groups = groupEventsByTurn(events);
  expect(groups).toHaveLength(2);
  expect(groups[0].messageId).toBe("M1");
  expect(groups[0].reason).toBe("tool-calls");
  expect(groups[0].tokensIn).toBe(10);
  expect(groups[1].messageId).toBe("M2");
  expect(groups[1].reason).toBe("stop");
});

test("turn without step-finish has reason=null", () => {
  const groups = groupEventsByTurn([
    { part: { type: "reasoning", messageID: "X", text: "..." }, timestamp: 1 },
  ]);
  expect(groups).toHaveLength(1);
  expect(groups[0].reason).toBeNull();
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/groupEventsByTurn.test.ts
```
Expected: 2 tests fail.

- [ ] **Step 3: Implement `web/src/lib/groupEventsByTurn.ts`**

```ts
export interface TurnGroup {
  messageId: string;
  parts: any[];          // raw OpenCode parts, sorted by timestamp asc
  reason: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  tokensReasoning: number | null;
  cost: number | null;
  startedAt: number | null;
  endedAt: number | null;
}

export function groupEventsByTurn(events: any[]): TurnGroup[] {
  const byId = new Map<string, TurnGroup>();
  const order: string[] = [];
  for (const ev of events) {
    const id = ev?.part?.messageID;
    if (!id) continue;
    if (!byId.has(id)) {
      byId.set(id, {
        messageId: id, parts: [], reason: null,
        tokensIn: null, tokensOut: null, tokensReasoning: null,
        cost: null, startedAt: ev.timestamp ?? null, endedAt: null,
      });
      order.push(id);
    }
    const g = byId.get(id)!;
    g.parts.push(ev.part);
    g.endedAt = ev.timestamp ?? g.endedAt;
    if (ev.part.type === "step-finish") {
      g.reason = ev.part.reason ?? null;
      g.tokensIn = ev.part.tokens?.input ?? null;
      g.tokensOut = ev.part.tokens?.output ?? null;
      g.tokensReasoning = ev.part.tokens?.reasoning ?? null;
      g.cost = ev.part.cost ?? null;
    }
  }
  for (const g of byId.values()) {
    g.parts.sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));
  }
  return order.map((id) => byId.get(id)!);
}
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/groupEventsByTurn.test.ts
```
Expected: 2 tests pass.

- [ ] **Step 5: Write `web/src/components/EventFilterBar.tsx`**

```tsx
import { Stack, FormControlLabel, Checkbox } from "@mui/material";

export type EventFilters = {
  reasoning: boolean;
  tool: boolean;
  text: boolean;
  error: boolean;
};

interface Props {
  value: EventFilters;
  onChange: (next: EventFilters) => void;
  autoScroll: boolean;
  onAutoScrollChange: (b: boolean) => void;
}

export default function EventFilterBar({ value, onChange, autoScroll, onAutoScrollChange }: Props) {
  function tog(k: keyof EventFilters) {
    return () => onChange({ ...value, [k]: !value[k] });
  }
  return (
    <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
      <FormControlLabel control={<Checkbox size="small" checked={value.reasoning} onChange={tog("reasoning")} />} label="think" />
      <FormControlLabel control={<Checkbox size="small" checked={value.tool} onChange={tog("tool")} />} label="tool" />
      <FormControlLabel control={<Checkbox size="small" checked={value.text} onChange={tog("text")} />} label="text" />
      <FormControlLabel control={<Checkbox size="small" checked={value.error} onChange={tog("error")} />} label="err" />
      <FormControlLabel control={<Checkbox size="small" checked={autoScroll} onChange={() => onAutoScrollChange(!autoScroll)} />} label="auto-scroll" />
    </Stack>
  );
}
```

- [ ] **Step 6: Write `web/src/components/EventStream.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Typography, Stack } from "@mui/material";
import EventFilterBar, { type EventFilters } from "./EventFilterBar";
import { groupEventsByTurn, type TurnGroup } from "../lib/groupEventsByTurn";
import type { Envelope } from "../ws/envelope";

interface Props { envelopes: Envelope[]; }

const defaultFilters: EventFilters = { reasoning: true, tool: true, text: true, error: true };

function matchesFilter(partType: string, f: EventFilters): boolean {
  if (partType === "reasoning" && !f.reasoning) return false;
  if ((partType === "tool-call" || partType === "tool-result") && !f.tool) return false;
  if (partType === "text" && !f.text) return false;
  if (partType === "error" && !f.error) return false;
  return true;
}

function partTone(partType: string): string {
  if (partType === "reasoning") return "info.dark";
  if (partType === "tool-call") return "primary.main";
  if (partType === "tool-result") return "success.dark";
  if (partType === "error") return "error.main";
  return "text.primary";
}

export default function EventStream({ envelopes }: Props) {
  const [filters, setFilters] = useState<EventFilters>(defaultFilters);
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const groups: TurnGroup[] = useMemo(() => {
    const raw = envelopes
      .filter((e) => e.type === "raw_event")
      .map((e: any) => e.event);
    return groupEventsByTurn(raw);
  }, [envelopes]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [groups, autoScroll]);

  return (
    <Stack spacing={1} sx={{ height: "100%" }}>
      <EventFilterBar
        value={filters} onChange={setFilters}
        autoScroll={autoScroll} onAutoScrollChange={setAutoScroll}
      />
      <Box sx={{
        flex: 1, overflow: "auto", fontFamily: "monospace", fontSize: 13,
        bgcolor: "#0e1116", color: "#dbe1ec", borderRadius: 1, p: 1.5,
      }}>
        {groups.map((g, i) => (
          <Box key={g.messageId} sx={{ mb: 2 }}>
            <Typography variant="caption" sx={{ color: "#7d8a9e" }}>
              ━━ turn {i + 1} ━━ {g.reason && <>· {g.reason}</>}
            </Typography>
            {g.parts.filter((p) => matchesFilter(p.type, filters)).map((p, j) => (
              <Box key={j} sx={{ color: partTone(p.type), pl: 2, mt: 0.5 }}>
                {p.type === "reasoning" && <>💭 {p.text}</>}
                {p.type === "tool-call" && <>✎ {p.name} {JSON.stringify(p.input).slice(0, 200)}</>}
                {p.type === "tool-result" && <>✓ {p.name} → {String(p.output ?? "").slice(0, 200)}</>}
                {p.type === "text" && <>🗨 {p.text}</>}
                {p.type === "error" && <>⚠ {p.message ?? JSON.stringify(p).slice(0, 200)}</>}
              </Box>
            ))}
          </Box>
        ))}
        <div ref={bottomRef} />
      </Box>
    </Stack>
  );
}
```

- [ ] **Step 7: Write the failing test for EventStream**

`web/tests/EventStream.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import EventStream from "../src/components/EventStream";
import type { Envelope } from "../src/ws/envelope";

test("renders one turn block per messageID", () => {
  const envelopes: Envelope[] = [
    { type: "raw_event", session_id: "S", event_id: 1, run_idx: 1, condition: "a", rep: 0,
      event: { part: { type: "reasoning", messageID: "M1", text: "hello" }, timestamp: 1 } },
    { type: "raw_event", session_id: "S", event_id: 2, run_idx: 1, condition: "a", rep: 0,
      event: { part: { type: "step-finish", messageID: "M1", reason: "stop", tokens: { input: 1, output: 1 } }, timestamp: 2 } },
  ];
  render(<EventStream envelopes={envelopes} />);
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  expect(screen.getByText(/hello/)).toBeInTheDocument();
});
```

- [ ] **Step 8: Run test, expect pass**

```bash
cd web && npm test -- --run tests/EventStream.test.tsx
```
Expected: 1 test passes.

- [ ] **Step 9: Wire EventStream into `Run.tsx`**

```tsx
import EventStream from "../components/EventStream";
// ...
<Box sx={{ flex: 1, overflow: "hidden" }}>
  <EventStream envelopes={ws.envelopes} />
</Box>
```

- [ ] **Step 10: Commit**

```bash
git add web/src/lib/groupEventsByTurn.ts web/src/components/{EventStream,EventFilterBar}.tsx \
        web/src/pages/Run.tsx \
        web/tests/{groupEventsByTurn.test.ts,EventStream.test.tsx}
git commit -m "feat(ui/web): live EventStream with turn grouping + filters"
```

---

## Task 5e: Run page — navigate to TraceView on finish + cancel UX

**Files:**
- Modify: `web/src/pages/ExperimentList.tsx` (pass experimentName in nav state)
- Modify: `web/src/pages/ExperimentEdit.tsx` (same)
- Modify: `web/src/pages/Run.tsx` (consume state, navigate)

- [ ] **Step 1: Update `ExperimentList.tsx`**

Find the `handleRun` function and replace the navigate call so it carries the experiment name:

```tsx
async function handleRun(name: string) {
  const { session_id } = await start.mutateAsync(name);
  navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
}
```

- [ ] **Step 2: Update `ExperimentEdit.tsx`**

Same edit in the `handleRun` body inside ExperimentEdit:

```tsx
async function handleRun() {
  if (!name) return;
  const { session_id } = await start.mutateAsync(name);
  navigate(`/runs/sessions/${session_id}`, { state: { experimentName: name } });
}
```

- [ ] **Step 3: Update `Run.tsx` to navigate on finish**

```tsx
import { useLocation, useParams, useNavigate } from "react-router-dom";
import { useEffect } from "react";
// ...
const location = useLocation();
const experimentName = (location.state as { experimentName?: string } | null)?.experimentName ?? null;

useEffect(() => {
  if (
    derived.sessionFinished &&
    derived.firstFinishedCond !== null &&
    derived.firstFinishedRep !== null &&
    experimentName
  ) {
    navigate(
      `/runs/${experimentName}/${derived.firstFinishedCond}/${derived.firstFinishedRep}`,
    );
  }
}, [derived.sessionFinished, derived.firstFinishedCond, derived.firstFinishedRep, experimentName, navigate]);
```

If `experimentName` is null (e.g. page reloaded mid-run, losing router state), render a fallback link panel inside the body:

```tsx
{derived.sessionFinished && experimentName === null && (
  <Typography color="warning.main">
    Session finished. Reopen via the Experiments list to view the trace.
  </Typography>
)}
```

- [ ] **Step 4: Remove the dead placeholder block**

Delete the earlier `setTimeout(...)` no-op `if (derived.sessionFinished && ...)` block from the prior task (it was a placeholder; the `useEffect` above replaces it).

- [ ] **Step 5: Run all tests, expect pass**

```bash
cd web && npm test -- --run
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/{ExperimentList,ExperimentEdit,Run}.tsx
git commit -m "feat(ui/web): pass experimentName into Run; navigate to TraceView on finish"
```

---

## Task 6a: TraceView — page skeleton + VerdictBanner + AggregateStatsBar

**Files:**
- Create: `web/src/components/VerdictBanner.tsx`
- Create: `web/src/components/AggregateStatsBar.tsx`
- Create: `web/src/lib/stopReasonHistogram.ts`
- Create: `web/src/lib/formatTokens.ts`
- Create: `web/tests/stopReasonHistogram.test.ts`
- Create: `web/tests/VerdictBanner.test.tsx`
- Modify: `web/src/pages/TraceView.tsx` (overwrite stub)

- [ ] **Step 1: Write the failing test for stopReasonHistogram**

`web/tests/stopReasonHistogram.test.ts`:
```ts
import { stopReasonHistogram } from "../src/lib/stopReasonHistogram";

test("counts reasons across turns, treats null as 'unknown'", () => {
  const h = stopReasonHistogram([
    { reason: "tool-calls" } as any,
    { reason: "tool-calls" } as any,
    { reason: "stop" } as any,
    { reason: null } as any,
  ]);
  expect(h).toEqual({ "tool-calls": 2, "stop": 1, "unknown": 1 });
});

test("empty turns → empty object", () => {
  expect(stopReasonHistogram([])).toEqual({});
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/stopReasonHistogram.test.ts
```

- [ ] **Step 3: Implement `web/src/lib/stopReasonHistogram.ts`**

```ts
import type { TurnInfo } from "../api/types";

export function stopReasonHistogram(turns: TurnInfo[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const t of turns) {
    const k = t.reason ?? "unknown";
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}
```

- [ ] **Step 4: Write `web/src/lib/formatTokens.ts`**

```ts
export function formatTokens(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd web && npm test -- --run tests/stopReasonHistogram.test.ts
```
Expected: 2 tests pass.

- [ ] **Step 6: Implement `web/src/components/VerdictBanner.tsx`**

```tsx
import { Alert, Stack, Typography } from "@mui/material";
import type { Trace } from "../api/types";

interface Props { trace: Trace; }

export default function VerdictBanner({ trace }: Props) {
  const v = trace.verify_status;
  if (v === "passed") {
    return (
      <Alert severity="success">
        <Typography variant="subtitle1">
          ✓ Verified — {trace.verify_passed_count}/{trace.verify_passed_count} tests passed
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
        </Typography>
      </Alert>
    );
  }
  if (v === "failed") {
    const total = (trace.verify_passed_count ?? 0) + (trace.verify_failed_count ?? 0);
    return (
      <Alert severity="error">
        <Typography variant="subtitle1">
          ✗ Verify failed — {trace.verify_passed_count}/{total}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
        </Typography>
      </Alert>
    );
  }
  if (v === "skipped") {
    return <Alert severity="info">Verify skipped.</Alert>;
  }
  if (v === "timeout") {
    return <Alert severity="warning">Verify timed out after {trace.verify_duration_s?.toFixed(0)}s.</Alert>;
  }
  if (v === "error") {
    return <Alert severity="warning">Verify errored — see verify_output.log.</Alert>;
  }
  return <Alert severity="info">No verify result.</Alert>;
}
```

- [ ] **Step 7: Write the failing test for VerdictBanner**

`web/tests/VerdictBanner.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import VerdictBanner from "../src/components/VerdictBanner";
import type { Trace } from "../src/api/types";

const base: Trace = {
  turns: [], verify_status: "passed", verify_command: "pytest",
  verify_duration_s: 1.2, verify_passed_count: 5, verify_failed_count: 0,
  verify_failed_names: [], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
};

test("passed banner", () => {
  render(<VerdictBanner trace={base} />);
  expect(screen.getByText(/✓ Verified/)).toBeInTheDocument();
});

test("failed banner", () => {
  render(<VerdictBanner trace={{ ...base, verify_status: "failed", verify_passed_count: 3, verify_failed_count: 2 }} />);
  expect(screen.getByText(/✗ Verify failed/)).toBeInTheDocument();
  expect(screen.getByText(/3\/5/)).toBeInTheDocument();
});
```

- [ ] **Step 8: Run test, expect pass**

```bash
cd web && npm test -- --run tests/VerdictBanner.test.tsx
```

- [ ] **Step 9: Implement `web/src/components/AggregateStatsBar.tsx`**

```tsx
import { Stack, Chip, Typography } from "@mui/material";
import { stopReasonHistogram } from "../lib/stopReasonHistogram";
import { formatTokens } from "../lib/formatTokens";
import type { TurnInfo } from "../api/types";

interface Props { turns: TurnInfo[]; }

export default function AggregateStatsBar({ turns }: Props) {
  const hist = stopReasonHistogram(turns);
  const tokensIn = turns.reduce((s, t) => s + (t.tokens_in ?? 0), 0);
  const tokensOut = turns.reduce((s, t) => s + (t.tokens_out ?? 0), 0);
  const cost = turns.reduce((s, t) => s + (t.cost ?? 0), 0);
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
      {Object.entries(hist).map(([reason, n]) => (
        <Chip key={reason} size="small" label={`${n} ${reason}`} variant="outlined" />
      ))}
      <Typography variant="body2" color="text.secondary">
        tokens in: {formatTokens(tokensIn)} · out: {formatTokens(tokensOut)} · cost: ${cost.toFixed(4)}
      </Typography>
    </Stack>
  );
}
```

- [ ] **Step 10: Implement initial `web/src/pages/TraceView.tsx`**

```tsx
import { useParams } from "react-router-dom";
import { Stack, Typography, CircularProgress, Alert } from "@mui/material";
import { useTrace } from "../api/queries";
import VerdictBanner from "../components/VerdictBanner";
import AggregateStatsBar from "../components/AggregateStatsBar";

export default function TraceView() {
  const { name, condition, rep } = useParams<{ name: string; condition: string; rep: string }>();
  const repN = Number(rep);
  const trace = useTrace(name!, condition!, repN);

  if (trace.isLoading) return <CircularProgress />;
  if (trace.error || !trace.data) return <Alert severity="error">Failed to load trace.</Alert>;

  return (
    <Stack spacing={2} sx={{ maxWidth: 1100, mx: "auto" }}>
      <Typography variant="h5">{name} / {condition} / rep {repN}</Typography>
      <VerdictBanner trace={trace.data} />
      <AggregateStatsBar turns={trace.data.turns} />
      {/* Turn timeline / VerifyCard / FinalDiffCard / etc. added in next tasks. */}
    </Stack>
  );
}
```

- [ ] **Step 11: Commit**

```bash
git add web/src/lib/{stopReasonHistogram,formatTokens}.ts \
        web/src/components/{VerdictBanner,AggregateStatsBar}.tsx \
        web/src/pages/TraceView.tsx \
        web/tests/{stopReasonHistogram.test.ts,VerdictBanner.test.tsx}
git commit -m "feat(ui/web): TraceView shell with VerdictBanner + aggregate stats"
```

---

## Task 6b: TraceView — TurnCard + ToolCallBlock + RawEventsToggle

**Files:**
- Create: `web/src/components/ToolCallBlock.tsx`
- Create: `web/src/components/RawEventsToggle.tsx`
- Create: `web/src/components/TurnCard.tsx`
- Create: `web/tests/TurnCard.test.tsx`
- Modify: `web/src/pages/TraceView.tsx`

Per spec §7.4: one TurnCard ≡ one `messageID`. Inside: header (short description + step-finish reason chip + show-raw toggle), body (parts in emission order), per-turn stats footer.

The TurnCard needs the raw events for the same messageID. We fetch them from `/api/runs/.../events`. To avoid downloading the whole jsonl repeatedly, the page fetches once at the top and passes a filtered slice down.

- [ ] **Step 1: Add `useEvents` to `web/src/api/queries.ts`**

```ts
export const useEvents = (name: string, condition: string, rep: number) =>
  useQuery({
    queryKey: ["events", name, condition, rep],
    queryFn: async () => {
      // Backend returns text/plain JSONL (one JSON per line).
      const text = await apiGet<string>(`/api/runs/${name}/${condition}/${rep}/events`);
      return text
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l));
    },
  });
```

- [ ] **Step 2: Implement `web/src/components/ToolCallBlock.tsx`**

```tsx
import { Box, Typography } from "@mui/material";

interface Props { call: any; result?: any; }

export default function ToolCallBlock({ call, result }: Props) {
  const ok = result ? !result.is_error : null;
  const icon = result ? (ok ? "✓" : "✗") : "✎";
  const name = call?.name ?? "?";
  const summary = JSON.stringify(call?.input ?? {}).slice(0, 200);
  const outputSnippet = result ? String(result.output ?? "").slice(0, 200) : null;
  return (
    <Box sx={{ pl: 1, borderLeft: 2, borderLeftColor: ok === false ? "error.main" : "primary.light", my: 1 }}>
      <Typography variant="body2"><b>{icon} {name}</b> {summary}</Typography>
      {outputSnippet && (
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "pre-wrap" }}>
          → {outputSnippet}
        </Typography>
      )}
    </Box>
  );
}
```

- [ ] **Step 3: Implement `web/src/components/RawEventsToggle.tsx`**

```tsx
import { useState } from "react";
import { Box, Button, Typography } from "@mui/material";

interface Props { events: unknown[]; }

export default function RawEventsToggle({ events }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <Box>
      <Button size="small" onClick={() => setOpen(!open)}>
        {open ? "hide raw ▴" : "show raw ▾"}
      </Button>
      {open && (
        <Box sx={{
          mt: 1, p: 1, bgcolor: "#0e1116", color: "#dbe1ec",
          fontFamily: "monospace", fontSize: 12, borderRadius: 1,
          maxHeight: 320, overflow: "auto",
        }}>
          {events.map((e, i) => (
            <Typography key={i} variant="caption" component="div">
              {JSON.stringify(e)}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}
```

- [ ] **Step 4: Implement `web/src/components/TurnCard.tsx`**

```tsx
import { Card, CardContent, Stack, Typography, Chip } from "@mui/material";
import ToolCallBlock from "./ToolCallBlock";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import type { TurnInfo } from "../api/types";
import type { TurnGroup } from "../lib/groupEventsByTurn";

interface Props {
  turn: TurnInfo;
  group: TurnGroup;
  index: number;
  rawEvents: unknown[];
}

function shortDescription(group: TurnGroup): string {
  const reasoning = group.parts.find((p) => p.type === "reasoning");
  if (reasoning) return String(reasoning.text ?? "").slice(0, 120);
  const calls = group.parts.filter((p) => p.type === "tool-call");
  if (calls.length > 0) return `→ ${calls.length} tool call${calls.length > 1 ? "s" : ""}`;
  const text = group.parts.find((p) => p.type === "text");
  if (text) return String(text.text ?? "").slice(0, 120);
  return "—";
}

export default function TurnCard({ turn, group, index, rawEvents }: Props) {
  const calls = group.parts.filter((p) => p.type === "tool-call");
  const results = group.parts.filter((p) => p.type === "tool-result");
  const reads = calls.filter((c) => c.name === "read").length;
  const greps = calls.filter((c) => c.name === "grep" || c.name === "search").length;
  const edits = calls.filter((c) => c.name === "edit" || c.name === "write").length;
  const duration = turn.started_at != null && turn.ended_at != null
    ? (turn.ended_at - turn.started_at).toFixed(1) + "s"
    : "—";

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography variant="caption" color="text.secondary">turn {index + 1}</Typography>
          <Typography variant="subtitle2" sx={{ flexGrow: 1, ml: 1 }}>
            {shortDescription(group)}
          </Typography>
          {turn.reason && <Chip size="small" label={`→ ${turn.reason}`} />}
        </Stack>
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          {group.parts.map((p, i) => {
            if (p.type === "reasoning") {
              return <Typography key={i} variant="body2" color="text.secondary">💭 {p.text}</Typography>;
            }
            if (p.type === "tool-call") {
              const matched = results.find((r) => r.toolCallID === p.toolCallID || r.callID === p.callID);
              return <ToolCallBlock key={i} call={p} result={matched} />;
            }
            if (p.type === "text") {
              return <Typography key={i} variant="body2">🗨 {p.text}</Typography>;
            }
            return null;
          })}
        </Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap">
          <Typography variant="caption" color="text.secondary">
            tools {calls.length} · reads {reads} · greps {greps} · edits {edits} ·{" "}
            tokens {formatTokens(turn.tokens_in)}/{formatTokens(turn.tokens_out)} ·{" "}
            cost ${turn.cost?.toFixed(4) ?? "—"} · {duration}
          </Typography>
        </Stack>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: Write the failing test for TurnCard**

`web/tests/TurnCard.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TurnCard from "../src/components/TurnCard";
import type { TurnInfo } from "../src/api/types";
import type { TurnGroup } from "../src/lib/groupEventsByTurn";

const turn: TurnInfo = {
  message_id: "M1", reason: "tool-calls",
  tokens_in: 100, tokens_out: 50, tokens_reasoning: null,
  cost: 0.001, started_at: 0, ended_at: 2,
};
const group: TurnGroup = {
  messageId: "M1",
  parts: [
    { type: "reasoning", text: "thinking…" },
    { type: "tool-call", name: "read", input: { path: "a.py" }, toolCallID: "c1" },
    { type: "tool-result", toolCallID: "c1", output: "ok" },
  ],
  reason: "tool-calls", tokensIn: 100, tokensOut: 50, tokensReasoning: null,
  cost: 0.001, startedAt: 0, endedAt: 2,
};

test("renders reasoning + tool call + per-turn stats", async () => {
  render(<TurnCard turn={turn} group={group} index={0} rawEvents={[{ part: { type: "tool-call" } }]} />);
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  expect(screen.getByText(/thinking…/)).toBeInTheDocument();
  expect(screen.getByText(/read/)).toBeInTheDocument();
  expect(screen.getByText(/reads 1/)).toBeInTheDocument();
  const btn = screen.getByRole("button", { name: /show raw/i });
  await userEvent.click(btn);
  expect(screen.getByText(/tool-call/)).toBeInTheDocument();
});
```

- [ ] **Step 6: Run test, expect pass**

```bash
cd web && npm test -- --run tests/TurnCard.test.tsx
```

- [ ] **Step 7: Wire TurnCards into `TraceView.tsx`**

```tsx
import { useEvents } from "../api/queries";
import { groupEventsByTurn } from "../lib/groupEventsByTurn";
import TurnCard from "../components/TurnCard";
// ...
const events = useEvents(name!, condition!, repN);
const groups = events.data ? groupEventsByTurn(events.data) : [];
// inside the Stack, after AggregateStatsBar:
{trace.data.turns.map((t, i) => {
  const g = groups.find((gg) => gg.messageId === t.message_id);
  if (!g) return null;
  const raw = events.data?.filter((e: any) => e?.part?.messageID === t.message_id) ?? [];
  return <TurnCard key={t.message_id} turn={t} group={g} index={i} rawEvents={raw} />;
})}
```

- [ ] **Step 8: Commit**

```bash
git add web/src/components/{TurnCard,ToolCallBlock,RawEventsToggle}.tsx \
        web/src/api/queries.ts web/src/pages/TraceView.tsx \
        web/tests/TurnCard.test.tsx
git commit -m "feat(ui/web): TurnCard + ToolCallBlock + RawEventsToggle in TraceView"
```

---

## Task 6c: TraceView — VerifyCard

**Files:**
- Create: `web/src/components/VerifyCard.tsx`
- Create: `web/tests/VerifyCard.test.tsx`
- Modify: `web/src/pages/TraceView.tsx`

- [ ] **Step 1: Implement `web/src/components/VerifyCard.tsx`**

```tsx
import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Button, Collapse, Box } from "@mui/material";
import type { Trace } from "../api/types";

interface Props { trace: Trace; }

export default function VerifyCard({ trace }: Props) {
  const [open, setOpen] = useState(false);
  const status = trace.verify_status;
  if (!status) return null;
  const passed = trace.verify_passed_count ?? 0;
  const failed = trace.verify_failed_count ?? 0;
  const total = passed + failed;
  const tone =
    status === "passed" ? "success.light"
    : status === "failed" ? "error.light"
    : "warning.light";

  return (
    <Card variant="outlined" sx={{ bgcolor: tone }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Chip size="small" label={`🧪 ${status}`} />
          <Typography variant="body2">
            {passed}/{total} · {trace.verify_command} · {trace.verify_duration_s?.toFixed(1)}s
          </Typography>
          {trace.verify_failed_names.length > 0 && (
            <Button size="small" onClick={() => setOpen(!open)}>
              {open ? "hide failing ▴" : `show ${trace.verify_failed_names.length} failing ▾`}
            </Button>
          )}
        </Stack>
        <Collapse in={open}>
          <Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12 }}>
            {trace.verify_failed_names.map((n) => (
              <Typography key={n} variant="body2" color="error">— {n}</Typography>
            ))}
          </Box>
        </Collapse>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Write the failing test**

`web/tests/VerifyCard.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VerifyCard from "../src/components/VerifyCard";
import type { Trace } from "../src/api/types";

const failed: Trace = {
  turns: [], verify_status: "failed", verify_command: "pytest",
  verify_duration_s: 3, verify_passed_count: 8, verify_failed_count: 2,
  verify_failed_names: ["test_a", "test_b"], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
};

test("shows command, counts, expands failing names", async () => {
  render(<VerifyCard trace={failed} />);
  expect(screen.getByText(/pytest/)).toBeInTheDocument();
  expect(screen.getByText(/8\/10/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show 2 failing/i }));
  expect(screen.getByText("— test_a")).toBeInTheDocument();
});

test("renders nothing when verify_status is null", () => {
  const { container } = render(
    <VerifyCard trace={{ ...failed, verify_status: null }} />,
  );
  expect(container.firstChild).toBeNull();
});
```

- [ ] **Step 3: Run test, expect pass**

```bash
cd web && npm test -- --run tests/VerifyCard.test.tsx
```

- [ ] **Step 4: Wire into `TraceView.tsx`**

After the last TurnCard:
```tsx
import VerifyCard from "../components/VerifyCard";
// ...
<VerifyCard trace={trace.data} />
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/VerifyCard.tsx web/src/pages/TraceView.tsx web/tests/VerifyCard.test.tsx
git commit -m "feat(ui/web): VerifyCard for TraceView"
```

---

## Task 6d: TraceView — FinalDiffCard + parsePatch

**Files:**
- Create: `web/src/lib/parsePatch.ts`
- Create: `web/tests/parsePatch.test.ts`
- Create: `web/src/components/FinalDiffCard.tsx`
- Create: `web/tests/FinalDiffCard.test.tsx`
- Modify: `web/src/pages/TraceView.tsx`

- [ ] **Step 1: Write the failing test for parsePatch**

`web/tests/parsePatch.test.ts`:
```ts
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
  expect(files[0].path).toBe("foo.py");
  expect(files[0].added).toBe(1);
  expect(files[0].removed).toBe(1);
  expect(files[1].path).toBe("bar.py");
  expect(files[1].added).toBe(1);
  expect(files[1].removed).toBe(0);
});

test("empty patch → empty array", () => {
  expect(parsePatch("")).toEqual([]);
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd web && npm test -- --run tests/parsePatch.test.ts
```

- [ ] **Step 3: Implement `web/src/lib/parsePatch.ts`**

```ts
export interface PatchFile {
  path: string;
  added: number;
  removed: number;
  hunkLines: string[];   // raw +/-/  /@@ lines for rendering
}

export function parsePatch(patch: string): PatchFile[] {
  if (!patch.trim()) return [];
  const lines = patch.split("\n");
  const files: PatchFile[] = [];
  let current: PatchFile | null = null;
  let inHunk = false;
  for (const ln of lines) {
    if (ln.startsWith("diff --git ")) {
      const m = /diff --git a\/(.+) b\/(.+)/.exec(ln);
      if (current) files.push(current);
      current = { path: m?.[2] ?? m?.[1] ?? "?", added: 0, removed: 0, hunkLines: [] };
      inHunk = false;
      continue;
    }
    if (!current) continue;
    if (ln.startsWith("@@")) { inHunk = true; current.hunkLines.push(ln); continue; }
    if (!inHunk) continue;
    current.hunkLines.push(ln);
    if (ln.startsWith("+") && !ln.startsWith("+++")) current.added += 1;
    else if (ln.startsWith("-") && !ln.startsWith("---")) current.removed += 1;
  }
  if (current) files.push(current);
  return files;
}
```

- [ ] **Step 4: Run test, expect pass**

```bash
cd web && npm test -- --run tests/parsePatch.test.ts
```

- [ ] **Step 5: Implement `web/src/components/FinalDiffCard.tsx`**

```tsx
import { useState } from "react";
import { Card, CardContent, Stack, Typography, Button, Box } from "@mui/material";
import { usePatch } from "../api/queries";
import { parsePatch, type PatchFile } from "../lib/parsePatch";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

function HunkLine({ line }: { line: string }) {
  let color = "text.primary";
  let bg = "transparent";
  if (line.startsWith("+") && !line.startsWith("+++")) { color = "success.main"; bg = "rgba(46,125,50,0.08)"; }
  else if (line.startsWith("-") && !line.startsWith("---")) { color = "error.main"; bg = "rgba(211,47,47,0.08)"; }
  else if (line.startsWith("@@")) { color = "text.secondary"; }
  return (
    <Box sx={{ color, bgcolor: bg, fontFamily: "monospace", fontSize: 12, whiteSpace: "pre" }}>
      {line || " "}
    </Box>
  );
}

export default function FinalDiffCard({ name, condition, rep }: Props) {
  const patch = usePatch(name, condition, rep);
  const [expanded, setExpanded] = useState(false);
  if (patch.isLoading) return null;
  if (!patch.data || patch.data.length === 0) {
    return (
      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle2">Final diff — no changes</Typography>
        </CardContent>
      </Card>
    );
  }
  const files: PatchFile[] = parsePatch(patch.data);
  const totalAdded = files.reduce((s, f) => s + f.added, 0);
  const totalRemoved = files.reduce((s, f) => s + f.removed, 0);
  // Spec §7.4: only diffs with ≥5 files or ≥200 lines collapse to the first 3.
  // showFiles MUST guard on !isLong, otherwise a short 4-file diff slices to 3
  // with no "show all" toggle and silently drops file #4.
  const isLong = files.length >= 5 || (totalAdded + totalRemoved) >= 200;
  const showFiles = expanded || !isLong ? files : files.slice(0, 3);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1}>
          <Typography variant="subtitle2">
            Final diff — {files.length} file{files.length === 1 ? "" : "s"}, +{totalAdded}/−{totalRemoved}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Button
            size="small"
            href={`/api/runs/${name}/${condition}/${rep}/patch`}
            download={`changes-${condition}-${rep}.patch`}
          >Download .patch</Button>
        </Stack>
        <Stack spacing={1} sx={{ mt: 1 }}>
          {showFiles.map((f) => (
            <Box key={f.path}>
              <Typography variant="body2"><b>{f.path}</b> · +{f.added}/−{f.removed}</Typography>
              <Box sx={{ borderLeft: 2, borderLeftColor: "divider", pl: 1, mt: 0.5 }}>
                {f.hunkLines.map((ln, i) => <HunkLine key={i} line={ln} />)}
              </Box>
            </Box>
          ))}
        </Stack>
        {isLong && !expanded && (
          <Button size="small" onClick={() => setExpanded(true)} sx={{ mt: 1 }}>
            show all {files.length} files
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 6: Write the failing test for FinalDiffCard**

`web/tests/FinalDiffCard.test.tsx`:
```tsx
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
```

- [ ] **Step 7: Run test, expect pass**

```bash
cd web && npm test -- --run tests/FinalDiffCard.test.tsx
```

- [ ] **Step 8: Wire into `TraceView.tsx`**

After the VerifyCard:
```tsx
import FinalDiffCard from "../components/FinalDiffCard";
// ...
<FinalDiffCard name={name!} condition={condition!} rep={repN} />
```

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/parsePatch.ts web/src/components/FinalDiffCard.tsx \
        web/src/pages/TraceView.tsx \
        web/tests/{parsePatch.test.ts,FinalDiffCard.test.tsx}
git commit -m "feat(ui/web): FinalDiffCard with parsed unified diff"
```

---

## Task 6e: TraceView — MethodComparisonCard

**Files:**
- Create: `web/src/components/MethodComparisonCard.tsx`
- Modify: `web/src/pages/TraceView.tsx`

Only rendered if the experiment defines `target_file` (+ optional `target_methods`). The card iterates `target_methods` and fetches `/api/runs/.../method_comparison?method=<name>` per method. If `target_methods` is empty, the spec says "side-by-side the whole file" — for v1 we render a single comparison with `method=<basename(target_file)>` and let the backend fall back to whole-file extraction.

- [ ] **Step 1: Implement `web/src/components/MethodComparisonCard.tsx`**

```tsx
import { Card, CardContent, Stack, Typography, Chip, Box } from "@mui/material";
import { useMethodComparison } from "../api/queries";
import { useExperiment } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

function SideBySide({ original, regen }: { original: string[]; regen: string[] }) {
  const maxLines = Math.max(original.length, regen.length);
  return (
    <Box sx={{
      display: "grid", gridTemplateColumns: "1fr 1fr",
      gap: 1, mt: 1, fontFamily: "monospace", fontSize: 12,
    }}>
      <Box>
        <Typography variant="caption" color="text.secondary">Original (reference)</Typography>
        <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", bgcolor: "grey.50", p: 1, borderRadius: 1 }}>
          {original.join("\n")}
        </Box>
      </Box>
      <Box>
        <Typography variant="caption" color="text.secondary">Agent's regeneration</Typography>
        <Box component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", bgcolor: "grey.50", p: 1, borderRadius: 1 }}>
          {regen.join("\n")}
        </Box>
      </Box>
    </Box>
  );
}

function MethodRow({ name, condition, rep, method }:
  Props & { method: string }) {
  const cmp = useMethodComparison(name, condition, rep, method);
  if (cmp.isLoading) return null;
  if (cmp.error || !cmp.data) return (
    <Typography variant="caption" color="error">{method}: failed to extract</Typography>
  );
  const diffCount = Math.max(0, cmp.data.original_lines.length - cmp.data.regen_lines.length)
    + Math.max(0, cmp.data.regen_lines.length - cmp.data.original_lines.length);
  return (
    <Box sx={{ mt: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2">{method}</Typography>
        {cmp.data.equivalent
          ? <Chip size="small" color="success" label="semantically equivalent ✓" />
          : <Chip size="small" color="warning" label={`divergent (${diffCount} lines differ)`} />}
      </Stack>
      <SideBySide original={cmp.data.original_lines} regen={cmp.data.regen_lines} />
    </Box>
  );
}

export default function MethodComparisonCard({ name, condition, rep }: Props) {
  const exp = useExperiment(name);
  const targetFile = exp.data?.target_file as string | undefined;
  const targetMethods = exp.data?.target_methods as string[] | undefined;
  if (!targetFile) return null;
  const methods = (targetMethods && targetMethods.length > 0)
    ? targetMethods
    : [targetFile.split("/").pop()!.replace(/\.[^.]+$/, "")];
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle2">Method comparison · {targetFile}</Typography>
        {methods.map((m) => (
          <MethodRow key={m} name={name} condition={condition} rep={rep} method={m} />
        ))}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Wire into `TraceView.tsx`**

After FinalDiffCard:
```tsx
import MethodComparisonCard from "../components/MethodComparisonCard";
// ...
<MethodComparisonCard name={name!} condition={condition!} rep={repN} />
```

- [ ] **Step 3: Run all tests**

```bash
cd web && npm test -- --run
```
Expected: still green (this card has no dedicated test — too API-shape-dependent for v1 unit; covered by manual smoke in Task 6g).

- [ ] **Step 4: Commit**

```bash
git add web/src/components/MethodComparisonCard.tsx web/src/pages/TraceView.tsx
git commit -m "feat(ui/web): MethodComparisonCard side-by-side"
```

---

## Task 6f: TraceView — MetricsDrawer

**Files:**
- Create: `web/src/components/MetricsDrawer.tsx`
- Modify: `web/src/pages/TraceView.tsx`

- [ ] **Step 1: Implement `web/src/components/MetricsDrawer.tsx`**

```tsx
import { useState } from "react";
import {
  Drawer, IconButton, Box, Typography, Divider, Stack, Tooltip,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useMetrics } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

export default function MetricsDrawer({ name, condition, rep }: Props) {
  const [open, setOpen] = useState(false);
  const metrics = useMetrics(name, condition, rep);
  return (
    <>
      <Tooltip title="Metrics">
        <IconButton
          color="primary"
          onClick={() => setOpen(true)}
          sx={{ position: "fixed", right: 16, top: 80 }}
        >
          <OpenInNewIcon />
        </IconButton>
      </Tooltip>
      <Drawer anchor="right" open={open} onClose={() => setOpen(false)}>
        <Box sx={{ width: 360, p: 2 }}>
          <Typography variant="h6">Metrics</Typography>
          <Divider sx={{ my: 1 }} />
          {metrics.isLoading && <Typography variant="body2">loading…</Typography>}
          {metrics.data && (
            <Stack spacing={1} sx={{ fontFamily: "monospace", fontSize: 12 }}>
              {Object.entries(metrics.data).map(([k, v]) => (
                <Box key={k}>
                  <Typography variant="caption" color="text.secondary">{k}</Typography>
                  <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </Box>
      </Drawer>
    </>
  );
}
```

- [ ] **Step 2: Wire into `TraceView.tsx`**

```tsx
import MetricsDrawer from "../components/MetricsDrawer";
// ... last child:
<MetricsDrawer name={name!} condition={condition!} rep={repN} />
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/MetricsDrawer.tsx web/src/pages/TraceView.tsx
git commit -m "feat(ui/web): MetricsDrawer for TraceView"
```

---

## Task 6g: TraceView — FooterNav (prev/next rep)

**Files:**
- Create: `web/src/components/FooterNav.tsx`
- Modify: `web/src/pages/TraceView.tsx`

- [ ] **Step 1: Implement `web/src/components/FooterNav.tsx`**

```tsx
import { Stack, Button, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useRuns } from "../api/queries";

interface Props {
  name: string;
  condition: string;
  rep: number;
}

export default function FooterNav({ name, condition, rep }: Props) {
  const runs = useRuns(name);
  if (!runs.data) return null;
  const ordered = [...runs.data].sort(
    (a, b) => a.condition.localeCompare(b.condition) || a.rep - b.rep,
  );
  const idx = ordered.findIndex((r) => r.condition === condition && r.rep === rep);
  const prev = idx > 0 ? ordered[idx - 1] : null;
  const next = idx >= 0 && idx < ordered.length - 1 ? ordered[idx + 1] : null;
  return (
    <Stack direction="row" alignItems="center" spacing={2} sx={{ mt: 4 }}>
      {prev
        ? <Button component={RouterLink} to={`/runs/${name}/${prev.condition}/${prev.rep}`}>
            ← {prev.condition}/rep {prev.rep}
          </Button>
        : <Button disabled>← prev</Button>}
      <Typography variant="body2" sx={{ flex: 1, textAlign: "center" }}>
        {idx + 1} / {ordered.length} runs
      </Typography>
      {next
        ? <Button component={RouterLink} to={`/runs/${name}/${next.condition}/${next.rep}`}>
            {next.condition}/rep {next.rep} →
          </Button>
        : <Button disabled>next →</Button>}
    </Stack>
  );
}
```

- [ ] **Step 2: Wire into `TraceView.tsx`**

```tsx
import FooterNav from "../components/FooterNav";
// ...
<FooterNav name={name!} condition={condition!} rep={repN} />
```

- [ ] **Step 3: Run all tests, expect pass**

```bash
cd web && npm test -- --run
```

- [ ] **Step 4: Commit**

```bash
git add web/src/components/FooterNav.tsx web/src/pages/TraceView.tsx
git commit -m "feat(ui/web): TraceView FooterNav (prev/next rep)"
```

- [ ] **Step 5: Manual smoke**

With backend + dev server running, open `http://127.0.0.1:5173/runs/<exp>/<cond>/<rep>` for a finished run and confirm:
- VerdictBanner reflects `verify_status` correctly,
- Aggregate stats render (token totals, reasons),
- TurnCards: one per `messageID`, parts in emission order, raw toggle filters by messageID,
- VerifyCard expands the failing list,
- FinalDiffCard renders +/− with download link working,
- MethodComparisonCard (only if `target_file` is set) shows side-by-side,
- MetricsDrawer opens and shows the metrics.json,
- FooterNav navigates between runs of the same experiment.

Do **not** commit this manual smoke — it's a checkpoint.

---

## Task 7: Static-serving + SPA fallback + CLI bundle check

**Files:**
- Modify: `abench_ui/server.py`
- Modify: `abench_ui/cli.py`
- Modify: `tests/abench_ui/test_cli.py`
- Create: `tests/abench_ui/test_static.py`

Now that the frontend builds into `abench_ui/static/`, the FastAPI app serves it at `/` and falls back to `index.html` for any non-API route (so client-side routes like `/runs/sessions/<sid>` resolve on reload). `abench-ui` warns and exits non-zero if the bundle is missing.

- [ ] **Step 1: Write the failing test for static serving**

`tests/abench_ui/test_static.py`:
```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abench_ui.server import create_app


@pytest.fixture
def app_with_static(tmp_path: Path, monkeypatch):
    static_dir = Path(__file__).resolve().parents[2] / "abench_ui" / "static"
    static_dir.mkdir(exist_ok=True)
    (static_dir / "index.html").write_text("<html><body>SPA</body></html>")
    (static_dir / "assets").mkdir(exist_ok=True)
    (static_dir / "assets" / "x.js").write_text("console.log('hi');")
    yield create_app(experiments_dir=tmp_path)
    # cleanup
    (static_dir / "index.html").unlink(missing_ok=True)
    (static_dir / "assets" / "x.js").unlink(missing_ok=True)
    try: (static_dir / "assets").rmdir()
    except OSError: pass


def test_serves_index_html_at_root(app_with_static):
    client = TestClient(app_with_static)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_serves_assets(app_with_static):
    client = TestClient(app_with_static)
    resp = client.get("/assets/x.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_unknown_route_falls_back_to_index(app_with_static):
    """Client-side router paths should still resolve."""
    client = TestClient(app_with_static)
    resp = client.get("/runs/sessions/abc123")
    assert resp.status_code == 200
    assert "SPA" in resp.text


def test_api_path_does_not_fall_back(app_with_static):
    """API 404s must remain API 404s — never bleed into SPA fallback."""
    client = TestClient(app_with_static)
    resp = client.get("/api/experiments/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
```

- [ ] **Step 2: Run test, expect failure**

```bash
.venv/bin/pytest tests/abench_ui/test_static.py -v
```
Expected: 4 tests fail (no static handlers wired in).

- [ ] **Step 3: Implement static + SPA fallback in `abench_ui/server.py`**

Add near the top of the file:

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

At the very end of `create_app` — **after** the websocket handler (currently around line 327-374) and **immediately before** `return app` (line 375) — append:

```python
    # ── Static SPA bundle ────────────────────────────────────────────────────
    # Order matters: this block runs after app.include_router(api) AND the
    # @app.websocket(...) registration, so the API and WS routes win over the
    # catch-all below.
    _static_dir = Path(__file__).resolve().parent / "static"
    _index = _static_dir / "index.html"
    if _index.is_file():
        _assets = _static_dir / "assets"
        if _assets.is_dir():
            app.mount("/assets", StaticFiles(directory=_assets), name="assets")

        @app.get("/", include_in_schema=False)
        def _spa_root():
            return FileResponse(_index)

        @app.get("/{full_path:path}", include_in_schema=False)
        def _spa_fallback(full_path: str):
            # Defence in depth: if a stray /api/... or /ws/... slips into the
            # catch-all (no matching API route registered), keep returning 404
            # instead of leaking index.html into client-side error handlers.
            if full_path.startswith("api/") or full_path.startswith("ws/"):
                raise HTTPException(404, f"not found: {full_path}")
            # Prefer a real static asset when one is at this exact path.
            candidate = _static_dir / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_index)
```

- [ ] **Step 4: Run test, expect pass**

```bash
.venv/bin/pytest tests/abench_ui/test_static.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Update `abench_ui/cli.py` to warn on missing bundle**

Add `import sys` at the top if not present. Replace the file with:

```python
"""`abench-ui` console-script — starts the FastAPI app via uvicorn."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from .server import create_app


def _static_index_path() -> Path:
    """Path to the SPA's index.html. Extracted as a function so tests can
    monkeypatch it without mutating the real build artefact on disk."""
    return Path(__file__).resolve().parent / "static" / "index.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abench-ui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--experiments-dir",
        default="experiments",
        help="path to the experiments/ directory",
    )
    parser.add_argument(
        "--skip-bundle-check",
        action="store_true",
        help="boot without the SPA bundle (API-only mode, for tests)",
    )
    args = parser.parse_args(argv)

    if not args.skip_bundle_check and not _static_index_path().is_file():
        print(
            "abench-ui: SPA bundle not found at abench_ui/static/index.html.\n"
            "Build the frontend first:\n"
            "    cd web && npm install && npm run build\n"
            "Or re-run with --skip-bundle-check for API-only mode.",
            file=sys.stderr,
        )
        return 2

    app = create_app(experiments_dir=Path(args.experiments_dir).resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
```

- [ ] **Step 6: Extend `tests/abench_ui/test_cli.py` with the bundle-check**

Append:

```python
def test_main_returns_2_when_bundle_missing(monkeypatch, capsys, tmp_path):
    """If abench_ui/static/index.html is absent, abench-ui must refuse to start
    and never reach uvicorn.run."""
    from abench_ui import cli

    # Monkeypatch the helper so we don't touch the real bundle on disk.
    monkeypatch.setattr(cli, "_static_index_path", lambda: tmp_path / "missing.html")

    rc = cli.main([])
    assert rc == 2
    assert "SPA bundle not found" in capsys.readouterr().err


def test_main_skips_bundle_check_when_flag_set(monkeypatch, tmp_path):
    """--skip-bundle-check must let main proceed even without a built bundle.
    We swap uvicorn.run for a no-op so the function returns 0 without binding."""
    from abench_ui import cli

    monkeypatch.setattr(cli, "_static_index_path", lambda: tmp_path / "missing.html")
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)

    rc = cli.main([
        "--skip-bundle-check",
        "--experiments-dir", str(tmp_path),
    ])
    assert rc == 0
```

- [ ] **Step 7: Run the full test suite**

```bash
.venv/bin/pytest
```
Expected: all green (106 prior + new tests).

- [ ] **Step 8: Integration smoke (manual)**

```bash
cd web && npm run build
.venv/bin/abench-ui --experiments-dir experiments
```
Open `http://127.0.0.1:8765/` in a browser. Confirm:
- ExperimentList loads at `/`,
- `/experiments/<name>` works on direct visit (SPA fallback),
- WebSocket connection succeeds on a fresh run.

- [ ] **Step 9: Commit**

```bash
git add abench_ui/server.py abench_ui/cli.py \
        tests/abench_ui/test_cli.py tests/abench_ui/test_static.py
git commit -m "feat(ui/server): serve SPA bundle from abench_ui/static with API/WS isolation"
```

---

## Task 8 (optional): Deferred items from Plan A review

These are low-priority items that came out of the Plan A code review. **Do them only if Plan B execution finishes with budget left** — they're independent and each can ship in its own commit.

### Task 8.1: `metrics.json` carries `final_diff_summary`

**Files:**
- Modify: `abench/metrics.py`
- Modify: `tests/test_metrics.py`

The trace already carries `final_diff_summary`; the metrics dict that's persisted to disk does not. UI surfaces (especially MetricsDrawer) would benefit from having it locally.

- [ ] **Step 1: Locate the `extract`/`build_metrics` function in `abench/metrics.py`** that produces the dict written as `metrics.json`. (Grep for the function used by `runner.py` to populate `metrics.json` — likely `extract_metrics` or `build_metrics`.)

- [ ] **Step 2: Write the failing test**

Append to `tests/test_metrics.py`:

```python
def test_metrics_carries_final_diff_summary(...):
    """Whatever signature build_metrics uses — pass a Trace with
    final_diff_summary populated and assert it round-trips into the dict."""
    from abench.trace_model import Trace, FinalDiffSummary, FileChange
    trace = Trace(...)
    trace.final_diff_summary = FinalDiffSummary(
        files=[FileChange(path="a.py", added=3, removed=1)],
        total_added=3, total_removed=1,
    )
    m = build_metrics(trace)  # adjust to the actual function
    assert m["final_diff_summary"]["total_added"] == 3
    assert m["final_diff_summary"]["files"][0]["path"] == "a.py"
```

- [ ] **Step 3: Run test, expect failure**

```bash
.venv/bin/pytest tests/test_metrics.py -v -k final_diff_summary
```

- [ ] **Step 4: Implement**

In the metrics-builder, after copying `verify_*` fields, add:

```python
if trace.final_diff_summary is not None:
    m["final_diff_summary"] = {
        "total_added": trace.final_diff_summary.total_added,
        "total_removed": trace.final_diff_summary.total_removed,
        "files": [
            {"path": f.path, "added": f.added, "removed": f.removed}
            for f in trace.final_diff_summary.files
        ],
    }
```

- [ ] **Step 5: Run test, expect pass + commit**

```bash
.venv/bin/pytest tests/test_metrics.py -v -k final_diff_summary
git add abench/metrics.py tests/test_metrics.py
git commit -m "feat(metrics): persist final_diff_summary in metrics.json"
```

### Task 8.2: API tests for `/api/validate/model` and `/api/providers`

**Files:**
- Create or extend: `tests/abench_ui/test_validate_api.py`
- Create or extend: `tests/abench_ui/test_providers_api.py`

`test_validate.py` and `test_providers.py` already cover the helpers but not the HTTP surface.

- [ ] **Step 1: Write `tests/abench_ui/test_validate_api.py`**

```python
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from abench_ui.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(experiments_dir=tmp_path))


def test_validate_model_available(client):
    with patch("abench_ui.server.validate_model") as v:
        from abench_ui.validate import ValidationResult
        v.return_value = ValidationResult(status="available", provider="openrouter", suggestions=[])
        resp = client.post("/api/validate/model", json={"model": "openrouter/foo"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "available", "provider": "openrouter", "suggestions": []}


def test_validate_model_no_key(client):
    with patch("abench_ui.server.validate_model") as v:
        from abench_ui.validate import ValidationResult
        v.return_value = ValidationResult(status="no_key", provider="openrouter", suggestions=[])
        resp = client.post("/api/validate/model", json={"model": "openrouter/foo"})
    body = resp.json()
    assert body["status"] == "no_key"


def test_validate_model_rejects_empty_body(client):
    resp = client.post("/api/validate/model", json={})
    assert resp.status_code == 422
```

- [ ] **Step 2: Write `tests/abench_ui/test_providers_api.py`**

```python
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from abench_ui.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(experiments_dir=tmp_path))


def test_get_providers(client):
    with patch("abench_ui.server.prov_mod.list_providers") as lp:
        lp.return_value = [{"id": "openrouter", "configured": True}]
        resp = client.get("/api/providers")
    assert resp.status_code == 200
    assert resp.json() == [{"id": "openrouter", "configured": True}]


def test_post_credentials_writes_atomically(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    resp = client.post(
        "/api/providers/openrouter/credentials",
        json={"api_key": "sk-test"},
    )
    assert resp.status_code in (200, 204)
    auth = tmp_path / ".local" / "share" / "opencode" / "auth.json"
    assert auth.is_file()
    assert "sk-test" in auth.read_text()


def test_post_credentials_rejects_empty_key(client):
    resp = client.post(
        "/api/providers/openrouter/credentials",
        json={"api_key": ""},
    )
    assert resp.status_code == 422
```

If the body-shape validation isn't already in `server.py`, add `min_length=1` to `_CredentialsBody.api_key`:

```python
class _CredentialsBody(BaseModel):
    api_key: str = Field(..., min_length=1)
```

- [ ] **Step 3: Run + commit**

```bash
.venv/bin/pytest tests/abench_ui/test_validate_api.py tests/abench_ui/test_providers_api.py -v
git add tests/abench_ui/test_validate_api.py tests/abench_ui/test_providers_api.py abench_ui/server.py
git commit -m "test(ui/server): API surface tests for validate/model + providers"
```

### Task 8.3: e2e WebSocket reconnect test

**Files:**
- Extend: `tests/abench_ui/test_ws_e2e.py`

The current e2e test exercises the happy path. Add a test that simulates a disconnect mid-stream and verifies the second connection's `last_event_id` resumes correctly without duplicate or skipped envelopes.

- [ ] **Step 1: Add the failing test**

Append to `tests/abench_ui/test_ws_e2e.py`:

```python
def test_ws_reconnect_resumes_from_last_event_id(monkeypatch, tmp_path):
    """Disconnect mid-stream → reconnect with last_event_id → no dup, no gap."""
    app = create_app(experiments_dir=tmp_path, client_factory_override=FakeOpenCodeClient.factory(...))
    client = TestClient(app)
    sid = client.post("/api/runs", json={"experiment_name": "exp"}).json()["session_id"]

    received_first: list[dict] = []
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        for _ in range(3):
            received_first.append(ws.receive_json())
        # Close mid-stream.

    last_id = max(e.get("event_id", 0) for e in received_first)
    received_second: list[dict] = []
    with client.websocket_connect(f"/ws/sessions/{sid}?last_event_id={last_id}") as ws:
        try:
            while True:
                env = ws.receive_json(mode="binary" if False else "text")
                received_second.append(env)
                if env["type"] in ("session.finished", "session.error"):
                    break
        except Exception:
            pass

    all_ids = [e["event_id"] for e in received_first + received_second]
    assert all_ids == sorted(set(all_ids)), "duplicate or out-of-order events on reconnect"
    # Last event_id of the second batch must be >= last_id; first event_id > last_id.
    assert received_second[0]["event_id"] > last_id
```

If `FakeOpenCodeClient.factory(...)` doesn't match the existing test seam, adapt to whatever pattern `test_ws_e2e.py` already uses (read the file first; mirror the setup).

- [ ] **Step 2: Run, fix, commit**

```bash
.venv/bin/pytest tests/abench_ui/test_ws_e2e.py::test_ws_reconnect_resumes_from_last_event_id -v
git add tests/abench_ui/test_ws_e2e.py
git commit -m "test(ui/server): e2e WS reconnect resume with last_event_id"
```

### Task 8.4: `target_methods` greppable validation

**Files:**
- Modify: `abench/config.py` (`_validate` function)
- Modify: `tests/test_config.py`

Currently `target_methods` is plain `list[str]`; spec §8 requires each name to be greppable in `target_file` with a language-aware regex (Java/Python in v1).

- [ ] **Step 1: Add the failing test**

```python
def test_target_methods_must_be_greppable_in_target_file(tmp_path):
    _scaffold(tmp_path)
    yaml_path = tmp_path / "exp.yaml"
    # target_file = a.py exists from _scaffold; a.py contains def foo
    yaml_path.write_text(yaml_path.read_text() + "\ntarget_file: a.py\ntarget_methods: [foo, bogus]\n")
    with pytest.raises(ValueError, match="bogus"):
        load_experiment(yaml_path)
```

(Adjust the fixture so `a.py` contains a `def foo` line.)

- [ ] **Step 2: Implement in `_validate`**

```python
if exp.target_file and exp.target_methods:
    text = (exp.fixture_path / exp.target_file).read_text()
    if exp.target_file.endswith(".py"):
        pat = lambda m: re.compile(rf"^\s*def\s+{re.escape(m)}\s*\(", re.M)
    elif exp.target_file.endswith(".java"):
        pat = lambda m: re.compile(rf"\b{re.escape(m)}\s*\(", re.M)
    else:
        pat = lambda m: re.compile(rf"\b{re.escape(m)}\b", re.M)
    missing = [m for m in exp.target_methods if not pat(m).search(text)]
    if missing:
        raise ValueError(f"target_methods not found in {exp.target_file}: {missing}")
```

Add `import re` at the top if not already present.

- [ ] **Step 3: Run, commit**

```bash
.venv/bin/pytest tests/test_config.py -v -k target_methods
git add abench/config.py tests/test_config.py
git commit -m "feat(config): grep-validate target_methods against target_file"
```

### Task 8.5: `verify_output.log` on verify_status=error

**Files:**
- Modify: `abench/verify.py` (or wherever `run_verify` lives)
- Modify: `abench/runner.py` (write the log alongside the rep)
- Modify: existing verify test

Per spec §12: when verify parser fails, raw stdout/stderr must land in `verify_output.log` next to the rep's artefacts. The dataclass already carries `raw_output`; we just need to persist it.

- [ ] **Step 1: Add the failing test**

In an existing verify test (or a new one), have `detect_command`/`run_verify` return a `VerifyResult` with `status="error"` and assert that after the rep, `<rundir>/verify_output.log` contains the raw output.

- [ ] **Step 2: Implement in `runner.py`**

After step 6 in `_run_one`, when `verify_result.status == "error"` (or `"timeout"`), write:

```python
(rundir / "verify_output.log").write_text(verify_result.raw_output or "")
```

- [ ] **Step 3: Run, commit**

```bash
.venv/bin/pytest tests/ -v -k verify_output_log
git add abench/runner.py tests/
git commit -m "feat(verify): persist verify_output.log on error/timeout"
```

---

## Self-Review

Before declaring the plan finished, the writer ran this self-review against spec §7, §6, §10:

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| §7.1 ExperimentList | Task 3 |
| §7.2 ExperimentEdit form | Task 4a (rjsf form) |
| §7.2 right panel | Task 4b (validation/plan/fixtures/previous runs) |
| §7.2 model validation chip + key dialog | Task 4c |
| §7.2 target_methods chip-list | Task 4d |
| §7.2 augmentation textarea | Task 4e |
| §7.3 Run progress + verify chips + isolation chip | Task 5b |
| §7.3 sidebar per-rep cards | Task 5c |
| §7.3 live ReAct stream grouped by turn | Task 5d |
| §7.3 → on finish navigate to TraceView | Task 5e |
| §7.4 verdict banner | Task 6a |
| §7.4 aggregate stats bar | Task 6a |
| §7.4 turn timeline (1 turn = 1 messageID) | Task 6b |
| §7.4 show raw toggle | Task 6b |
| §7.4 verify card | Task 6c |
| §7.4 final diff card | Task 6d |
| §7.4 method comparison card | Task 6e |
| §7.4 metrics drawer | Task 6f |
| §7.4 footer nav | Task 6g |
| §6 REST + WS contract | Task 1 (REST hooks) + Task 5a (WS hook) |
| §6 WS reconnect with last_event_id | Task 5a + optional Task 8.3 |
| §10 isolation chip | Task 5b (IsolationChip) |
| §3 single-process serving | Task 7 |

**Placeholder scan:** No `TBD`, `TODO: implement later`, or "similar to Task N" placeholders. Each step shows the code it produces. The only intentional handoff is the **navigation-on-finish note** in Task 5b, which is then resolved in Task 5e (caller passes `experimentName` via router state).

**Type/method-name consistency:**

- `Envelope` union (Task 5a) → consumed by `useRunSession` (Task 5a) → consumed by `EventStream` and `RunSidebar` (Task 5c/5d) — type names match.
- `TurnGroup` (Task 5d) → consumed by `TurnCard` (Task 6b) — same field names (`messageId`, `parts`, `reason`, `tokensIn`, …).
- `Trace` (Task 1) → consumed by `VerdictBanner`, `VerifyCard`, `AggregateStatsBar`, `MethodComparisonCard` — field names match `abench/trace_model.py` JSON (snake_case).
- `MethodComparison` (Task 1) → consumed by `MethodComparisonCard` (Task 6e) — field names `original_lines`, `regen_lines`, `equivalent` match the backend response from `abench_ui/runs.py:method_comparison`.
- `useEvents` (Task 6b) → `events.jsonl` is text/plain; the hook parses it line-by-line into `unknown[]`. Backend route returns JSONL — verified against `runs.py`.

**Sanity-checked open items:**

- The Run page assumes `total_runs` evenly divides among `conditions` to derive `totalReps`. This holds because `compute_plan` in `run_session.py` uses `reps_per_condition` × `conditions`. If a future change breaks evenness, RunSidebar would under-count — flag for the executing engineer to read `session.started.conditions` and accept overflow.
- ModelValidationChip uses `useValidateModel` (a mutation) inside a debounced effect. This is intentional: the endpoint is POST (TTL cache lives server-side), and we want imperative control, not a `useQuery`.

---

## Execution Handoff

Plan complete and saved to [`docs/superpowers/plans/2026-05-29-web-ui-frontend.md`](2026-05-29-web-ui-frontend.md).

**Recommended approach: Subagent-Driven (mirrors Plan A).** Dispatch a fresh subagent per task (0, 1, 2, 3, 4a-f, 5a-e, 6a-g, 7), review between tasks, and only pick up Task 8.x items if budget remains after Task 7 is green end-to-end.

**Alternative: Inline Execution.** Execute tasks in this session using superpowers:executing-plans with checkpoints. Slower, but useful if you want to keep cross-task context warm (e.g. for the rjsf-mui widget registration that touches multiple files).




