import { formatAmount, formatPercent } from "@/lib/format";
import type { components } from "@/types/api";

type BacktestMetricsSchema = components["schemas"]["BacktestMetricsSchema"];

interface BacktestMetricsProps {
  metrics: BacktestMetricsSchema;
}

export default function BacktestMetrics({ metrics }: BacktestMetricsProps) {
  const rows: Array<[string, string]> = [
    ["Barras", String(metrics.n_bars)],
    ["Operaciones", String(metrics.n_trades)],
    ["Retorno total", formatPercent(metrics.total_return)],
    ["Sharpe", formatAmount(metrics.sharpe)],
    ["Max drawdown", formatPercent(metrics.max_drawdown)],
    ["Win rate", formatPercent(metrics.win_rate)],
    ["Expectancy", formatPercent(metrics.expectancy)],
    ["Equity final", formatAmount(metrics.final_equity)],
  ];

  return (
    <section aria-label="Métricas del backtest" className="space-y-3">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded border border-zinc-800 bg-zinc-950/50 p-3">
            <dt className="text-xs text-zinc-400">{label}</dt>
            <dd className="font-mono text-sm text-zinc-100">{value}</dd>
          </div>
        ))}
      </dl>
      {metrics.warnings.length > 0 && (
        <ul aria-label="Avisos del backtest" className="space-y-1">
          {metrics.warnings.map((warning) => (
            <li key={warning} className="text-sm text-yellow-400">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-zinc-500">El backtest no modela costes ni slippage</p>
    </section>
  );
}
