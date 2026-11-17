"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet, type ApiError } from "@/lib/api";
import type { components } from "@/types/api";

type JournalSchema = components["schemas"]["JournalSchema"];

export function useJournal(symbol?: string, limit: number = 100) {
  return useQuery<JournalSchema, ApiError>({
    queryKey: ["journal", symbol ?? null, limit],
    queryFn: () => {
      const params = new URLSearchParams();
      if (symbol) params.set("symbol", symbol);
      params.set("limit", String(limit));
      return apiGet<JournalSchema>(`/api/v1/journal?${params.toString()}`);
    },
    staleTime: 5000,
  });
}
