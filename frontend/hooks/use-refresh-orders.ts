"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, type ApiError } from "@/lib/api";
import type { components } from "@/types/api";

type PaperRefreshResult = components["schemas"]["PaperRefreshResult"];

export function useRefreshOrders() {
  const queryClient = useQueryClient();
  return useMutation<PaperRefreshResult, ApiError>({
    mutationFn: () => apiPost<PaperRefreshResult>("/api/v1/paper/refresh"),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["blotter"] });
    },
  });
}
