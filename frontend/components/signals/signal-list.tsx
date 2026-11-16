"use client";

import { formatPrice } from "@/lib/format";
import type { components } from "@/types/api";

type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];

interface SignalListProps {
  signals: TradeSignalSchema[];
  structure: components["schemas"]["MarketStructureResult"];
  tickSize: string;
  lotSize: string;
}

export function SignalList({ signals, tickSize }: SignalListProps) {
  if (signals.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-8">
        Sin señales activas para el símbolo seleccionado
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {signals.map((signal) => (
        <SignalCard key={signal.id} signal={signal} tickSize={tickSize} />
      ))}
    </div>
  );
}

interface SignalCardProps {
  signal: TradeSignalSchema;
  tickSize: string;
}

function SignalCard({ signal, tickSize }: SignalCardProps) {
  const entry = formatPrice(signal.entry, tickSize);
  const stopLoss = formatPrice(signal.stop_loss, tickSize);
  const takeProfit = formatPrice(signal.take_profit, tickSize);

  const directionColor = signal.direction === "LONG" ? "text-green-400" : "text-red-400";
  const directionBg = signal.direction === "LONG" ? "bg-green-900/30" : "bg-red-900/30";

  return (
    <div className="border border-zinc-700 rounded-lg p-4 bg-zinc-900/50">
      <div className="flex items-center justify-between mb-3">
        <span className={`px-2 py-1 text-xs font-mono rounded ${directionBg} ${directionColor}`}>
          {signal.direction}
        </span>
        <span className="px-2 py-1 text-xs font-mono rounded bg-zinc-800 text-zinc-300">
          {signal.status}
        </span>
        <span className="px-2 py-1 text-xs font-mono rounded bg-zinc-800 text-zinc-300">
          {signal.timeframe}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm mb-3">
        <div>
          <span className="text-zinc-400">Entrada:</span>
          <span className="font-mono text-white ml-2">{entry}</span>
        </div>
        <div>
          <span className="text-zinc-400">SL:</span>
          <span className="font-mono text-white ml-2">{stopLoss}</span>
        </div>
        <div>
          <span className="text-zinc-400">TP:</span>
          <span className="font-mono text-white ml-2">{takeProfit}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm mb-3">
        <div>
          <span className="text-zinc-400">R:R</span>
          <span className="font-mono text-white ml-2">{signal.rr}</span>
        </div>
        {signal.size && (
          <>
            <div>
              <span className="text-zinc-400">Riesgo:</span>
              <span className="font-mono text-white ml-2">
                {formatPrice(signal.size.risk_amount, tickSize)} ({signal.size.risk_pct}%)
              </span>
            </div>
            <div>
              <span className="text-zinc-400">Notional:</span>
              <span className="font-mono text-white ml-2">{formatPrice(signal.size.notional, tickSize)}</span>
            </div>
          </>
        )}
      </div>

      <div className="pt-3 border-t border-zinc-700">
        <div className="flex items-center gap-2 text-xs text-zinc-500 mb-1">
          <span className="font-medium">Rationale:</span>
          <span className="italic">Texto del modelo, no verificado</span>
        </div>
        <p className="text-zinc-300 text-sm whitespace-pre-wrap">{signal.rationale}</p>
      </div>
    </div>
  );
}