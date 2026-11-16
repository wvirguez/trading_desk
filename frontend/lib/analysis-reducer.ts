import type { components } from "@/types/api";

type AnalysisEventEnvelope = components["schemas"]["AnalysisEventEnvelope"];
export type AnalysisEvent = AnalysisEventEnvelope;

type AnalysisStep = components["schemas"]["AnalysisStep"];
export type StepUsage = components["schemas"]["StepUsage"];
type AnalysisOutcome = components["schemas"]["AnalysisOutcome"];
type AgentReportSchema = components["schemas"]["AgentReportSchema"];
type StepOutput = components["schemas"]["StepCompleted"]["output"];

export interface StepState {
  step: AnalysisStep;
  status: "pending" | "running" | "completed" | "failed";
  seq: number;
  usage: StepUsage | null;
  output: StepOutput | null;
  error: string | null;
  startedAt: string | null;
}

export interface TotalUsage {
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  costUsd: string | null;
}

export interface AnalysisState {
  analysisId: string | null;
  symbol: string | null;
  timeframe: components["schemas"]["Timeframe"] | null;
  timeframes: components["schemas"]["Timeframe"][];
  status: "idle" | "running" | "completed" | "failed" | "cancelled" | "error";
  steps: StepState[];
  totalUsage: TotalUsage;
  warnings: string[];
  outcome: AnalysisOutcome | null;
  report: AgentReportSchema | null;
  error: string | null;
  failedStep: AnalysisStep | null;
  canRetry: boolean;
  lastSeq: number;
}

export const initialAnalysisState: AnalysisState = {
  analysisId: null,
  symbol: null,
  timeframe: null,
  timeframes: [],
  status: "idle",
  steps: [],
  totalUsage: { inputTokens: 0, outputTokens: 0, latencyMs: 0, costUsd: null },
  warnings: [],
  outcome: null,
  report: null,
  error: null,
  failedStep: null,
  canRetry: false,
  lastSeq: -1,
};

function normalizeCost(cost: string): string {
  const value = Number(cost);
  if (!Number.isFinite(value) || value === 0) return "0";
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

function addUsage(total: TotalUsage, usage: StepUsage | null): TotalUsage {
  if (!usage) return total;

  const inputTokens = total.inputTokens + usage.input_tokens;
  const outputTokens = total.outputTokens + usage.output_tokens;
  const latencyMs = total.latencyMs + usage.latency_ms;
  const costUsd =
    usage.cost_usd === null || usage.cost_usd === undefined
      ? total.costUsd
      : normalizeCost(String(Number(total.costUsd ?? "0") + Number(usage.cost_usd)));

  return { inputTokens, outputTokens, latencyMs, costUsd };
}

function usageFromReport(usage: StepUsage): TotalUsage {
  return {
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    latencyMs: usage.latency_ms,
    costUsd:
      usage.cost_usd === null || usage.cost_usd === undefined
        ? null
        : normalizeCost(usage.cost_usd),
  };
}

function findStep(steps: StepState[], step: AnalysisStep): number {
  return steps.findIndex((item) => item.step === step);
}

function upsertStep(steps: StepState[], next: StepState): StepState[] {
  const index = findStep(steps, next.step);
  const copy = [...steps];
  if (index >= 0) {
    copy[index] = next;
  } else {
    copy.push(next);
  }
  return copy.sort((a, b) => a.seq - b.seq);
}

export function reduceAnalysisEvent(state: AnalysisState, event: AnalysisEvent): AnalysisState {
  if (
    event.event === "analysis_started" &&
    event.analysis_id !== state.analysisId
  ) {
    return {
      ...initialAnalysisState,
      analysisId: event.analysis_id,
      symbol: event.symbol,
      timeframe: event.timeframe,
      timeframes: event.timeframes,
      status: "running",
      lastSeq: event.seq,
    };
  }

  if (event.seq <= state.lastSeq) {
    return state;
  }

  if (state.analysisId !== null && event.analysis_id !== state.analysisId) {
    return state;
  }

  const base = { ...state, lastSeq: event.seq };

  switch (event.event) {
    case "analysis_started":
      return {
        ...base,
        analysisId: event.analysis_id,
        symbol: event.symbol,
        timeframe: event.timeframe,
        timeframes: event.timeframes,
        status: "running",
      };

    case "step_started": {
      if (base.status !== "running") return state;
      const existing = base.steps[findStep(base.steps, event.step)];
      if (existing && existing.status !== "pending") {
        return base;
      }
      const step: StepState = {
        step: event.step,
        status: "running",
        seq: event.seq,
        usage: null,
        output: null,
        error: null,
        startedAt: null,
      };
      return { ...base, steps: upsertStep(base.steps, step) };
    }

    case "step_completed": {
      if (base.status !== "running") return state;
      const index = findStep(base.steps, event.step);
      if (index < 0) return base;
      const step: StepState = {
        ...base.steps[index],
        status: "completed",
        usage: event.usage,
        output: event.output,
        error: null,
      };
      return {
        ...base,
        steps: upsertStep(base.steps, step),
        totalUsage: addUsage(base.totalUsage, event.usage),
      };
    }

    case "step_failed": {
      if (base.status !== "running") return state;
      const index = findStep(base.steps, event.step);
      if (index < 0) return base;
      const step: StepState = {
        ...base.steps[index],
        status: "failed",
        usage: event.usage ?? null,
        error: event.error,
      };
      return {
        ...base,
        steps: upsertStep(base.steps, step),
        status: "failed",
        error: event.error,
        failedStep: event.step,
        totalUsage: addUsage(base.totalUsage, event.usage ?? null),
        canRetry: true,
      };
    }

    case "analysis_completed": {
      if (base.status !== "running") return state;
      return {
        ...base,
        status: "completed",
        outcome: event.report.outcome,
        report: event.report,
        warnings: event.report.warnings ?? [],
        totalUsage: usageFromReport(event.report.usage),
        canRetry: false,
      };
    }

    case "analysis_failed": {
      if (base.status !== "running" && base.status !== "failed") return state;
      return {
        ...base,
        status: "failed",
        error: event.error,
        failedStep: event.step ?? null,
        canRetry: true,
      };
    }
  }
}
