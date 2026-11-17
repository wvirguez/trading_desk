import { formatPrice } from "@/lib/format";
import type { components } from "@/types/api";

type BlotterSchema = components["schemas"]["BlotterSchema"];

const AMOUNT_STEP = "0.01";

interface AccountSummaryProps {
  blotter: BlotterSchema;
}

export function AccountSummary({ blotter }: AccountSummaryProps) {
  const items: { label: string; value: string }[] = [
    { label: "Equity", value: formatPrice(blotter.equity, AMOUNT_STEP) },
    { label: "PnL del día", value: formatPrice(blotter.realized_pnl_today, AMOUNT_STEP) },
    { label: "PnL no realizado", value: formatPrice(blotter.unrealized_pnl_total, AMOUNT_STEP) },
    { label: "Riesgo abierto", value: formatPrice(blotter.open_risk, AMOUNT_STEP) },
  ];

  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Resumen de cuenta">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border border-zinc-700 bg-zinc-900/50 p-3">
          <dt className="text-xs text-zinc-400">{item.label}</dt>
          <dd className="font-mono text-sm text-white">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
