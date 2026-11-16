import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { SignalList } from "@/components/signals/signal-list";
import type { components } from "@/types/api";

vi.mock("@/lib/api");

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

// overlays conversion tests are in components/chart/__tests__/overlays.test.tsx