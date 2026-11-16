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

export async function apiGet<T>(path: string): Promise<T> {
  const baseUrl = getApiUrl();
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
    });
  } catch {
    throw new ApiError(0, "Error de red: no se pudo conectar con el servidor");
  }

  if (!response.ok) {
    let detail = `Error HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data.detail) {
        detail = data.detail;
      }
    } catch {
      // Ignorar errores de parsing JSON
    }
    throw new ApiError(response.status, detail);
  }

  return response.json();
}