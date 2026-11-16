import { describe, it, expect } from "vitest";
import {
  initialAnalysisState,
  reduceAnalysisEvent,
  type AnalysisEvent,
  type AnalysisState,
  type StepUsage,
} from "../analysis-reducer";
import type { components } from "@/types/api";

const ANALYSIS_ID = "123e4567-e89b-12d3-a456-426614174000";

const structureUsage: StepUsage = {
  model: "claude-sonnet",
  input_tokens: 100,
  output_tokens: 50,
  latency_ms: 200,
  cost_usd: "0.01",
};

const quantUsage: StepUsage = {
  model: "claude-sonnet",
  input_tokens: 200,
  output_tokens: 100,
  latency_ms: 300,
  cost_usd: "0.02",
};

const started: components["schemas"]["AnalysisStarted"] = {
  event: "analysis_started",
  analysis_id: ANALYSIS_ID,
  seq: 1,
  started_at: "2024-01-01T00:00:00Z",
  symbol: "BTC/USDT",
  timeframe: "1h",
  timeframes: ["15m", "1h", "4h", "1d"],
};

function apply(events: AnalysisEvent[]): AnalysisState {
  return events.reduce(reduceAnalysisEvent, initialAnalysisState);
}

function report(
  overrides: Partial<components["schemas"]["AgentReportSchema"]> = {},
): components["schemas"]["AgentReportSchema"] {
  return {
    analysis_id: ANALYSIS_ID,
    symbol: "BTC/USDT",
    timeframe: "1h",
    outcome: "SIGNAL_APPROVED",
    usage: structureUsage,
    warnings: [],
    ...overrides,
  };
}

describe("lib/analysis-reducer.ts - reduceAnalysisEvent", () => {
  it("construye el estado para analysis_started", () => {
    const state = reduceAnalysisEvent(initialAnalysisState, started);

    expect(state.analysisId).toBe(ANALYSIS_ID);
    expect(state.symbol).toBe("BTC/USDT");
    expect(state.timeframe).toBe("1h");
    expect(state.timeframes).toEqual(["15m", "1h", "4h", "1d"]);
    expect(state.steps).toEqual([]);
    expect(state.status).toBe("running");
    expect(state.lastSeq).toBe(1);
  });

  it("construye el estado para step_started", () => {
    const state = apply([
      started,
      {
        event: "step_started",
        analysis_id: ANALYSIS_ID,
        seq: 2,
        step: "STRUCTURE",
      },
    ]);

    expect(state.steps).toHaveLength(1);
    expect(state.steps[0].step).toBe("STRUCTURE");
    expect(state.steps[0].status).toBe("running");
    expect(state.steps[0].seq).toBe(2);
  });

  it("construye el estado para step_completed con usage por paso", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "STRUCTURE" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 3,
        step: "STRUCTURE",
        output: { reasoning: "estructura" },
        usage: structureUsage,
      },
    ]);

    expect(state.steps[0].status).toBe("completed");
    expect(state.steps[0].usage).toEqual(structureUsage);
    expect(state.steps[0].output).toEqual({ reasoning: "estructura" });
    expect(state.totalUsage.inputTokens).toBe(100);
    expect(state.totalUsage.outputTokens).toBe(50);
    expect(state.totalUsage.latencyMs).toBe(200);
    expect(state.totalUsage.costUsd).toBe("0.01");
  });

  it("construye el estado para step_failed con paso y mensaje", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "QUANT" },
      {
        event: "step_failed",
        analysis_id: ANALYSIS_ID,
        seq: 3,
        step: "QUANT",
        error: "El modelo agotó el tiempo máximo",
        usage: null,
      },
    ]);

    expect(state.steps[0].status).toBe("failed");
    expect(state.steps[0].error).toBe("El modelo agotó el tiempo máximo");
    expect(state.status).toBe("failed");
    expect(state.failedStep).toBe("QUANT");
    expect(state.canRetry).toBe(true);
  });

  it("construye el estado para analysis_completed con outcome, informe y avisos", () => {
    const agentReport = report({
      outcome: "SIGNAL_REJECTED",
      warnings: ["Aviso 1", "Aviso 2"],
    });
    const state = apply([
      started,
      {
        event: "analysis_completed",
        analysis_id: ANALYSIS_ID,
        seq: 2,
        report: agentReport,
      },
    ]);

    expect(state.status).toBe("completed");
    expect(state.outcome).toBe("SIGNAL_REJECTED");
    expect(state.report).toEqual(agentReport);
    expect(state.warnings).toEqual(["Aviso 1", "Aviso 2"]);
    expect(state.canRetry).toBe(false);
  });

  it("construye el estado para analysis_failed", () => {
    const state = apply([
      started,
      {
        event: "analysis_failed",
        analysis_id: ANALYSIS_ID,
        seq: 2,
        error: "Error interno del análisis: Modelo no disponible",
        step: "PROPOSAL",
      },
    ]);

    expect(state.status).toBe("failed");
    expect(state.error).toBe("Error interno del análisis: Modelo no disponible");
    expect(state.failedStep).toBe("PROPOSAL");
    expect(state.canRetry).toBe(true);
  });

  it("procesa la secuencia completa de los cinco pasos y el informe final", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "STRUCTURE" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 3,
        step: "STRUCTURE",
        output: {},
        usage: structureUsage,
      },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 4, step: "QUANT" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 5,
        step: "QUANT",
        output: {},
        usage: quantUsage,
      },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 6, step: "PROPOSAL" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 7,
        step: "PROPOSAL",
        output: {},
        usage: quantUsage,
      },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 8, step: "GUARDS" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 9,
        step: "GUARDS",
        output: {},
        usage: structureUsage,
      },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 10, step: "RISK_AUDIT" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 11,
        step: "RISK_AUDIT",
        output: {},
        usage: quantUsage,
      },
      {
        event: "analysis_completed",
        analysis_id: ANALYSIS_ID,
        seq: 12,
        report: report({
          outcome: "NO_TRADE",
          usage: {
            input_tokens: 850,
            output_tokens: 400,
            latency_ms: 1500,
            cost_usd: "0.09",
          },
        }),
      },
    ]);

    expect(state.steps.map((step) => step.step)).toEqual([
      "STRUCTURE",
      "QUANT",
      "PROPOSAL",
      "GUARDS",
      "RISK_AUDIT",
    ]);
    expect(state.steps.map((step) => step.status)).toEqual([
      "completed",
      "completed",
      "completed",
      "completed",
      "completed",
    ]);
    expect(state.steps.map((step) => step.seq)).toEqual([2, 4, 6, 8, 10]);
    expect(state.status).toBe("completed");
    expect(state.outcome).toBe("NO_TRADE");
    expect(state.report).not.toBeNull();
  });

  it("ordena los pasos por seq", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "QUANT" },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 3, step: "STRUCTURE" },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 4, step: "PROPOSAL" },
    ]);

    expect(state.steps.map((step) => step.seq)).toEqual([2, 3, 4]);
  });

  it("usa el usage del informe como total final sin duplicar el de los pasos", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "STRUCTURE" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 3,
        step: "STRUCTURE",
        output: {},
        usage: structureUsage,
      },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 4, step: "QUANT" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 5,
        step: "QUANT",
        output: {},
        usage: quantUsage,
      },
      {
        event: "analysis_completed",
        analysis_id: ANALYSIS_ID,
        seq: 6,
        report: report({
          usage: {
            input_tokens: 300,
            output_tokens: 150,
            latency_ms: 500,
            cost_usd: "0.03",
          },
        }),
      },
    ]);

    expect(state.totalUsage).toEqual({
      inputTokens: 300,
      outputTokens: 150,
      latencyMs: 500,
      costUsd: "0.03",
    });
  });

  it("mantiene el total de coste nulo si ningún paso ni el informe lo conocen", () => {
    const usageWithoutCost: StepUsage = {
      model: "claude-sonnet",
      input_tokens: 10,
      output_tokens: 5,
      latency_ms: 20,
      cost_usd: null,
    };
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "QUANT" },
      {
        event: "step_completed",
        analysis_id: ANALYSIS_ID,
        seq: 3,
        step: "QUANT",
        output: {},
        usage: usageWithoutCost,
      },
      {
        event: "analysis_completed",
        analysis_id: ANALYSIS_ID,
        seq: 4,
        report: report({ usage: usageWithoutCost }),
      },
    ]);

    expect(state.totalUsage.costUsd).toBeNull();
  });

  it("descarta eventos con seq repetido", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "STRUCTURE" },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "QUANT" },
    ]);

    expect(state.steps).toHaveLength(1);
    expect(state.steps[0].step).toBe("STRUCTURE");
  });

  it("descarta eventos con seq anterior al último aceptado", () => {
    const state = apply([
      started,
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 4, step: "STRUCTURE" },
      { event: "step_started", analysis_id: ANALYSIS_ID, seq: 2, step: "QUANT" },
    ]);

    expect(state.steps).toHaveLength(1);
    expect(state.steps[0].step).toBe("STRUCTURE");
    expect(state.lastSeq).toBe(4);
  });

  it("descarta eventos de otro análisis", () => {
    const otherAnalysis: components["schemas"]["StepStarted"] = {
      event: "step_started",
      analysis_id: "00000000-0000-0000-0000-000000000000",
      seq: 99,
      step: "QUANT",
    };
    const state = reduceAnalysisEvent(
      reduceAnalysisEvent(initialAnalysisState, started),
      otherAnalysis,
    );

    expect(state.steps).toEqual([]);
    expect(state.lastSeq).toBe(1);
  });
});
