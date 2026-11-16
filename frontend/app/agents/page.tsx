"use client";

import { useTerminalStore } from "@/store/terminal";
import Sidebar from "@/components/shell/sidebar";
import Topbar from "@/components/shell/topbar";
import AnalysisForm from "@/components/agents/analysis-form";
import AnalysisFeed from "@/components/agents/analysis-feed";
import { useAnalysis } from "@/hooks/use-analysis";

export default function AgentsPage() {
  const { symbol, timeframe } = useTerminalStore();
  const analysis = useAnalysis();

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 flex overflow-hidden">
          <div className="w-full max-w-4xl mx-auto flex flex-col flex-1 p-6">
            <div className="mb-6">
              <h1 className="text-2xl font-semibold">Análisis de agentes</h1>
              <p className="text-zinc-400 mt-1">
                Feed de razonamiento paso a paso de {symbol} · {timeframe} vía SSE
              </p>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
              <div className="lg:col-span-1">
                <AnalysisForm analysis={analysis} />
              </div>
              <div className="lg:col-span-2 min-h-0">
                <AnalysisFeed analysis={analysis} />
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
