import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import {
  loadSchema, _resetSchemaCache, collapseNullableStrings,
} from "../src/api/schemaCache";

describe("collapseNullableStrings", () => {
  it("collapses { anyOf: [string, null] } to a plain string, preserving title", () => {
    expect(
      collapseNullableStrings({ anyOf: [{ type: "string" }, { type: "null" }], title: "Command" }),
    ).toEqual({ type: "string", title: "Command" });
  });

  it("collapses the reverse order [null, string] too", () => {
    expect(
      collapseNullableStrings({ anyOf: [{ type: "null" }, { type: "string" }], default: null }),
    ).toEqual({ type: "string", default: null });
  });

  it("leaves a genuine (non-nullable) anyOf unchanged", () => {
    const node = { anyOf: [{ type: "string" }, { type: "number" }], title: "Mixed" };
    expect(collapseNullableStrings(node)).toEqual(node);
  });

  it("recurses into nested properties", () => {
    const input = {
      type: "object",
      properties: {
        verify: {
          type: "object",
          properties: {
            command: { anyOf: [{ type: "string" }, { type: "null" }], title: "Command" },
          },
        },
      },
    };
    expect(collapseNullableStrings(input)).toEqual({
      type: "object",
      properties: {
        verify: {
          type: "object",
          properties: {
            command: { type: "string", title: "Command" },
          },
        },
      },
    });
  });

  it("recurses through arrays", () => {
    expect(
      collapseNullableStrings([
        { anyOf: [{ type: "string" }, { type: "null" }] },
        { type: "integer" },
      ]),
    ).toEqual([{ type: "string" }, { type: "integer" }]);
  });
});

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

  it("collapses nullable-string anyOf in the fetched schema before caching", async () => {
    mswServer.use(http.get("/api/schema", () =>
      HttpResponse.json({
        type: "object",
        properties: {
          verify: {
            properties: {
              command: { anyOf: [{ type: "string" }, { type: "null" }], title: "Command" },
            },
          },
        },
      }),
    ));
    const s = await loadSchema();
    const props = s.properties as { verify: { properties: { command: unknown } } };
    expect(props.verify.properties.command).toEqual({ type: "string", title: "Command" });
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
