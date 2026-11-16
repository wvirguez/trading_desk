"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { components } from "@/types/api";

type MarketStructureResult = components["schemas"]["MarketStructureResult"];

export function useStructure(symbol: string, timeframe: string) {
  return useQuery<MarketStructureResult>({
    queryKey: ["structure", symbol, timeframe],
    queryFn: () =>
      apiGet<MarketStructureResult>(
        `/api/v1/market/structure?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(timeframe)}`,
      ),
    enabled: Boolean(symbol && timeframe),
    staleTime: 30000,
  });
}