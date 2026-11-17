"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet, type ApiError } from "@/lib/api";
import type { components } from "@/types/api";

type BlotterSchema = components["schemas"]["BlotterSchema"];
type OrderStatus = components["schemas"]["OrderStatus"];

export function useBlotter(status?: OrderStatus) {
  return useQuery<BlotterSchema, ApiError>({
    queryKey: ["blotter", status ?? null],
    queryFn: () =>
      apiGet<BlotterSchema>(
        status
          ? `/api/v1/paper/blotter?status=${encodeURIComponent(status)}`
          : "/api/v1/paper/blotter",
      ),
    refetchInterval: 15000,
    staleTime: 5000,
  });
}
