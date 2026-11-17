import { formatAmount, formatPercent } from "@/lib/format";
import type { components } from "@/types/api";

type JournalSummarySchema = components["schemas"]["JournalSummarySchema"];

interface JournalSummaryProps {
  summary: JournalSummarySchema;
}

export default function JournalSummary({ summary }: JournalSummaryProps) {
  const rows: Array<[string, string]> = [
    ["Señales", String(summary.n_signals)],
    ["Aprobadas", String(summary.n_approved)],
    ["Rechazadas", String(summary.n_rejected)],
    ["Ejecutadas", String(summary.n_executed)],
    ["Cerradas", String(summary.n_closed)],
    ["Ganadoras", String(summary.n_wins)],
    ["Perdedoras", String(summary.n_losses)],
    ["Win rate", formatPercent(summary.win_rate)],
    ["PnL total", formatAmount(summary.total_pnl)],
    ["R:R emitido", formatAmount(summary.avg_rr_emitted)],
    ["R realizado", formatAmount(summary.avg_r_realized)],
    ["Expectancy (R)", formatAmount(summary.expectancy_r)],
  ];

  return (
    <section aria-label="Resumen del diario" className="space-y-3">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded border border-zinc-800 bg-zinc-950/50 p-3">
            <dt className="text-xs text-zinc-400">{label}</dt>
            <dd className="font-mono text-sm text-zinc-100">{value}</dd>
          </div>
        ))}
      </dl>
      {summary.warnings.length > 0 && (
        <ul aria-label="Avisos del diario" className="space-y-1">
          {summary.warnings.map((warning) => (
            <li key={warning} className="text-sm text-yellow-400">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-zinc-500">
        El diario es una ayuda de análisis, no una promesa de rentabilidad.
      </p>
    </section>
  );
}
