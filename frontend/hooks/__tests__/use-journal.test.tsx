import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useJournal } from "../use-journal";

vi.mock("@/lib/env", () => ({ getApiUrl: () => "http://localhost:8000" }));

const mockFetch = vi.fn();
beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});
afterEach(() => vi.unstubAllGlobals());

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
}

describe("useJournal", () => {
  it("pide /journal con symbol y limit", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ entries: [], summary: {} }) });
    const { result } = renderHook(() => useJournal("BTC/USDT", 50), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/journal?symbol=BTC%2FUSDT&limit=50",
      expect.anything(),
    );
  });

  it("omite symbol si no hay filtro", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ entries: [], summary: {} }) });
    const { result } = renderHook(() => useJournal(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockFetch.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/journal?limit=100");
  });

  it("un 404 devuelve el detail exacto", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Instrumento XYZ desconocido" }),
    });
    const { result } = renderHook(() => useJournal("XYZ"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.detail).toBe("Instrumento XYZ desconocido");
    expect(result.current.error?.status).toBe(404);
  });
});
