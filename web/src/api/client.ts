export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.name = "ApiError";
    // Required for `instanceof ApiError` to work reliably when `extends Error`
    // is targeted to ES2015+ output.
    Object.setPrototypeOf(this, ApiError.prototype);
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
