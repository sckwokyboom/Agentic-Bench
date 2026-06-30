import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

// Node's experimental global `localStorage` (the "--localstorage-file" warning)
// shadows jsdom's with a stub whose methods throw. Components use bare
// `localStorage` (fine in a real browser), so install a working in-memory Storage
// for tests and reset it per-test.
class MemStorage implements Storage {
  private m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
}
Object.defineProperty(globalThis, "localStorage", {
  value: new MemStorage(), configurable: true, writable: true,
});

// The global ActiveRunsBanner polls /api/sessions on every page. Default it to
// "no active runs" so tests that render <App> don't trip onUnhandledRequest;
// per-test handlers (mswServer.use) still override this.
export const mswServer = setupServer(
  http.get("/api/sessions", () => HttpResponse.json([])),
);

beforeAll(() => mswServer.listen({ onUnhandledRequest: "error" }));
afterEach(() => { mswServer.resetHandlers(); localStorage.clear(); });
afterAll(() => mswServer.close());
