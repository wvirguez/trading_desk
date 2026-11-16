"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { components } from "@/types/api";

type CandleSchema = components["schemas"]["CandleSchema"];

export function useOhlcv(symbol: string, timeframe: string) {
  return useQuery<CandleSchema[]>({
    queryKey: ["ohlcv", symbol, timeframe],
    queryFn: () =>
      apiGet<CandleSchema[]>(
        `/api/v1/market/ohlcv?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(timeframe)}&limit=500`,
      ),
    enabled: Boolean(symbol && timeframe),
    staleTime: 30 * 1000,
  });
}