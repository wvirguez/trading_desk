"use client";

/**
 * Lee y valida las variables de entorno del frontend.
 * Falla rápido con mensaje en español si la URL no es válida.
 */

function isValidUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" || parsed.protocol === "ws:" || parsed.protocol === "wss:";
  } catch {
    return false;
  }
}

function normalizeUrl(url: string): string {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

export function getApiUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
  const normalized = normalizeUrl(raw);
  if (!isValidUrl(normalized)) {
    throw new Error(`NEXT_PUBLIC_API_URL inválida: "${raw}". Debe ser una URL http(s) válida.`);
  }
  return normalized;
}

export function getWsUrl(): string {
  const raw = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1/ws";
  const normalized = normalizeUrl(raw);
  if (!isValidUrl(normalized)) {
    throw new Error(`NEXT_PUBLIC_WS_URL inválida: "${raw}". Debe ser una URL ws(s) válida.`);
  }
  return normalized;
}

export const apiUrl = getApiUrl();
export const wsUrl = getWsUrl();