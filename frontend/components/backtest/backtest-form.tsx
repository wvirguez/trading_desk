"use client";

import { useState } from "react";
import { useTerminalStore } from "@/store/terminal";
import { Button } from "@/components/ui/button";
import type { components } from "@/types/api";

type BacktestConfig = components["schemas"]["BacktestConfig-Input"];
type Timeframe = components["schemas"]["Timeframe"];

const TIMEFRAMES: Timeframe[] = ["5m", "15m", "1h", "4h", "1d"];

interface BacktestFormProps {
  onSubmit: (config: BacktestConfig) => void;
  isPending?: boolean;
}

const INPUT_CLASS =
  "w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100 disabled:opacity-50";
const LABEL_CLASS = "block text-sm font-medium text-zinc-300 mb-1";

function dateToIso(value: string): string | null {
  return value ? `${value}T00:00:00Z` : null;
}

export default function BacktestForm({ onSubmit, isPending = false }: BacktestFormProps) {
  const { symbol, timeframe, setSymbol, setTimeframe } = useTerminalStore();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [initialCapital, setInitialCapital] = useState("10000");
  const [zscoreWindow, setZscoreWindow] = useState("50");
  const [entryZ, setEntryZ] = useState("2");
  const [exitZ, setExitZ] = useState("0");
  const [allowShort, setAllowShort] = useState(true);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    // La validación de negocio vive en BacktestConfig (backend); aquí solo se arma el cuerpo.
    onSubmit({
      symbol,
      timeframe,
      start: dateToIso(start),
      end: dateToIso(end),
      initial_capital: initialCapital,
      zscore_window: Number(zscoreWindow),
      entry_z: Number(entryZ),
      exit_z: Number(exitZ),
      allow_short: allowShort,
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="Configuración del backtest"
      className="space-y-4 p-4 border border-zinc-800 rounded-lg bg-zinc-950/50"
    >
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div>
          <label htmlFor="bt-symbol" className={LABEL_CLASS}>Símbolo</label>
          <input
            id="bt-symbol"
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="bt-timeframe" className={LABEL_CLASS}>Timeframe</label>
          <select
            id="bt-timeframe"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className={INPUT_CLASS}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="bt-start" className={LABEL_CLASS}>Desde (UTC, opcional)</label>
          <input id="bt-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={INPUT_CLASS} />
        </div>
        <div>
          <label htmlFor="bt-end" className={LABEL_CLASS}>Hasta (UTC, opcional)</label>
          <input id="bt-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={INPUT_CLASS} />
        </div>
        <div>
          <label htmlFor="bt-capital" className={LABEL_CLASS}>Capital inicial</label>
          <input
            id="bt-capital"
            type="number"
            min="0"
            step="any"
            value={initialCapital}
            onChange={(e) => setInitialCapital(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="bt-window" className={LABEL_CLASS}>Ventana Z-score</label>
          <input
            id="bt-window"
            type="number"
            min="10"
            max="500"
            step="1"
            value={zscoreWindow}
            onChange={(e) => setZscoreWindow(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="bt-entry" className={LABEL_CLASS}>Z de entrada</label>
          <input
            id="bt-entry"
            type="number"
            step="any"
            value={entryZ}
            onChange={(e) => setEntryZ(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="bt-exit" className={LABEL_CLASS}>Z de salida</label>
          <input
            id="bt-exit"
            type="number"
            step="any"
            value={exitZ}
            onChange={(e) => setExitZ(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={allowShort}
            onChange={(e) => setAllowShort(e.target.checked)}
          />
          Permitir cortos
        </label>
        <div className="flex items-center gap-3">
          {isPending && <span className="text-xs text-zinc-400">Ejecutando backtest…</span>}
          <Button type="submit" disabled={isPending}>
            Ejecutar backtest
          </Button>
        </div>
      </div>
    </form>
  );
}
