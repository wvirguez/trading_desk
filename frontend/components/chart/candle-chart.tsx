"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createChart, CandlestickSeries, IChartApi, ISeriesApi, CandlestickSeriesPartialOptions, UTCTimestamp } from "lightweight-charts";
import { useTerminalStore } from "@/store/terminal";
import { useOhlcv } from "@/hooks/use-ohlcv";
import { useActiveSignals } from "@/hooks/use-signals";
import { useStructure } from "@/hooks/use-structure";
import { useStream } from "@/hooks/use-stream";
import { candlesToSeries, type CandleSeriesItem } from "@/lib/chart-data";
import { formatPrice } from "@/lib/format";
import { signalToOverlay, fvgToBox, type FvgBox } from "@/lib/overlays";
import ChartOverlays from "./overlays";
import { Skeleton } from "@/components/ui/skeleton";

interface CandleChartProps {
  className?: string;
}

function createCandleChart(element: HTMLDivElement): {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
} {
  const chart = createChart(element, {
    layout: { background: { color: "#0f1117" }, textColor: "#d1d4dc" },
    grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
    crosshair: { mode: 1 },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1e222d" },
    rightPriceScale: { borderColor: "#1e222d" },
    autoSize: true,
  });

  const series = chart.addSeries(CandlestickSeries, {
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
  } satisfies CandlestickSeriesPartialOptions);

  return { chart, series };
}

export default function CandleChart({ className }: CandleChartProps) {
  const { symbol, timeframe, instruments } = useTerminalStore();
  const queryClient = useQueryClient();
  const { data: candles, isLoading, isError, error } = useOhlcv(symbol, timeframe);
  const { data: signals, isLoading: signalsLoading } = useActiveSignals(symbol);
  const { data: structure, isLoading: structureLoading } = useStructure(symbol, timeframe);

  const seriesRef = useRef<CandleSeriesItem[]>([]);
  const chartApiRef = useRef<IChartApi | null>(null);
  const [chart, setChart] = useState<IChartApi | null>(null);
  const [series, setSeries] = useState<ISeriesApi<"Candlestick"> | null>(null);
  const [showSignals, setShowSignals] = useState(true);
  const [showFvgs, setShowFvgs] = useState(true);

  const instrument = instruments.find((item) => item.symbol === symbol);
  const tickSize = instrument?.tick_size ?? "0.01";
  const lastClose = candles && candles.length > 0 ? candles[candles.length - 1].close : null;

  const signalOverlay = signals?.[0] ? signalToOverlay(signals[0]) : null;
  const fvgBoxes = structure?.fvgs
    ?.map((fvg) => fvgToBox(fvg))
    .filter((box): box is FvgBox => box !== null) ?? [];

  const handleTick = useCallback((updatedSeries: CandleSeriesItem[]) => {
    seriesRef.current = updatedSeries;
    if (series) {
      const chartData = updatedSeries.map((item) => ({
        ...item,
        time: item.time as UTCTimestamp,
      }));
      series.setData(chartData);
    }
  }, [series]);

  const handleSignal = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["active-signals"] });
  }, [queryClient]);

  const handleWarning = useCallback(() => {
    // El aviso de datos provisionales se deriva de lastTick en la barra del gráfico.
  }, []);

  const { connectionState, lastTick, lastSignal } = useStream(symbol, timeframe, {
    onTick: handleTick,
    onSignal: handleSignal,
    onWarning: handleWarning,
  });

  const displayedPrice = lastTick?.price ?? lastClose;

  const attachChart = useCallback((element: HTMLDivElement | null) => {
    chartApiRef.current?.remove();
    chartApiRef.current = null;

    if (!element) {
      setChart(null);
      setSeries(null);
      return;
    }

    const created = createCandleChart(element);
    chartApiRef.current = created.chart;
    setChart(created.chart);
    setSeries(created.series);
  }, []);

  useEffect(() => {
    if (!series || !candles) return;

    const seriesData = candlesToSeries(candles, timeframe);
    seriesRef.current = seriesData;
    const chartData = seriesData.map((item) => ({
      ...item,
      time: item.time as UTCTimestamp,
    }));
    series.setData(chartData);
  }, [candles, timeframe, series]);

  if (isLoading) {
    return (
      <div className={`h-[400px] w-full ${className ?? ""}`} data-testid="candle-chart-skeleton">
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={`h-[400px] w-full flex items-center justify-center text-red-400 ${className ?? ""}`}>
        Error cargando velas: {error instanceof Error ? error.message : "Error desconocido"}
      </div>
    );
  }

  if (!candles || candles.length === 0) {
    return (
      <div className={`h-[400px] w-full flex items-center justify-center text-zinc-400 ${className ?? ""}`}>
        Sin velas para {symbol} {timeframe}. Ingiere datos con la CLI.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[400px] w-full">
      <div className="flex items-center gap-2 mb-2 px-2">
        {displayedPrice && (
          <span data-testid="last-price" className="text-sm font-mono text-zinc-100">
            {formatPrice(displayedPrice, tickSize)}
          </span>
        )}
        <label className="flex items-center gap-1 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={showSignals}
            onChange={(e) => setShowSignals(e.target.checked)}
            className="rounded border-zinc-600 text-blue-500 focus:ring-blue-500"
          />
          Señales
        </label>
        <label className="flex items-center gap-1 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={showFvgs}
            onChange={(e) => setShowFvgs(e.target.checked)}
            className="rounded border-zinc-600 text-blue-500 focus:ring-blue-500"
          />
          FVG
        </label>
        {signalsLoading && <span className="text-xs text-zinc-500">Cargando señales...</span>}
        {structureLoading && <span className="text-xs text-zinc-500">Cargando estructura...</span>}
        {connectionState === "Reconectando..." && (
          <span className="text-xs text-yellow-400">Reconectando stream…</span>
        )}
        {connectionState === "Desconectado" && (
          <span className="text-xs text-red-400">Stream desconectado</span>
        )}
        {lastTick && (
          <span className="text-xs text-zinc-500" data-testid="provisional-warning">
            Precio = último cierre ingerido (no es tiempo real)
          </span>
        )}
        {lastSignal && (
          <span className="text-xs text-green-400" data-testid="signal-alert">
            Nueva señal aprobada recibida: {lastSignal.signal.symbol} {lastSignal.signal.direction}
          </span>
        )}
        <span
          data-testid="chart-overlays-status"
          data-signal-count={signalOverlay ? "1" : "0"}
          data-fvg-count={String(fvgBoxes.length)}
          data-signals-visible={showSignals ? "true" : "false"}
          data-fvgs-visible={showFvgs ? "true" : "false"}
          className="sr-only"
        />
      </div>
      <div
        ref={attachChart}
        className={`flex-1 w-full ${className ?? ""}`}
        style={{ minHeight: "350px" }}
      />
      <ChartOverlays
        chart={chart}
        candleSeries={series}
        signalOverlay={signalOverlay}
        fvgBoxes={fvgBoxes}
        showSignals={showSignals}
        showFvgs={showFvgs}
      />
    </div>
  );
}