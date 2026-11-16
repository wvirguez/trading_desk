"use client";

import { useEffect, useState } from "react";
import { useTerminalStore } from "@/store/terminal";
import SymbolSelect from "@/components/chart/symbol-select";
import TimeframeSelect from "@/components/chart/timeframe-select";
import CandleChart from "@/components/chart/candle-chart";
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

type TabValue = "signals" | "analysis";

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
          <main className="flex-1 p-6 overflow-auto min-w-0">
            <CandleChart className="w-full" />
          </main>
          <aside className="w-96 border-l border-zinc-800 bg-zinc-950/50 flex flex-col">
            <Tabs
              value={activeTab}
              onValueChange={(v: string) => setActiveTab(v as TabValue)}
              className="flex-1 flex flex-col"
            >
              <TabsList className="border-b border-zinc-800 bg-zinc-950/50">
                <TabsTrigger value="signals">Señales</TabsTrigger>
                <TabsTrigger value="analysis">Análisis</TabsTrigger>
              </TabsList>
              <TabsContent value="signals" className="flex-1 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-zinc-800">
                  <h2 className="text-lg font-semibold">Señales activas</h2>
                </div>
                <ScrollArea className="flex-1 p-4">
                  <SignalList
                    signals={signals ?? []}
                    structure={structure ?? { events: [], fvgs: [], swings: [] }}
                    tickSize={tickSize}
                    lotSize={lotSize}
                  />
                </ScrollArea>
              </TabsContent>
              <TabsContent
                value="analysis"
                className="flex-1 flex flex-col overflow-hidden min-h-0"
              >
                <div className="flex flex-col flex-1 min-h-0">
                  <div className="p-4 border-b border-zinc-800 flex-shrink-0">
                    <h2 className="text-lg font-semibold">Análisis de agentes</h2>
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1 min-h-0 p-4">
                    <div className="lg:col-span-1 min-h-0">
                      <AnalysisForm analysis={analysis} />
                    </div>
                    <div className="lg:col-span-2 min-h-0">
                      <AnalysisFeed analysis={analysis} />
                    </div>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </aside>
        </div>
      </div>
    </div>
  );
}
