import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTerminalStore } from "@/store/terminal";
import BacktestForm from "../backtest-form";
import BacktestMetrics from "../backtest-metrics";
import EquityChart from "../equity-chart";
import BacktestPage from "@/app/backtest/page";
import type { components } from "@/types/api";

type Metrics = components["schemas"]["BacktestMetricsSchema"];

const chartMocks = vi.hoisted(() => {
  const setData = vi.fn();
  const remove = vi.fn();
  const addSeries = vi.fn(() => ({ setData }));
  const createChart = vi.fn(() => ({
    addSeries,
    remove,
    timeScale: () => ({ fitContent: vi.fn() }),
  }));
  return { setData, remove, addSeries, createChart };
});

vi.mock("lightweight-charts", () => ({
  createChart: chartMocks.createChart,
  LineSeries: { type: "Line" },
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/backtest" }));
vi.mock("@/components/shell/topbar", () => ({ default: () => <div data-testid="topbar" /> }));
vi.mock("@/lib/env", () => ({ getApiUrl: () => "http://localhost:8000" }));

const METRICS: Metrics = {
  strategy_id: "123e4567-e89b-12d3-a456-426614174000",
  config: {
    symbol: "BTC/USDT",
    timeframe: "1h",
    initial_capital: "10000",
    zscore_window: 50,
    entry_z: 2,
    exit_z: 0,
    allow_short: true,
  },
  n_bars: 500,
  n_trades: 12,
  total_return: 0.1234,
  sharpe: 1.2345,
  max_drawdown: -0.0567,
  win_rate: 0.5,
  expectancy: 0.0021,
  final_equity: "11234.5678",
  equity_curve: [
    { ts: "2024-01-01T01:00:00Z", equity: "10100" },
    { ts: "2024-01-01T00:00:00Z", equity: "10000" },
  ],
  warnings: ["Pocas operaciones: resultado no concluyente"],
};

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  useTerminalStore.setState({ symbol: "BTC/USDT", timeframe: "1h" });
});

describe("BacktestForm", () => {
  it("usa símbolo y timeframe del store y los valores por defecto de BacktestConfig", () => {
    useTerminalStore.setState({ symbol: "ETH/USDT", timeframe: "4h" });
    const onSubmit = vi.fn();
    render(<BacktestForm onSubmit={onSubmit} />);

    expect(screen.getByLabelText("Símbolo")).toHaveValue("ETH/USDT");
    expect(screen.getByLabelText("Timeframe")).toHaveValue("4h");
    expect(screen.getByLabelText("Capital inicial")).toHaveValue(10000);
    expect(screen.getByLabelText("Ventana Z-score")).toHaveValue(50);
    expect(screen.getByLabelText("Z de entrada")).toHaveValue(2);
    expect(screen.getByLabelText("Z de salida")).toHaveValue(0);
    expect(screen.getByLabelText("Permitir cortos")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar backtest" }));
    expect(onSubmit).toHaveBeenCalledWith({
      symbol: "ETH/USDT",
      timeframe: "4h",
      start: null,
      end: null,
      initial_capital: "10000",
      zscore_window: 50,
      entry_z: 2,
      exit_z: 0,
      allow_short: true,
    });
  });

  it("no valida negocio: envía valores fuera de rango tal cual", () => {
    const onSubmit = vi.fn();
    render(<BacktestForm onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Ventana Z-score"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Desde (UTC, opcional)"), { target: { value: "2024-01-01" } });
    fireEvent.submit(screen.getByRole("form", { name: "Configuración del backtest" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ zscore_window: 5, start: "2024-01-01T00:00:00Z" }),
    );
  });

  it("deshabilita «Ejecutar backtest» mientras corre", () => {
    render(<BacktestForm onSubmit={vi.fn()} isPending />);
    expect(screen.getByRole("button", { name: "Ejecutar backtest" })).toBeDisabled();
  });
});

describe("BacktestMetrics", () => {
  it("muestra todas las métricas con formato, avisos y la limitación", () => {
    render(<BacktestMetrics metrics={METRICS} />);
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("12.34 %")).toBeInTheDocument();
    expect(screen.getByText("1.23")).toBeInTheDocument();
    expect(screen.getByText("-5.67 %")).toBeInTheDocument();
    expect(screen.getByText("50.00 %")).toBeInTheDocument();
    expect(screen.getByText("0.21 %")).toBeInTheDocument();
    expect(screen.getByText("11234.57")).toBeInTheDocument();
    expect(screen.getByText("Pocas operaciones: resultado no concluyente")).toBeInTheDocument();
    expect(screen.getByText("El backtest no modela costes ni slippage")).toBeInTheDocument();
  });
});

describe("EquityChart", () => {
  it("crea una serie de línea con los puntos y se limpia al desmontar", () => {
    const { unmount } = render(<EquityChart points={METRICS.equity_curve} />);
    expect(chartMocks.createChart).toHaveBeenCalledTimes(1);
    expect(chartMocks.addSeries).toHaveBeenCalledWith({ type: "Line" }, expect.anything());
    expect(chartMocks.setData).toHaveBeenCalledWith([
      { time: 1704067200, value: 10000 },
      { time: 1704070800, value: 10100 },
    ]);
    unmount();
    expect(chartMocks.remove).toHaveBeenCalledTimes(1);
  });
});

describe("Página /backtest", () => {
  const mockFetch = vi.fn();
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal("fetch", mockFetch);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("no es marcadora y ejecuta el backtest mostrando métricas y curva", async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => METRICS });
    renderWithClient(<BacktestPage />);
    expect(screen.queryByText("Pendiente: paso 4.8")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar backtest" }));
    expect(await screen.findByText("12.34 %")).toBeInTheDocument();
    expect(await screen.findByTestId("equity-chart")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/quant/backtest",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("muestra el detail de un 422 y el formulario sigue usable", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({ detail: "Datos insuficientes para BTC/USDT 1h" }),
    });
    renderWithClient(<BacktestPage />);

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar backtest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Datos insuficientes para BTC/USDT 1h");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ejecutar backtest" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Ventana Z-score"), { target: { value: "60" } });
    expect(screen.getByLabelText("Ventana Z-score")).toHaveValue(60);
  });
});
