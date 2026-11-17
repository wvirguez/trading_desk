"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, type ApiError } from "@/lib/api";
import type { components } from "@/types/api";

type OrderReceiptSchema = components["schemas"]["OrderReceiptSchema"];

export function useExecuteSignal() {
  const queryClient = useQueryClient();
  return useMutation<OrderReceiptSchema, ApiError, string>({
    mutationFn: (signalId) =>
      apiPost<OrderReceiptSchema>(`/api/v1/signals/${encodeURIComponent(signalId)}/execute`),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["active-signals"] }),
        queryClient.invalidateQueries({ queryKey: ["blotter"] }),
      ]);
    },
  });
}
