import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("next/dist/build/webpack/loaders/next-client-pages-loader", () => ({}));

describe("lib/env", () => {
  const originalEnv = process.env;

  beforeEach(() => {
    vi.resetModules();
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_WS_URL;
  });

  it("usa valores por defecto de desarrollo cuando no hay variables", async () => {
    const { apiUrl, wsUrl } = await import("../env");
    expect(apiUrl).toBe("http://localhost:8000");
    expect(wsUrl).toBe("ws://localhost:8000/api/v1/ws");
  });

  it("normaliza la URL eliminando la barra final", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000/";
    process.env.NEXT_PUBLIC_WS_URL = "ws://localhost:8000/api/v1/ws/";
    const { apiUrl, wsUrl } = await import("../env");
    expect(apiUrl).toBe("http://localhost:8000");
    expect(wsUrl).toBe("ws://localhost:8000/api/v1/ws");
  });

  it("falla con mensaje en español si NEXT_PUBLIC_API_URL no es válida", async () => {
    process.env.NEXT_PUBLIC_API_URL = "no-es-una-url";
    await expect(import("../env")).rejects.toThrow('NEXT_PUBLIC_API_URL inválida: "no-es-una-url"');
  });

  it("falla con mensaje en español si NEXT_PUBLIC_WS_URL no es válida", async () => {
    process.env.NEXT_PUBLIC_WS_URL = "no-es-una-url";
    await expect(import("../env")).rejects.toThrow('NEXT_PUBLIC_WS_URL inválida: "no-es-una-url"');
  });

  it("acepta URLs http y https para API", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com/v1";
    const { apiUrl } = await import("../env");
    expect(apiUrl).toBe("https://api.example.com/v1");
  });

  it("acepta URLs ws y wss para WebSocket", async () => {
    process.env.NEXT_PUBLIC_WS_URL = "wss://ws.example.com/ws";
    const { wsUrl } = await import("../env");
    expect(wsUrl).toBe("wss://ws.example.com/ws");
  });
});