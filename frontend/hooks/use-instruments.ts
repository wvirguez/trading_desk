"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { components } from "@/types/api";

type InstrumentSchema = components["schemas"]["InstrumentSchema"];

export function useInstruments() {
  return useQuery<InstrumentSchema[]>({
    queryKey: ["instruments"],
    queryFn: () => apiGet<InstrumentSchema[]>("/api/v1/market/instruments"),
    staleTime: 5 * 60 * 1000,
  });
}