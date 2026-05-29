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
