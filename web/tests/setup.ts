import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

// The global ActiveRunsBanner polls /api/sessions on every page. Default it to
// "no active runs" so tests that render <App> don't trip onUnhandledRequest;
// per-test handlers (mswServer.use) still override this.
export const mswServer = setupServer(
  http.get("/api/sessions", () => HttpResponse.json([])),
);

beforeAll(() => mswServer.listen({ onUnhandledRequest: "error" }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());
