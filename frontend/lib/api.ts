"use client";

import { getApiUrl } from "./env";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const baseUrl = getApiUrl();
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(0, "Error de red: no se pudo conectar con el servidor");
  }

  if (!response.ok) {
    let detail = `Error HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string" && data.detail) {
        detail = data.detail;
      }
    } catch {
      // Ignorar errores de parsing JSON
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("POST", path, body);
}
