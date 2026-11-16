import type { components } from "@/types/api";

type CandleSchema = components["schemas"]["CandleSchema"];

export interface CandleSeriesItem {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  gap?: boolean;
}

export interface TickData {
  ts: number;
  price: string | number;
}

const TIMEFRAME_SECONDS: Record<string, number> = {
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

function parseTsToSeconds(ts: string): number {
  return Math.floor(new Date(ts).getTime() / 1000);
}

function timeframeToSeconds(tf: string): number {
  return TIMEFRAME_SECONDS[tf] ?? 3600;
}

export function candlesToSeries(
  candles: CandleSchema[],
  timeframe: string = "1h",
): CandleSeriesItem[] {
  if (candles.length === 0) return [];

  const sorted = [...candles].sort((a, b) => parseTsToSeconds(a.ts) - parseTsToSeconds(b.ts));

  const dedupedMap = new Map<number, CandleSchema>();

  for (const candle of sorted) {
    const ts = parseTsToSeconds(candle.ts);
    dedupedMap.set(ts, candle);
  }

  const deduped = Array.from(dedupedMap.values()).sort((a, b) => parseTsToSeconds(a.ts) - parseTsToSeconds(b.ts));

  const expectedInterval = timeframeToSeconds(timeframe);
  const gapThreshold = expectedInterval * 1.5;

  const result: CandleSeriesItem[] = [];

  for (let i = 0; i < deduped.length; i++) {
    const candle = deduped[i];
    const ts = parseTsToSeconds(candle.ts);

    let gap = false;
    if (i > 0) {
      const prevTs = parseTsToSeconds(deduped[i - 1].ts);
      const diff = ts - prevTs;
      if (diff > gapThreshold) {
        gap = true;
      }
    }

    result.push({
      time: ts,
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
      gap,
    });
  }

  return result;
}

export function toChartPrice(price: string): number {
  return Number(price);
}

export function applyTick(
  series: CandleSeriesItem[],
  tick: TickData,
  timeframe: string = "1h",
): CandleSeriesItem[] {
  const price = typeof tick.price === "string" ? Number(tick.price) : tick.price;

  if (series.length === 0) {
    return [
      {
        time: tick.ts,
        open: price,
        high: price,
        low: price,
        close: price,
        gap: false,
      },
    ];
  }

  const lastIndex = series.length - 1;
  const lastCandle = series[lastIndex];
  const expectedInterval = timeframeToSeconds(timeframe);
  const gapThreshold = expectedInterval * 1.5;

  if (tick.ts <= lastCandle.time) {
    const updated = [...series];
    updated[lastIndex] = {
      ...lastCandle,
      high: Math.max(lastCandle.high, price),
      low: Math.min(lastCandle.low, price),
      close: price,
    };
    return updated;
  }

  const isGap = tick.ts - lastCandle.time > gapThreshold;

  return [
    ...series,
    {
      time: tick.ts,
      open: price,
      high: price,
      low: price,
      close: price,
      gap: isGap,
    },
  ];
}