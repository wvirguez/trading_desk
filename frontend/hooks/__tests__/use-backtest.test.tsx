import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useBacktest } from "../use-backtest";
import type { components } from "@/types/api";

vi.mock("@/lib/env", () => ({ getApiUrl: () => "http://localhost:8000" }));

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});
afterEach(() => vi.unstubAllGlobals());

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CONFIG: components["schemas"]["BacktestConfig-Input"] = {
  symbol: "BTC/USDT",
  timeframe: "1h",
  initial_capital: "10000",
  zscore_window: 50,
  entry_z: 2,
  exit_z: 0,
  allow_short: true,
};

describe("useBacktest", () => {
  it("hace POST a /quant/backtest con el BacktestConfig y entrega las métricas", async () => {
    const metrics = { n_bars: 100, n_trades: 3, warnings: [], equity_curve: [] };
    mockFetch.mockResolvedValue({ ok: true, json: async () => metrics });
    const { result } = renderHook(() => useBacktest(), { wrapper });

    let data: unknown;
    await act(async () => {
      data = await result.current.mutateAsync(CONFIG);
    });

    expect(data).toEqual(metrics);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/quant/backtest");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(CONFIG);
  });

  it.each([
    [404, "Instrumento XYZ/USDT no encontrado"],
    [422, "Datos insuficientes: se requieren al menos 60 barras"],
  ])("un %i devuelve el detail exacto", async (status, detail) => {
    mockFetch.mockResolvedValue({ ok: false, status, json: async () => ({ detail }) });
    const { result } = renderHook(() => useBacktest(), { wrapper });

    await act(async () => {
      await expect(result.current.mutateAsync(CONFIG)).rejects.toMatchObject({ status, detail });
    });
  });
});
