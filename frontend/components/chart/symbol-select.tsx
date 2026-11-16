"use client";

import { useTerminalStore } from "@/store/terminal";
import { useInstruments } from "@/hooks/use-instruments";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

export default function SymbolSelect() {
  const { symbol, setSymbol } = useTerminalStore();
  const { data: instruments, isLoading, isError, error } = useInstruments();

  if (isLoading) {
    return (
      <div className="w-48">
        <Skeleton className="h-10 w-full" data-testid="symbol-select-skeleton" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="w-48 text-sm text-red-400">
        Error cargando símbolos: {error instanceof Error ? error.message : "Error desconocido"}
      </div>
    );
  }

  return (
    <div className="w-48">
      <Select value={symbol} onValueChange={setSymbol}>
        <SelectTrigger>
          <SelectValue placeholder="Símbolo" />
        </SelectTrigger>
        <SelectContent>
          {instruments?.map((inst) => (
            <SelectItem key={inst.symbol} value={inst.symbol}>
              {inst.symbol}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}