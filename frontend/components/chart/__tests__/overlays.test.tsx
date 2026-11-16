import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import ChartOverlays from "@/components/chart/overlays";
import type { SignalOverlay, FvgBox } from "@/lib/overlays";

vi.mock("@/lib/chart-data", () => ({
  toChartPrice: (price: string) => Number(price),
}));

const mockRemovePriceLine = vi.fn();
const mockCreatePriceLine = vi.fn();

function createMockPriceLine() {
  return { options: vi.fn(), applyOptions: vi.fn() };
}

function createMockSeries(overrides: Partial<ISeriesApi<"Candlestick">> = {}) {
  return {
    createPriceLine: mockCreatePriceLine,
    removePriceLine: mockRemovePriceLine,
    ...overrides,
  } as unknown as ISeriesApi<"Candlestick">;
}

function createMockChart(): IChartApi {
  return { remove: vi.fn(), subscribeCrosshairMove: vi.fn() } as unknown as IChartApi;
}

const mockSignalOverlay: SignalOverlay = {
  id: "signal-1",
  symbol: "BTC/USDT",
  timeframe: "1h",
  direction: "LONG",
  status: "APPROVED",
  levels: [
    { price: "50000.00", label: "Entrada" },
    { price: "49000.00", label: "SL" },
    { price: "52000.00", label: "TP" },
  ],
  zone: { top: "50000.00", bottom: "49000.00", direction: "LONG" },
  rr: "2.0",
  rationale: "Estructura alcista con BOS confirmado",
};

const mockFvgBoxes: FvgBox[] = [
  {
    top: "51000.00",
    bottom: "50500.00",
    left: 0,
    right: 0,
    direction: "LONG",
    color: "rgba(38, 166, 154, 0.5)",
    borderWidth: 1,
    borderStyle: 0,
    borderColor: "rgba(38, 166, 154, 0.8)",
    mitigated: false,
    ts: "2024-01-15T08:00:00Z",
  },
];

describe("ChartOverlays", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreatePriceLine.mockImplementation(() => createMockPriceLine());
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("crea líneas de precio para entrada, SL y TP cuando showSignals es true", () => {
    const chart = createMockChart();
    const series = createMockSeries();

    render(
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={mockSignalOverlay}
        fvgBoxes={[]}
        showSignals={true}
        showFvgs={false}
      />,
    );

    expect(mockCreatePriceLine).toHaveBeenCalledTimes(3);
    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 50000, title: "Entrada 50000.00" }),
    );
    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 49000, title: "SL 49000.00" }),
    );
    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 52000, title: "TP 52000.00" }),
    );
  });

  it("no crea líneas de precio cuando showSignals es false", () => {
    const chart = createMockChart();
    const series = createMockSeries();

    render(
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={mockSignalOverlay}
        fvgBoxes={[]}
        showSignals={false}
        showFvgs={false}
      />,
    );

    expect(mockCreatePriceLine).not.toHaveBeenCalled();
  });

  it("limpia las líneas de precio al desmontar", () => {
    const chart = createMockChart();
    const series = createMockSeries();

    const { unmount } = render(
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={mockSignalOverlay}
        fvgBoxes={[]}
        showSignals={true}
        showFvgs={false}
      />,
    );

    unmount();

    expect(mockRemovePriceLine).toHaveBeenCalledTimes(3);
  });

  it("crea líneas de precio para las cajas FVG cuando showFvgs es true", () => {
    const chart = createMockChart();
    const series = createMockSeries();

    render(
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={null}
        fvgBoxes={mockFvgBoxes}
        showSignals={false}
        showFvgs={true}
      />,
    );

    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 51000 }),
    );
    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 50500 }),
    );
  });

  it("crea líneas de zona entrada-SL cuando hay señal y FVG activos", () => {
    const chart = createMockChart();
    const series = createMockSeries();

    render(
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={mockSignalOverlay}
        fvgBoxes={mockFvgBoxes}
        showSignals={true}
        showFvgs={true}
      />,
    );

    const zoneTopCalls = mockCreatePriceLine.mock.calls.filter(
      (call: Array<unknown>) => (call[0] as Record<string, unknown>).price === 50000,
    );
    const zoneBottomCalls = mockCreatePriceLine.mock.calls.filter(
      (call: Array<unknown>) => (call[0] as Record<string, unknown>).price === 49000,
    );

    // Zone lines should be created
    expect(zoneTopCalls.length).toBeGreaterThanOrEqual(1);
    expect(zoneBottomCalls.length).toBeGreaterThanOrEqual(1);
  });

  it("no crea líneas cuando chart es null", () => {
    const series = createMockSeries();

    render(
      <ChartOverlays
        chart={null}
        candleSeries={series}
        signalOverlay={mockSignalOverlay}
        fvgBoxes={mockFvgBoxes}
        showSignals={true}
        showFvgs={true}
      />,
    );

    expect(mockCreatePriceLine).not.toHaveBeenCalled();
  });
});