import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

vi.mock("@/lib/env", () => ({
  getApiUrl: () => "http://localhost:8000/api/v1",
}));

describe("apiGet", () => {
  it("usa la URL base de NEXT_PUBLIC_API_URL", async () => {
    const { apiGet } = await import("@/lib/api");
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ data: "test" }),
    });

    await apiGet("/test");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/test",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("convierte error 4xx en ApiError con detail y status", async () => {
    const { apiGet, ApiError } = await import("@/lib/api");
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Instrumento no encontrado" }),
    });

    await expect(apiGet("/test")).rejects.toThrow(ApiError);
    await expect(apiGet("/test")).rejects.toMatchObject({
      status: 404,
      detail: "Instrumento no encontrado",
    });
  });

  it("convierte error 5xx en ApiError con detail y status", async () => {
    const { apiGet, ApiError } = await import("@/lib/api");
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Error interno del servidor" }),
    });

    await expect(apiGet("/test")).rejects.toThrow(ApiError);
    await expect(apiGet("/test")).rejects.toMatchObject({
      status: 500,
      detail: "Error interno del servidor",
    });
  });

  it("error de red lanza ApiError con mensaje en español", async () => {
    const { apiGet, ApiError } = await import("@/lib/api");
    mockFetch.mockRejectedValue(new Error("Failed to fetch"));

    await expect(apiGet("/test")).rejects.toThrow(ApiError);
    await expect(apiGet("/test")).rejects.toMatchObject({
      status: 0,
      detail: "Error de red: no se pudo conectar con el servidor",
    });
  });

  it("devuelve JSON en caso de éxito", async () => {
    const { apiGet } = await import("@/lib/api");
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ result: "ok" }),
    });

    const data = await apiGet("/test");
    expect(data).toEqual({ result: "ok" });
  });
});