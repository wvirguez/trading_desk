"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode, useEffect } from "react";
import { useInstruments } from "@/hooks/use-instruments";
import { useTerminalStore } from "@/store/terminal";

function InstrumentsInitializer() {
  const { data: instruments, isSuccess } = useInstruments();
  const setInstruments = useTerminalStore((state) => state.setInstruments);

  useEffect(() => {
    if (isSuccess && instruments) {
      setInstruments(instruments);
    }
  }, [isSuccess, instruments, setInstruments]);

  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000 * 60 * 5,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <InstrumentsInitializer />
      {children}
    </QueryClientProvider>
  );
}