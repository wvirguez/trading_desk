"use client";

import { useState } from "react";
import { useInstruments } from "@/hooks/use-instruments";
import { useJournal } from "@/hooks/use-journal";
import JournalSummary from "./journal-summary";
import JournalTable from "./journal-table";

export default function JournalView() {
  const [symbol, setSymbol] = useState("");
  const { data: instruments } = useInstruments();
  const { data, error, isLoading, refetch } = useJournal(symbol || undefined);
  const tickSizes = Object.fromEntries((instruments ?? []).map((i) => [i.symbol, i.tick_size]));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <label htmlFor="journal-symbol" className="text-sm text-zinc-400">
          Símbolo
        </label>
        <select
          id="journal-symbol"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100"
        >
          <option value="">Todos</option>
          {(instruments ?? []).map((inst) => (
            <option key={inst.symbol} value={inst.symbol}>
              {inst.symbol}
            </option>
          ))}
        </select>
      </div>

      {isLoading && <p className="text-sm text-zinc-500">Cargando diario…</p>}

      {error && (
        <div role="alert" className="space-y-3 text-sm">
          <p className="text-red-400">{error.detail}</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="rounded border border-zinc-600 px-3 py-1 text-zinc-200 hover:bg-zinc-800"
          >
            Reintentar
          </button>
        </div>
      )}

      {data && (
        <>
          <JournalSummary summary={data.summary} />
          <JournalTable entries={data.entries} tickSizes={tickSizes} />
        </>
      )}
    </div>
  );
}
