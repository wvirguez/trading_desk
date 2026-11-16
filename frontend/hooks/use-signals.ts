"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { components } from "@/types/api";

type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];

export function useActiveSignals(activeSymbol: string) {
  return useQuery<TradeSignalSchema[]>({
    queryKey: ["active-signals"],
    queryFn: () => apiGet<TradeSignalSchema[]>("/api/v1/signals/active"),
    select: (data) => data.filter((signal) => signal.symbol === activeSymbol),
    refetchInterval: 10000,
    enabled: Boolean(activeSymbol),
    staleTime: 5000,
  });
}