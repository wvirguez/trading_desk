import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { useTerminalStore } from "@/store/terminal";
import CandleChart from "@/components/chart/candle-chart";

const mockUseOhlcv = vi.fn();

vi.mock("@/hooks/use-ohlcv", () => ({
  useOhlcv: () => mockUseOhlcv(),
}));

// Mock lightweight-charts to avoid canvas/ResizeObserver issues in jsdom
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(),
  candlestickSeries: {},
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
};

describe("CandleChart - estados de UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTerminalStore.setState({ symbol: "BTC/USDT", timeframe: "1h" });
  });

  it("muestra skeleton mientras carga", () => {
    mockUseOhlcv.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      isSuccess: false,
    });

    render(<CandleChart />, { wrapper: createWrapper() });

    expect(screen.getByTestId("candle-chart-skeleton")).toBeInTheDocument();
  });

  it("muestra error visible si falla la carga", () => {
    mockUseOhlcv.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Instrumento no encontrado"),
      isSuccess: false,
    });

    render(<CandleChart />, { wrapper: createWrapper() });

    expect(screen.getByText("Error cargando velas: Instrumento no encontrado")).toBeInTheDocument();
  });

  it("muestra estado vacío en español cuando no hay velas", () => {
    mockUseOhlcv.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      error: null,
      isSuccess: true,
    });

    render(<CandleChart />, { wrapper: createWrapper() });

    expect(screen.getByText("Sin velas para BTC/USDT 1h. Ingiere datos con la CLI.")).toBeInTheDocument();
  });
});