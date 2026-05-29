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
