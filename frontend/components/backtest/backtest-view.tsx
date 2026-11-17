"use client";

import dynamic from "next/dynamic";
import { useBacktest } from "@/hooks/use-backtest";
import { Skeleton } from "@/components/ui/skeleton";
import BacktestForm from "./backtest-form";
import BacktestMetrics from "./backtest-metrics";

const EquityChart = dynamic(() => import("./equity-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-[320px] w-full" />,
});

export default function BacktestView() {
  const backtest = useBacktest();

  return (
    <div className="space-y-6">
      <BacktestForm onSubmit={(config) => backtest.mutate(config)} isPending={backtest.isPending} />
      {backtest.isError && (
        <p role="alert" className="text-sm text-red-400">
          {backtest.error.detail}
        </p>
      )}
      {backtest.data && (
        <>
          <BacktestMetrics metrics={backtest.data} />
          <section aria-label="Curva de capital" className="space-y-2">
            <h2 className="text-lg font-semibold">Curva de capital</h2>
            {backtest.data.equity_curve.length > 0 ? (
              <EquityChart points={backtest.data.equity_curve} />
            ) : (
              <p className="text-sm text-zinc-400">Sin puntos de curva de capital.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
