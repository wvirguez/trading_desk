"use client";

import { Fragment, useState } from "react";
import { formatAmount, formatPrice } from "@/lib/format";
import type { components } from "@/types/api";

type JournalEntrySchema = components["schemas"]["JournalEntrySchema"];

const NULL_VALUE = "—";

interface JournalTableProps {
  entries: JournalEntrySchema[];
  tickSizes: Record<string, string>;
}

export default function JournalTable({ entries, tickSizes }: JournalTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (entries.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-zinc-500">
        Sin señales registradas. Lanza un análisis en /agents.
      </p>
    );
  }

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-700 text-left text-xs text-zinc-400">
            <th className="py-2 pr-3 font-medium">Símbolo</th>
            <th className="py-2 pr-3 font-medium">Dirección</th>
            <th className="py-2 pr-3 font-medium">Señal</th>
            <th className="py-2 pr-3 font-medium">Resultado</th>
            <th className="py-2 pr-3 text-right font-medium">Entrada</th>
            <th className="py-2 pr-3 text-right font-medium">SL</th>
            <th className="py-2 pr-3 text-right font-medium">TP</th>
            <th className="py-2 pr-3 text-right font-medium">R:R emitido</th>
            <th className="py-2 pr-3 text-right font-medium">R realizado</th>
            <th className="py-2 pr-3 font-medium">Vetos</th>
            <th className="py-2 font-medium">Detalle</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const tick = tickSizes[entry.symbol] ?? "0.01";
            const isOpen = expanded.has(entry.signal_id);
            const directionColor = entry.direction === "LONG" ? "text-green-400" : "text-red-400";
            return (
              <Fragment key={entry.signal_id}>
                <tr className="border-b border-zinc-800 font-mono">
                  <td className="py-2 pr-3 text-white">{entry.symbol}</td>
                  <td className={`py-2 pr-3 ${directionColor}`}>{entry.direction}</td>
                  <td className="py-2 pr-3 text-zinc-300">{entry.signal_status}</td>
                  <td className="py-2 pr-3 text-zinc-300">{entry.outcome}</td>
                  <td className="py-2 pr-3 text-right text-white">{formatPrice(entry.entry, tick)}</td>
                  <td className="py-2 pr-3 text-right text-white">{formatPrice(entry.stop_loss, tick)}</td>
                  <td className="py-2 pr-3 text-right text-white">{formatPrice(entry.take_profit, tick)}</td>
                  <td className="py-2 pr-3 text-right text-white">{formatAmount(entry.rr)}</td>
                  <td className="py-2 pr-3 text-right text-white">
                    {entry.r_multiple ? formatAmount(entry.r_multiple) : NULL_VALUE}
                  </td>
                  <td className="py-2 pr-3 text-amber-400">
                    {entry.veto_reasons.length > 0 ? entry.veto_reasons.join(", ") : NULL_VALUE}
                  </td>
                  <td className="py-2 font-sans">
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => toggle(entry.signal_id)}
                      className="rounded border border-zinc-600 px-2 py-0.5 text-xs text-zinc-200 hover:bg-zinc-800"
                    >
                      {isOpen ? "Ocultar texto" : "Ver texto"}
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="border-b border-zinc-800">
                    <td colSpan={11} className="space-y-1 py-2 pr-3">
                      <p className="text-xs text-zinc-500">Texto del modelo, no verificado</p>
                      <p className="whitespace-pre-wrap text-sm text-zinc-300">{entry.rationale}</p>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
