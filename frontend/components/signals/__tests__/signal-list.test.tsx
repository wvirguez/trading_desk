import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { SignalList } from "@/components/signals/signal-list";
import { apiPost, ApiError } from "@/lib/api";
import type { components } from "@/types/api";

vi.mock("@/lib/api", () => {
  class MockApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly detail: string,
    ) {
      super(detail);
    }
  }
  return { apiGet: vi.fn(), apiPost: vi.fn(), ApiError: MockApiError };
});

type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];
type MarketStructureResult = components["schemas"]["MarketStructureResult"];

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

describe("SignalList", () => {
  const mockSignal: TradeSignalSchema = {
    id: "123e4567-e89b-12d3-a456-426614174000",
    analysis_id: "123e4567-e89b-12d3-a456-426614174001",
    symbol: "BTC/USDT",
    timeframe: "1h",
    direction: "LONG",
    entry: "50000.00",
    stop_loss: "49000.00",
    take_profit: "52000.00",
    rr: "2.5",
    status: "APPROVED",
    rationale: "Estructura alcista con BOS confirmado en 4h",
    regime: "TRENDING",
    asset_class: "CRYPTO",
    created_at: "2024-01-15T10:00:00Z",
    veto_reasons: [],
    size: {
      notional: "1000.00",
      risk_amount: "100.00",
      risk_pct: "1.0",
      stop_distance: "1000.00",
      units: "0.02",
    },
  };

  const mockStructure: MarketStructureResult = {
    events: [],
    fvgs: [
      { direction: "LONG", high: "51000.00", low: "50500.00", ts: "2024-01-15T08:00:00Z", mitigated_at: null },
      { direction: "SHORT", high: "49500.00", low: "49000.00", ts: "2024-01-15T07:00:00Z", mitigated_at: "2024-01-15T09:00:00Z" },
    ],
    swings: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("muestra estado APPROVED y dirección LONG", async () => {
    render(<SignalList signals={[mockSignal]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.getByText("APPROVED")).toBeInTheDocument();
      expect(screen.getByText("LONG")).toBeInTheDocument();
    });
  });

  it("muestra niveles formateados con tick_size", async () => {
    render(<SignalList signals={[mockSignal]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.getByText("Entrada:")).toBeInTheDocument();
      expect(screen.getByText("SL:")).toBeInTheDocument();
      expect(screen.getByText("TP:")).toBeInTheDocument();
      expect(screen.getByText("50000.00")).toBeInTheDocument();
      expect(screen.getByText("49000.00")).toBeInTheDocument();
      expect(screen.getByText("52000.00")).toBeInTheDocument();
    });
  });

  it("muestra R:R tal cual del backend", async () => {
    render(<SignalList signals={[mockSignal]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.getByText("R:R")).toBeInTheDocument();
      expect(screen.getByText("2.5")).toBeInTheDocument();
    });
  });

  it("muestra riesgo con la etiqueta «Texto del modelo, no verificado» para rationale", async () => {
    render(<SignalList signals={[mockSignal]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.getByText("Texto del modelo, no verificado")).toBeInTheDocument();
      expect(screen.getByText("Estructura alcista con BOS confirmado en 4h")).toBeInTheDocument();
    });
  });

  it("muestra información de tamaño de posición si está disponible", async () => {
    render(<SignalList signals={[mockSignal]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.getByText("Riesgo:")).toBeInTheDocument();
      expect(screen.getByText(/100\.00/)).toBeInTheDocument();
      expect(screen.getByText(/1\.0%/)).toBeInTheDocument();
      expect(screen.getByText("Notional:")).toBeInTheDocument();
      expect(screen.getByText(/1000\.00/)).toBeInTheDocument();
    });
  });

  it("no muestra información de tamaño si no está disponible", async () => {
    const signalWithoutSize = { ...mockSignal, size: null };
    render(<SignalList signals={[signalWithoutSize]} structure={mockStructure} tickSize="0.01" lotSize="0.00001" />, { wrapper: createWrapper() });

    await vi.waitFor(() => {
      expect(screen.queryByText("Riesgo:")).not.toBeInTheDocument();
    });
  });
});


describe("SignalList: ejecución en paper", () => {
  const signal: TradeSignalSchema = {
    id: "sig-1",
    analysis_id: "an-1",
    symbol: "BTC/USDT",
    timeframe: "1h",
    direction: "LONG",
    entry: "50000.00",
    stop_loss: "49000.00",
    take_profit: "52000.00",
    rr: "2.0",
    status: "APPROVED",
    rationale: "x",
    regime: "TRENDING",
    asset_class: "CRYPTO",
    created_at: "2024-01-15T10:00:00Z",
    veto_reasons: [],
  };
  const structure: MarketStructureResult = { events: [], fvgs: [], swings: [] };
  const renderList = (signals: TradeSignalSchema[]) =>
    render(<SignalList signals={signals} structure={structure} tickSize="0.01" lotSize="0.00001" />, {
      wrapper: createWrapper(),
    });

  beforeEach(() => {
    vi.mocked(apiPost).mockReset();
  });

  it("muestra «Ejecutar (paper)» solo para señales APPROVED", () => {
    renderList([signal, { ...signal, id: "sig-2", status: "REJECTED" }, { ...signal, id: "sig-3", status: "PENDING" }]);
    expect(screen.getAllByRole("button", { name: "Ejecutar (paper)" })).toHaveLength(1);
  });

  it("requiere dos clics: el primero solo pide confirmación", async () => {
    vi.mocked(apiPost).mockResolvedValue({});
    renderList([signal]);

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar (paper)" }));
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar ejecución simulada" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(vi.mocked(apiPost).mock.calls[0][0]).toBe("/api/v1/signals/sig-1/execute");
  });

  it("se deshabilita mientras corre y no envía dos veces", async () => {
    let resolve: (v: unknown) => void = () => undefined;
    vi.mocked(apiPost).mockReturnValue(new Promise((r) => (resolve = r)));
    renderList([signal]);

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar (paper)" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar ejecución simulada" }));

    const busy = await screen.findByRole("button", { name: "Ejecutando…" });
    expect(busy).toBeDisabled();
    fireEvent.click(busy);
    expect(apiPost).toHaveBeenCalledTimes(1);
    resolve({});
  });

  it("un 409 muestra el detail tal cual y la señal sigue visible", async () => {
    const detail = "Señal vetada por la cartera: DAILY_LOSS_LIMIT (límite de pérdida diaria alcanzado)";
    vi.mocked(apiPost).mockRejectedValue(new ApiError(409, detail));
    renderList([signal]);

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar (paper)" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar ejecución simulada" }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByText("APPROVED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ejecutar (paper)" })).toBeEnabled();
  });
});

// overlays conversion tests are in components/chart/__tests__/overlays.test.tsx