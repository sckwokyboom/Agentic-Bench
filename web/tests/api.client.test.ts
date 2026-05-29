import { describe, it, expect } from "vitest";
import { mswServer } from "./setup";
import { http, HttpResponse } from "msw";
import { apiGet, apiPut, apiPutText, apiPostJson, apiDelete, ApiError } from "../src/api/client";

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

  it("apiPut sends JSON body and gets length back", async () => {
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

  it("apiGet returns text for non-JSON 2xx", async () => {
    mswServer.use(http.get("/api/raw", () =>
      new HttpResponse("hello world", { headers: { "content-type": "text/plain" } })));
    expect(await apiGet<string>("/api/raw")).toBe("hello world");
  });

  it("apiDelete returns undefined on 204 No Content", async () => {
    mswServer.use(http.delete("/api/empty", () =>
      new HttpResponse(null, { status: 204 })));
    expect(await apiDelete("/api/empty")).toBeUndefined();
  });

  it("apiPutText sends text/plain body and parses JSON response", async () => {
    mswServer.use(http.put("/api/text", async ({ request }) => {
      expect(request.headers.get("content-type")).toContain("text/plain");
      const body = await request.text();
      return HttpResponse.json({ echoed: body });
    }));
    expect(await apiPutText<{ echoed: string }>("/api/text", "raw text"))
      .toEqual({ echoed: "raw text" });
  });
});
