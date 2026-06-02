import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { mswServer } from "./setup";
import {
  loadSchema, _resetSchemaCache, collapseNullable,
} from "../src/api/schemaCache";

describe("collapseNullable", () => {
  it("collapses { anyOf: [string, null] } to a plain string, preserving title", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "string" }, { type: "null" }], title: "Command" }),
    ).toEqual({ type: "string", title: "Command" });
  });

  it("collapses the reverse order [null, string] too", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "null" }, { type: "string" }], default: null }),
    ).toEqual({ type: "string", default: null });
  });

  it("collapses { anyOf: [integer, null] } to a plain integer, preserving title", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "integer" }, { type: "null" }], title: "Reps" }),
    ).toEqual({ type: "integer", title: "Reps" });
  });

  it("collapses the reverse order [null, integer] too", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "null" }, { type: "integer" }] }),
    ).toEqual({ type: "integer" });
  });

  it("preserves the non-null branch's own constraints (enum)", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "string", enum: ["a", "b"] }, { type: "null" }] }),
    ).toEqual({ type: "string", enum: ["a", "b"] });
  });

  it("lets the parent's sibling keys win over the non-null branch", () => {
    expect(
      collapseNullable({ anyOf: [{ type: "string" }, { type: "null" }], description: "D" }),
    ).toEqual({ type: "string", description: "D" });
  });

  it("leaves a genuine (non-nullable) anyOf unchanged", () => {
    const node = { anyOf: [{ type: "string" }, { type: "number" }], title: "Mixed" };
    expect(collapseNullable(node)).toEqual(node);
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
    expect(collapseNullable(input)).toEqual({
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

  it("collapses a nullable integer nested under properties", () => {
    const input = {
      type: "object",
      properties: {
        x: { anyOf: [{ type: "integer" }, { type: "null" }] },
      },
    };
    expect(collapseNullable(input)).toEqual({
      type: "object",
      properties: {
        x: { type: "integer" },
      },
    });
  });

  it("recurses through arrays", () => {
    expect(
      collapseNullable([
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

  it("collapses nullable anyOf in the fetched schema before caching", async () => {
    mswServer.use(http.get("/api/schema", () =>
      HttpResponse.json({
        type: "object",
        properties: {
          verify: {
            properties: {
              command: { anyOf: [{ type: "string" }, { type: "null" }], title: "Command" },
              reps: { anyOf: [{ type: "integer" }, { type: "null" }], title: "Reps" },
            },
          },
        },
      }),
    ));
    const s = await loadSchema();
    const props = s.properties as {
      verify: { properties: { command: unknown; reps: unknown } };
    };
    expect(props.verify.properties.command).toEqual({ type: "string", title: "Command" });
    expect(props.verify.properties.reps).toEqual({ type: "integer", title: "Reps" });
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
