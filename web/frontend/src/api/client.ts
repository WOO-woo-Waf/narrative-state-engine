export class ApiError extends Error {
  status: number;
  payload: unknown;
  endpoint: string;

  constructor(message: string, status: number, payload: unknown, endpoint: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.endpoint = endpoint;
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null | string[]>;

function buildUrl(path: string, params?: QueryParams): string {
  const url = path.startsWith("/api") ? path : `/api${path}`;
  if (!params) return url;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (Array.isArray(value)) {
      if (value.length) search.set(key, value.join(","));
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `${url}?${query}` : url;
}

async function parseResponse<T>(response: Response, endpoint: string): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" && payload && "detail" in payload ? String((payload as { detail?: unknown }).detail) : response.statusText;
    throw new ApiError(message, response.status, payload, endpoint);
  }
  return payload as T;
}

export async function apiGet<T>(path: string, params?: QueryParams, init?: RequestInit): Promise<T> {
  const endpoint = buildUrl(path, params);
  const response = await fetch(endpoint, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers }
  });
  return parseResponse<T>(response, endpoint);
}

export async function apiPost<T>(path: string, body?: unknown, params?: QueryParams, init?: RequestInit): Promise<T> {
  const endpoint = buildUrl(path, params);
  const response = await fetch(endpoint, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...init?.headers
    }
  });
  return parseResponse<T>(response, endpoint);
}

export async function apiPatch<T>(path: string, body?: unknown, params?: QueryParams, init?: RequestInit): Promise<T> {
  const endpoint = buildUrl(path, params);
  const response = await fetch(endpoint, {
    method: "PATCH",
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...init?.headers
    }
  });
  return parseResponse<T>(response, endpoint);
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const payload = typeof error.payload === "string" ? error.payload : JSON.stringify(error.payload, null, 2);
    return `${error.endpoint}\nHTTP ${error.status}\n${error.message}${payload && payload !== `"${error.message}"` ? `\n${payload}` : ""}`;
  }
  return error instanceof Error ? error.message : String(error || "未知错误");
}

export async function apiGetOr<T>(path: string, fallback: T, params?: QueryParams): Promise<T> {
  try {
    return await apiGet<T>(path, params);
  } catch (error) {
    if (error instanceof ApiError && [404, 405, 501].includes(error.status)) return fallback;
    throw error;
  }
}
