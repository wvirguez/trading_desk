"use client";

import { Badge } from "@/components/ui/badge";
import type { StepState, StepUsage } from "@/lib/analysis-reducer";

export interface StepCardProps {
  step: StepState["step"];
  status: StepState["status"];
  seq: number;
  usage: StepUsage | null;
  error?: string | null;
  startedAt: string | null;
}

const STATUS_LABELS: Record<StepState["status"], string> = {
  pending: "Pendiente",
  running: "En curso",
  completed: "Completado",
  failed: "Fallido",
};

const STATUS_VARIANTS: Record<
  StepState["status"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  pending: "outline",
  running: "default",
  completed: "secondary",
  failed: "destructive",
};

function formatCost(cost: string | null | undefined): string {
  if (cost === null || cost === undefined) return "—";
  const value = Number(cost);
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "$0.00";
  if (value < 0.01) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

function formatTokens(usage: StepUsage | null): string {
  if (!usage) return "—";
  return `${usage.input_tokens}/${usage.output_tokens}`;
}

function formatLatency(usage: StepUsage | null): string {
  if (!usage) return "—";
  return `${usage.latency_ms}ms`;
}

export default function StepCard({
  step,
  status,
  seq,
  usage,
  error,
  startedAt,
}: StepCardProps) {
  return (
    <div className="border border-zinc-800 rounded-lg bg-zinc-950/50 overflow-hidden">
      <div className="flex items-center gap-3 p-3 bg-zinc-900/50 border-b border-zinc-800">
        <span className="text-xs text-zinc-500 font-mono w-6 text-right">#{seq}</span>
        <span className="font-mono text-sm font-medium text-zinc-100 min-w-[100px]">{step}</span>
        <Badge variant={STATUS_VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
        {startedAt && (
          <span className="text-xs text-zinc-500 ml-auto font-mono">
            {new Date(startedAt).toLocaleTimeString()}
          </span>
        )}
      </div>

      <div className="p-3 space-y-2">
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div>
            <span className="text-zinc-500">Modelo:</span>
            <span className="text-zinc-300 ml-1 font-mono">{usage?.model ?? "—"}</span>
          </div>
          <div>
            <span className="text-zinc-500">Tokens:</span>
            <span className="text-zinc-300 ml-1 font-mono">{formatTokens(usage)}</span>
          </div>
          <div>
            <span className="text-zinc-500">Latencia:</span>
            <span className="text-zinc-300 ml-1 font-mono">{formatLatency(usage)}</span>
          </div>
          <div>
            <span className="text-zinc-500">Coste:</span>
            <span className="text-zinc-300 ml-1 font-mono">{formatCost(usage?.cost_usd)}</span>
          </div>
        </div>

        {error && (
          <div className="text-sm text-red-400 p-2 bg-red-950/30 border border-red-900/50 rounded">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
