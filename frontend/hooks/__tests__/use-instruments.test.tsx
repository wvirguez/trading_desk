import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { useInstruments } from "../use-instruments";
import { useOhlcv } from "../use-ohlcv";
import { apiGet, ApiError } from "@/lib/api";

vi.mock("@/lib/api", () => {
  class MockApiError extends Error {
    public readonly status: number;
    public readonly detail: string;
    constructor(status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  }
  return {
    apiGet: vi.fn(),
    ApiError: MockApiError,
  };
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
};

describe("useInstruments", () => {
  const mockInstruments = [
    {
      symbol: "BTC/USDT",
      base_currency: "BTC",
      quote_currency: "USDT",
      asset_class: "CRYPTO",
      provider: "BINANCE",
      provider_symbol: "BTCUSDT",
      tick_size: "0.01",
      lot_size: "0.00001",
      session: "CRYPTO_24_7",
    },
    {
      symbol: "ETH/USDT",
      base_currency: "ETH",
      quote_currency: "USDT",
      asset_class: "CRYPTO",
      provider: "BINANCE",
      provider_symbol: "ETHUSDT",
      tick_size: "0.01",
      lot_size: "0.0001",
      session: "CRYPTO_24_7",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("carga instrumentos correctamente", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockInstruments);

    const { result } = renderHook(() => useInstruments(), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(mockInstruments);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/market/instruments");
  });

  it("maneja error 404", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(404, "Instrumento no encontrado"));

    const { result } = renderHook(() => useInstruments(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as Error).message).toBe("Instrumento no encontrado");
  });

  it("maneja error 503", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(503, "Servicio no disponible"));

    const { result } = renderHook(() => useInstruments(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("Servicio no disponible");
  });

  it("maneja error de red", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(0, "Error de red: no se pudo conectar con el servidor"));

    const { result } = renderHook(() => useInstruments(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain("Error de red");
  });
});

describe("useOhlcv", () => {
  const mockCandles = [
    {
      ts: "2024-01-01T00:00:00Z",
      open: "100.0",
      high: "105.0",
      low: "99.0",
      close: "103.0",
      volume: "1000",
      symbol: "BTC/USDT",
      timeframe: "1h",
    },
    {
      ts: "2024-01-01T01:00:00Z",
      open: "103.0",
      high: "108.0",
      low: "102.0",
      close: "106.0",
      volume: "1100",
      symbol: "BTC/USDT",
      timeframe: "1h",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("carga velas correctamente con symbol y timeframe", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockCandles);

    const { result } = renderHook(() => useOhlcv("BTC/USDT", "1h"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(mockCandles);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/market/ohlcv?symbol=BTC%2FUSDT&tf=1h&limit=500");
  });

  it("maneja error 404 para símbolo desconocido", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(404, "Instrumento no encontrado"));

    const { result } = renderHook(() => useOhlcv("UNKNOWN/USDT", "1h"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("Instrumento no encontrado");
  });

  it("maneja error 422 para datos insuficientes", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(422, "Datos insuficientes: se requieren 51 velas, hay 10"));

    const { result } = renderHook(() => useOhlcv("BTC/USDT", "1h"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain("Datos insuficientes");
  });

  it("maneja error 503", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(503, "Servicio no disponible"));

    const { result } = renderHook(() => useOhlcv("BTC/USDT", "1h"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("Servicio no disponible");
  });

  it("no hace fetch si symbol o timeframe están vacíos", async () => {
    const { result } = renderHook(() => useOhlcv("", "1h"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeUndefined();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("re-fetcha cuando cambia el symbol o timeframe", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockCandles);

    const { result, rerender } = renderHook(
      ({ symbol, tf }) => useOhlcv(symbol, tf),
      { wrapper: createWrapper(), initialProps: { symbol: "BTC/USDT", tf: "1h" } },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledTimes(1);

    vi.mocked(apiGet).mockResolvedValueOnce([]);
    rerender({ symbol: "ETH/USDT", tf: "1h" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledTimes(2);
    expect(apiGet).toHaveBeenLastCalledWith("/api/v1/market/ohlcv?symbol=ETH%2FUSDT&tf=1h&limit=500");
  });
});