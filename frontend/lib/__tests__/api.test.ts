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
  getApiUrl: () => "http://localhost:8000",
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
      "http://localhost:8000/test",
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
describe("apiPost", () => {
  it("envía el cuerpo JSON con método POST", async () => {
    const { apiPost } = await import("@/lib/api");
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });

    const data = await apiPost("/test", { a: 1 });

    expect(data).toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/test",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ a: 1 }),
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("sin cuerpo no envía body", async () => {
    const { apiPost } = await import("@/lib/api");
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({}) });

    await apiPost("/test");

    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("convierte 4xx y 5xx en ApiError con el detail exacto", async () => {
    const { apiPost, ApiError } = await import("@/lib/api");
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Señal ya ejecutada" }),
    });
    await expect(apiPost("/test")).rejects.toMatchObject({ status: 409, detail: "Señal ya ejecutada" });

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Servicio no disponible" }),
    });
    const error = await apiPost("/test").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503, detail: "Servicio no disponible" });
  });

  it("usa un mensaje genérico si el error no trae detail", async () => {
    const { apiPost } = await import("@/lib/api");
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("no json");
      },
    });
    await expect(apiPost("/test")).rejects.toMatchObject({ status: 500, detail: "Error HTTP 500" });
  });

  it("error de red lanza ApiError con mensaje en español", async () => {
    const { apiPost } = await import("@/lib/api");
    mockFetch.mockRejectedValue(new Error("Failed to fetch"));
    await expect(apiPost("/test")).rejects.toMatchObject({
      status: 0,
      detail: "Error de red: no se pudo conectar con el servidor",
    });
  });
});
