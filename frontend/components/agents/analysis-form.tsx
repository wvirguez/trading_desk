"use client";

import { useTerminalStore } from "@/store/terminal";
import { useAnalysis, type UseAnalysisReturn } from "@/hooks/use-analysis";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { components } from "@/types/api";

type AnalyzeRequest = components["schemas"]["AnalyzeRequest"];
type Timeframe = components["schemas"]["Timeframe"];

const TIMEFRAMES: Timeframe[] = ["5m", "15m", "1h", "4h", "1d"];
const DEFAULT_TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h", "1d"];

export function buildAnalyzeRequest(symbol: string, timeframe: Timeframe): AnalyzeRequest {
  const timeframes = DEFAULT_TIMEFRAMES.includes(timeframe)
    ? [...DEFAULT_TIMEFRAMES]
    : [...DEFAULT_TIMEFRAMES, timeframe];
  return { symbol, timeframe, timeframes };
}

interface AnalysisFormProps {
  analysis?: UseAnalysisReturn;
}

export default function AnalysisForm({ analysis }: AnalysisFormProps) {
  const fallback = useAnalysis();
  const { state, start, cancel } = analysis ?? fallback;
  const { symbol, timeframe, setSymbol, setTimeframe } = useTerminalStore();

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void start(buildAnalyzeRequest(symbol, timeframe));
  };

  const isRunning = state.status === "running";

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 p-4 border border-zinc-800 rounded-lg bg-zinc-950/50"
    >
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="symbol" className="block text-sm font-medium text-zinc-300 mb-1">
            Símbolo
          </label>
          <input
            id="symbol"
            type="text"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            disabled={isRunning}
            className="w-full px-3 py-2 bg-zinc-900 border border-zinc-700 rounded-md text-white placeholder-zinc-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="BTC/USDT"
          />
        </div>
        <div>
          <label htmlFor="timeframe" className="block text-sm font-medium text-zinc-300 mb-1">
            Timeframe
          </label>
          <Select value={timeframe} onValueChange={setTimeframe} disabled={isRunning}>
            <SelectTrigger id="timeframe" className="bg-zinc-900 border-zinc-700 disabled:opacity-50">
              <SelectValue placeholder="Seleccionar" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-700">
              {TIMEFRAMES.map((tf) => (
                <SelectItem key={tf} value={tf}>
                  {tf}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <Separator className="my-2" />
      <div className="flex gap-2">
        <Button type="submit" disabled={isRunning} className="flex-1">
          Analizar
        </Button>
        {isRunning && (
          <Button type="button" variant="outline" onClick={cancel} className="flex-1">
            Cancelar
          </Button>
        )}
      </div>
      {(state.status === "error" || state.status === "failed") && state.error && (
        <div className="text-sm text-red-400 p-2 bg-red-950/30 border border-red-900/50 rounded">
          {state.error}
        </div>
      )}
      {state.status === "cancelled" && (
        <div className="text-sm text-yellow-400 p-2 bg-yellow-950/30 border border-yellow-900/50 rounded">
          Cancelado
        </div>
      )}
    </form>
  );
}
