import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode } from "react";
import { useTerminalStore } from "@/store/terminal";
import SymbolSelect from "@/components/chart/symbol-select";
import TimeframeSelect from "@/components/chart/timeframe-select";

const mockUseInstruments = vi.fn();

vi.mock("@/hooks/use-instruments", () => ({
  useInstruments: () => mockUseInstruments(),
}));

const mockInstruments = [
  { symbol: "BTC/USDT", base_currency: "BTC", quote_currency: "USDT", asset_class: "CRYPTO", provider: "BINANCE", provider_symbol: "BTCUSDT", tick_size: "0.01", lot_size: "0.00001", session: "CRYPTO_24_7" },
  { symbol: "ETH/USDT", base_currency: "ETH", quote_currency: "USDT", asset_class: "CRYPTO", provider: "BINANCE", provider_symbol: "ETHUSDT", tick_size: "0.01", lot_size: "0.0001", session: "CRYPTO_24_7" },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
};

describe("SymbolSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTerminalStore.setState({ symbol: "BTC/USDT", timeframe: "1h" });
    mockUseInstruments.mockReturnValue({
      data: mockInstruments,
      isLoading: false,
      isError: false,
      error: null,
      isSuccess: true,
    });
  });

  it("lista los símbolos del endpoint", () => {
    render(<SymbolSelect />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();

    fireEvent.click(select);
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("BTC/USDT");
    expect(options[1]).toHaveTextContent("ETH/USDT");
  });

  it("cambia el store al seleccionar un símbolo", () => {
    render(<SymbolSelect />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    fireEvent.click(select);
    fireEvent.click(screen.getByText("ETH/USDT"));

    expect(useTerminalStore.getState().symbol).toBe("ETH/USDT");
  });

  it("muestra skeleton mientras carga", () => {
    mockUseInstruments.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      isSuccess: false,
    });

    render(<SymbolSelect />, { wrapper: createWrapper() });

    expect(screen.getByTestId("symbol-select-skeleton")).toBeInTheDocument();
  });

  it("muestra error si falla la carga", () => {
    mockUseInstruments.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Error de red"),
      isSuccess: false,
    });

    render(<SymbolSelect />, { wrapper: createWrapper() });

    expect(screen.getByText("Error cargando símbolos: Error de red")).toBeInTheDocument();
  });
});

describe("TimeframeSelect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTerminalStore.setState({ symbol: "BTC/USDT", timeframe: "1h" });
  });

  it("ofrece 5m, 15m, 1h, 4h, 1d", () => {
    render(<TimeframeSelect />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    fireEvent.click(select);

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(5);
    expect(options[0]).toHaveTextContent("5m");
    expect(options[1]).toHaveTextContent("15m");
    expect(options[2]).toHaveTextContent("1h");
    expect(options[3]).toHaveTextContent("4h");
    expect(options[4]).toHaveTextContent("1d");
  });

  it("cambia el store al seleccionar un timeframe", () => {
    render(<TimeframeSelect />, { wrapper: createWrapper() });

    const select = screen.getByRole("combobox");
    fireEvent.click(select);
    fireEvent.click(screen.getByText("4h"));

    expect(useTerminalStore.getState().timeframe).toBe("4h");
  });

  it("no acepta timeframe inválido", () => {
    expect(() => useTerminalStore.getState().setTimeframe("invalid")).toThrow("Timeframe inválido");
  });
});