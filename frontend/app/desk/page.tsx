"use client";

import { useEffect, useState } from "react";
import { useTerminalStore } from "@/store/terminal";
import SymbolSelect from "@/components/chart/symbol-select";
import TimeframeSelect from "@/components/chart/timeframe-select";
import CandleChart from "@/components/chart/candle-chart";
import { Blotter } from "@/components/blotter/blotter";
import { SignalList } from "@/components/signals/signal-list";
import { useActiveSignals } from "@/hooks/use-signals";
import { useStructure } from "@/hooks/use-structure";
import { useAnalysis } from "@/hooks/use-analysis";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import AnalysisForm from "@/components/agents/analysis-form";
import AnalysisFeed from "@/components/agents/analysis-feed";
import { useQueryClient } from "@tanstack/react-query";

type TabValue = "signals" | "blotter";

export default function DeskPage() {
  const { symbol, timeframe } = useTerminalStore();
  const { data: signals } = useActiveSignals(symbol);
  const { data: structure } = useStructure(symbol, timeframe);
  const queryClient = useQueryClient();
  const analysis = useAnalysis();
  const [activeTab, setActiveTab] = useState<TabValue>("signals");

  const instrument = useTerminalStore.getState().instruments?.find((i) => i.symbol === symbol);
  const tickSize = instrument?.tick_size ?? "0.01";
  const lotSize = instrument?.lot_size ?? "0.00001";
  const instruments = useTerminalStore.getState().instruments ?? [];
  const tickSizes = Object.fromEntries(instruments.map((i) => [i.symbol, i.tick_size]));
  const lotSizes = Object.fromEntries(instruments.map((i) => [i.symbol, i.lot_size]));

  useEffect(() => {
    if (analysis.state.status === "completed") {
      void queryClient.invalidateQueries({ queryKey: ["active-signals"] });
    }
  }, [analysis.state.status, queryClient]);

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex h-12 items-center gap-4 border-b border-zinc-800 px-4">
          <h1 className="text-xl font-semibold">Desk</h1>
          <Separator orientation="vertical" className="h-6" />
          <SymbolSelect />
          <TimeframeSelect />
          <div className="flex-1" />
          <div className="text-sm text-zinc-400 font-mono">
            {symbol} · {timeframe}
          </div>
        </div>
        <div className="flex-1 flex overflow-hidden">
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            <main className="flex-1 p-6 overflow-auto min-h-0">
              <CandleChart className="w-full" />
            </main>
            <section className="h-80 border-t border-zinc-800 bg-zinc-950/50 flex flex-col">
              <Tabs
                value={activeTab}
                onValueChange={(v: string) => setActiveTab(v as TabValue)}
                className="flex-1 flex flex-col min-h-0"
              >
                <TabsList className="border-b border-zinc-800 bg-zinc-950/50">
                  <TabsTrigger value="signals">Señales</TabsTrigger>
                  <TabsTrigger value="blotter">Blotter</TabsTrigger>
                </TabsList>
                <TabsContent value="signals" className="flex-1 min-h-0 overflow-hidden">
                  <ScrollArea className="h-full p-4">
                    <SignalList
                      signals={signals ?? []}
                      structure={structure ?? { events: [], fvgs: [], swings: [] }}
                      tickSize={tickSize}
                      lotSize={lotSize}
                    />
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="blotter" className="flex-1 min-h-0 overflow-hidden">
                  <ScrollArea className="h-full p-4">
                    <Blotter tickSizes={tickSizes} lotSizes={lotSizes} />
                  </ScrollArea>
                </TabsContent>
              </Tabs>
            </section>
          </div>
          <aside className="w-96 border-l border-zinc-800 bg-zinc-950/50 flex flex-col min-h-0">
            <div className="p-4 border-b border-zinc-800 flex-shrink-0">
              <h2 className="text-lg font-semibold">Análisis de agentes</h2>
            </div>
            <div className="flex flex-col gap-4 flex-1 min-h-0 p-4">
              <AnalysisForm analysis={analysis} />
              <AnalysisFeed analysis={analysis} />
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
