"use client";

import { useEffect, useRef } from "react";
import { createChart, LineSeries, type UTCTimestamp } from "lightweight-charts";
import { equityToSeries } from "@/lib/chart-data";
import type { components } from "@/types/api";

type EquityPoint = components["schemas"]["EquityPoint"];

interface EquityChartProps {
  points: EquityPoint[];
}

export default function EquityChart({ points }: EquityChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const chart = createChart(element, {
      layout: { background: { color: "#0f1117" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1e222d" },
      rightPriceScale: { borderColor: "#1e222d" },
      autoSize: true,
    });
    const series = chart.addSeries(LineSeries, { color: "#26a69a", lineWidth: 2 });
    series.setData(
      equityToSeries(points).map((item) => ({
        time: item.time as UTCTimestamp,
        value: item.value,
      })),
    );
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [points]);

  return (
    <div
      ref={containerRef}
      data-testid="equity-chart"
      aria-label="Curva de capital"
      className="h-[320px] w-full"
    />
  );
}
