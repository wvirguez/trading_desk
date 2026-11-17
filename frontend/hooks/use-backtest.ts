"use client";

import { useMutation } from "@tanstack/react-query";
import { apiPost, type ApiError } from "@/lib/api";
import type { components } from "@/types/api";

type BacktestConfig = components["schemas"]["BacktestConfig-Input"];
type BacktestMetricsSchema = components["schemas"]["BacktestMetricsSchema"];

export function useBacktest() {
  return useMutation<BacktestMetricsSchema, ApiError, BacktestConfig>({
    mutationFn: (config) => apiPost<BacktestMetricsSchema>("/api/v1/quant/backtest", config),
  });
}
