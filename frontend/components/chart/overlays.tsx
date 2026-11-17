"use client";

import { useEffect, useRef } from "react";
import { IChartApi, ISeriesApi, IPriceLine } from "lightweight-charts";
import type { SignalOverlay, FvgBox } from "@/lib/overlays";
import { toChartPrice } from "@/lib/chart-data";

interface ChartOverlaysProps {
  chart: IChartApi | null;
  candleSeries: ISeriesApi<"Candlestick"> | null;
  signalOverlay: SignalOverlay | null;
  fvgBoxes: FvgBox[];
  showSignals: boolean;
  showFvgs: boolean;
}

export default function ChartOverlays({
  chart,
  candleSeries,
  signalOverlay,
  fvgBoxes,
  showSignals,
  showFvgs,
}: ChartOverlaysProps) {
  const priceLinesRef = useRef<Map<string, IPriceLine>>(new Map());

  useEffect(() => {
    const chartInstance = chart;
    const seriesInstance = candleSeries;
    const priceLines = priceLinesRef.current;

    if (!chartInstance || !seriesInstance || !signalOverlay || !showSignals) {
      if (seriesInstance) {
        priceLines.forEach((line) => seriesInstance.removePriceLine(line));
      }
      priceLines.clear();
      return;
    }

    const levels = signalOverlay.levels;

    levels.forEach((level) => {
      const key = `signal-${signalOverlay.id}-${level.label}`;
      if (!priceLines.has(key)) {
        const line = seriesInstance.createPriceLine({
          price: toChartPrice(level.price),
          color: level.label === "Entrada" ? "#2962ff" : level.label === "SL" ? "#ef5350" : "#26a69a",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${level.label} ${level.price}`,
        });
        priceLines.set(key, line);
      }
    });

    return () => {
      if (seriesInstance) {
        priceLines.forEach((line) => seriesInstance.removePriceLine(line));
      }
      priceLines.clear();
    };
  }, [chart, candleSeries, signalOverlay, showSignals]);

  useEffect(() => {
    const chartInstance = chart;
    const seriesInstance = candleSeries;

    if (!chartInstance || !seriesInstance || !showFvgs) {
      return;
    }

    const existingLines = new Map<string, IPriceLine>();

    fvgBoxes.forEach((fvg) => {
      const topKey = `fvg-${fvg.ts}-top`;
      const bottomKey = `fvg-${fvg.ts}-bottom`;

      if (!existingLines.has(topKey)) {
        const line = seriesInstance.createPriceLine({
          price: toChartPrice(fvg.top),
          color: fvg.color,
          lineWidth: fvg.borderWidth as 1 | 2 | 3 | 4,
          lineStyle: fvg.borderStyle === 2 ? 2 : 0,
          axisLabelVisible: false,
        });
        existingLines.set(topKey, line);
      }

      if (!existingLines.has(bottomKey)) {
        const line = seriesInstance.createPriceLine({
          price: toChartPrice(fvg.bottom),
          color: fvg.color,
          lineWidth: fvg.borderWidth as 1 | 2 | 3 | 4,
          lineStyle: fvg.borderStyle === 2 ? 2 : 0,
          axisLabelVisible: false,
        });
        existingLines.set(bottomKey, line);
      }
    });

    if (signalOverlay) {
      const zone = signalOverlay.zone;
      const topKey = `signal-zone-top`;
      const bottomKey = `signal-zone-bottom`;

      if (!existingLines.has(topKey)) {
        const line = seriesInstance.createPriceLine({
          price: toChartPrice(zone.top),
          color: zone.direction === "LONG" ? "#26a69a" : "#ef5350",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
        });
        existingLines.set(topKey, line);
      }

      if (!existingLines.has(bottomKey)) {
        const line = seriesInstance.createPriceLine({
          price: toChartPrice(zone.bottom),
          color: zone.direction === "LONG" ? "#26a69a" : "#ef5350",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
        });
        existingLines.set(bottomKey, line);
      }
    }

    return () => {
      existingLines.forEach((line) => seriesInstance.removePriceLine(line));
    };
  }, [chart, candleSeries, fvgBoxes, showFvgs, signalOverlay]);

  // Indicador accesible para los E2E: los niveles viven en un canvas y no son consultables por DOM.
  const drawn =
    chart && candleSeries && signalOverlay && showSignals
      ? signalOverlay.levels.map((level) => level.label).join(",")
      : "";
  return <span data-testid="chart-price-lines" data-lines={drawn} className="sr-only" />;
}