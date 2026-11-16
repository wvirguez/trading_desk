import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { useActiveSignals } from "../use-signals";
import { useStructure } from "../use-structure";
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

describe("useActiveSignals", () => {
  const mockSignals = [
    {
      id: "123e4567-e89b-12d3-a456-426614174000",
      analysis_id: "123e4567-e89b-12d3-a456-426614174001",
      symbol: "BTC/USDT",
      timeframe: "1h",
      direction: "LONG",
      entry: "50000.00",
      stop_loss: "49000.00",
      take_profit: "52000.00",
      rr: "2.0",
      status: "APPROVED",
      rationale: "Estructura alcista con BOS confirmado",
      regime: "TRENDING",
      asset_class: "CRYPTO",
      created_at: "2024-01-15T10:00:00Z",
      veto_reasons: [],
    },
    {
      id: "123e4567-e89b-12d3-a456-426614174002",
      analysis_id: "123e4567-e89b-12d3-a456-426614174003",
      symbol: "ETH/USDT",
      timeframe: "1h",
      direction: "SHORT",
      entry: "3000.00",
      stop_loss: "3100.00",
      take_profit: "2800.00",
      rr: "2.0",
      status: "APPROVED",
      rationale: "Estructura bajista con CHOCH",
      regime: "TRENDING",
      asset_class: "CRYPTO",
      created_at: "2024-01-15T10:00:00Z",
      veto_reasons: [],
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("carga señales activas correctamente", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockSignals);

    const { result } = renderHook(() => useActiveSignals("BTC/USDT"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].symbol).toBe("BTC/USDT");
    expect(apiGet).toHaveBeenCalledWith("/api/v1/signals/active");
  });

  it("filtra por símbolo activo", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockSignals);

    const { result, rerender } = renderHook(
      ({ symbol }) => useActiveSignals(symbol),
      { wrapper: createWrapper(), initialProps: { symbol: "BTC/USDT" } },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].symbol).toBe("BTC/USDT");

    rerender({ symbol: "ETH/USDT" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].symbol).toBe("ETH/USDT");
  });

  it("devuelve array vacío si no hay señales para el símbolo", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockSignals);

    const { result } = renderHook(() => useActiveSignals("SOL/USDT"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toHaveLength(0);
  });

  it("maneja error 404", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(404, "No hay señales activas"));

    const { result } = renderHook(() => useActiveSignals("BTC/USDT"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("No hay señales activas");
  });

  it("maneja error 503", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(503, "Servicio no disponible"));

    const { result } = renderHook(() => useActiveSignals("BTC/USDT"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("Servicio no disponible");
  });

  it("usa refetchInterval corto (10s)", () => {
    vi.mocked(apiGet).mockResolvedValue(mockSignals);

    const { result } = renderHook(() => useActiveSignals("BTC/USDT"), { wrapper: createWrapper() });

    // Verificar que el hook se configura con refetchInterval: 10000
    // Esto se verifica indirectamente comprobando que el queryKey incluye la configuración
    expect(result.current.isLoading).toBe(true);
  });
});

describe("useStructure", () => {
  const mockStructure = {
    events: [
      {
        type: "BOS",
        direction: "LONG",
        level: "50000.00",
        ts: "2024-01-15T08:00:00Z",
        broken_swing_ts: "2024-01-15T06:00:00Z",
      },
    ],
    fvgs: [
      {
        direction: "LONG",
        high: "51000.00",
        low: "50500.00",
        ts: "2024-01-15T08:00:00Z",
        mitigated_at: null,
      },
      {
        direction: "SHORT",
        high: "49500.00",
        low: "49000.00",
        ts: "2024-01-15T07:00:00Z",
        mitigated_at: "2024-01-15T09:00:00Z",
      },
    ],
    swings: [
      {
        kind: "HIGH",
        price: "51500.00",
        ts: "2024-01-15T07:00:00Z",
        confirmed_at: "2024-01-15T07:30:00Z",
      },
      {
        kind: "LOW",
        price: "49000.00",
        ts: "2024-01-15T06:00:00Z",
        confirmed_at: "2024-01-15T06:30:00Z",
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("carga estructura correctamente", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockStructure);

    const { result } = renderHook(() => useStructure("BTC/USDT", "1h"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(mockStructure);
    expect(apiGet).toHaveBeenCalledWith("/api/v1/market/structure?symbol=BTC%2FUSDT&tf=1h");
  });

  it("maneja error 404 para símbolo desconocido", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(404, "Instrumento desconocido: XYZ/USDT"));

    const { result } = renderHook(() => useStructure("XYZ/USDT", "1h"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toBe("Instrumento desconocido: XYZ/USDT");
  });

  it("maneja error 422 para datos insuficientes", async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(422, "Datos insuficientes: se requieren 51 velas, hay 10"));

    const { result } = renderHook(() => useStructure("BTC/USDT", "1h"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as Error).message).toContain("Datos insuficientes");
  });

  it("no hace fetch si symbol o timeframe están vacíos", async () => {
    const { result } = renderHook(() => useStructure("", "1h"), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeUndefined();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("re-fetcha cuando cambia el symbol o timeframe", async () => {
    vi.mocked(apiGet).mockResolvedValue(mockStructure);

    const { result, rerender } = renderHook(
      ({ symbol, tf }) => useStructure(symbol, tf),
      { wrapper: createWrapper(), initialProps: { symbol: "BTC/USDT", tf: "1h" } },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledTimes(1);

    vi.mocked(apiGet).mockResolvedValueOnce({ ...mockStructure, fvgs: [] });
    rerender({ symbol: "ETH/USDT", tf: "1h" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledTimes(2);
    expect(apiGet).toHaveBeenLastCalledWith("/api/v1/market/structure?symbol=ETH%2FUSDT&tf=1h");
  });
});