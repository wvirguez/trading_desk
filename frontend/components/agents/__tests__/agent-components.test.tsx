import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { useTerminalStore } from "@/store/terminal";
import AnalysisForm from "@/components/agents/analysis-form";
import AnalysisFeed from "@/components/agents/analysis-feed";
import StepCard from "@/components/agents/step-card";
import {
  initialAnalysisState,
  type AnalysisState,
  type StepState,
  type StepUsage,
} from "@/lib/analysis-reducer";
import type { UseAnalysisReturn } from "@/hooks/use-analysis";
import type { components } from "@/types/api";

vi.mock("@/store/terminal");

type AgentReportSchema = components["schemas"]["AgentReportSchema"];
type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];

const ANALYSIS_ID = "123e4567-e89b-12d3-a456-426614174000";

const structureUsage: StepUsage = {
  model: "claude-sonnet",
  input_tokens: 100,
  output_tokens: 50,
  latency_ms: 200,
  cost_usd: "0.01",
};

const guardSize: components["schemas"]["PositionSizeResult"] = {
  notional: "1000",
  risk_amount: "100",
  risk_pct: "1",
  stop_distance: "1000",
  units: "0.02",
};

const approvedSignal: TradeSignalSchema = {
  id: "223e4567-e89b-12d3-a456-426614174000",
  analysis_id: ANALYSIS_ID,
  symbol: "BTC/USDT",
  asset_class: "CRYPTO",
  timeframe: "1h",
  direction: "LONG",
  entry: "50000",
  stop_loss: "49000",
  take_profit: "52500",
  rr: "2.5",
  size: guardSize,
  status: "APPROVED",
  regime: "TRENDING",
  rationale: "NO VERIFICADO: ruptura con volumen",
  veto_reasons: [],
  created_at: "2024-01-01T00:00:00Z",
};

function stateWith(overrides: Partial<AnalysisState> = {}): AnalysisState {
  return { ...initialAnalysisState, ...overrides };
}

function stepWith(overrides: Partial<StepState> & Pick<StepState, "step">): StepState {
  return {
    status: "pending",
    seq: 1,
    usage: null,
    output: null,
    error: null,
    startedAt: null,
    ...overrides,
  };
}

function reportWith(overrides: Partial<AgentReportSchema> = {}): AgentReportSchema {
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

function analysisReturn(
  state: AnalysisState,
  overrides: Partial<UseAnalysisReturn> = {},
): UseAnalysisReturn {
  return {
    state,
    start: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

function mockStore(timeframe: components["schemas"]["Timeframe"] = "1h") {
  const setSymbol = vi.fn();
  const setTimeframe = vi.fn();
  const mockUseTerminalStore = useTerminalStore as unknown as ReturnType<typeof vi.fn>;
  mockUseTerminalStore.mockReturnValue({
    symbol: "BTC/USDT",
    timeframe,
    setSymbol,
    setTimeframe,
  });
  return { setSymbol, setTimeframe };
}

describe("components/agents - AnalysisForm", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockStore();
  });

  it("muestra símbolo y timeframe desde el store", () => {
    render(<AnalysisForm analysis={analysisReturn(stateWith())} />);

    expect(screen.getByDisplayValue("BTC/USDT")).toBeInTheDocument();
    expect(screen.getByDisplayValue("1h")).toBeInTheDocument();
  });

  it("ofrece marcos por defecto (5m, 15m, 1h, 4h, 1d)", () => {
    render(<AnalysisForm analysis={analysisReturn(stateWith())} />);

    fireEvent.click(screen.getByRole("combobox", { name: /timeframe/i }));

    expect(screen.getByRole("option", { name: "5m" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "15m" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1h" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "4h" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1d" })).toBeInTheDocument();
  });

  it("botón «Analizar» deshabilitado y «Cancelar» visible mientras corre", () => {
    render(<AnalysisForm analysis={analysisReturn(stateWith({ status: "running" }))} />);

    expect(screen.getByRole("button", { name: /analizar/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancelar/i })).toBeInTheDocument();
  });

  it("botón «Analizar» habilitado y «Cancelar» oculto en idle", () => {
    render(<AnalysisForm analysis={analysisReturn(stateWith())} />);

    expect(screen.getByRole("button", { name: /analizar/i })).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: /cancelar/i })).not.toBeInTheDocument();
  });

  it("llama start con un AnalyzeRequest válido y los marcos por defecto", async () => {
    const start = vi.fn();
    render(<AnalysisForm analysis={analysisReturn(stateWith(), { start })} />);

    fireEvent.click(screen.getByRole("button", { name: /analizar/i }));

    await waitFor(() => {
      expect(start).toHaveBeenCalledWith({
        symbol: "BTC/USDT",
        timeframe: "1h",
        timeframes: ["15m", "1h", "4h", "1d"],
      });
    });
  });

  it("incluye un timeframe activo fuera de los defaults sin duplicarlo", async () => {
    mockStore("5m");
    const start = vi.fn();
    render(<AnalysisForm analysis={analysisReturn(stateWith(), { start })} />);

    fireEvent.click(screen.getByRole("button", { name: /analizar/i }));

    await waitFor(() => {
      expect(start).toHaveBeenCalledWith({
        symbol: "BTC/USDT",
        timeframe: "5m",
        timeframes: ["15m", "1h", "4h", "1d", "5m"],
      });
    });
  });

  it("muestra «Cancelado» cuando el análisis se cancela", () => {
    render(<AnalysisForm analysis={analysisReturn(stateWith({ status: "cancelled" }))} />);

    expect(screen.getByText("Cancelado")).toBeInTheDocument();
  });

  it("muestra el detail del backend sin ocultarlo", () => {
    render(
      <AnalysisForm
        analysis={analysisReturn(
          stateWith({ status: "error", error: "Instrumento no encontrado: BTC/XXX" }),
        )}
      />,
    );

    expect(screen.getByText("Instrumento no encontrado: BTC/XXX")).toBeInTheDocument();
  });
});

describe("components/agents - AnalysisFeed", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockStore();
  });

  it("muestra cada paso con modelo, tokens, latencia y coste (— si es null)", () => {
    const state = stateWith({
      status: "running",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      steps: [
        stepWith({
          step: "STRUCTURE",
          status: "completed",
          seq: 2,
          usage: structureUsage,
          output: { reasoning: "test" },
        }),
        stepWith({ step: "QUANT", status: "running", seq: 3 }),
        stepWith({ step: "PROPOSAL", seq: 4 }),
        stepWith({ step: "GUARDS", seq: 5 }),
        stepWith({ step: "RISK_AUDIT", seq: 6 }),
      ],
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    expect(screen.getByText("STRUCTURE")).toBeInTheDocument();
    expect(screen.getByText("QUANT")).toBeInTheDocument();
    expect(screen.getByText("PROPOSAL")).toBeInTheDocument();
    expect(screen.getByText("GUARDS")).toBeInTheDocument();
    expect(screen.getByText("RISK_AUDIT")).toBeInTheDocument();

    expect(screen.getByText("claude-sonnet")).toBeInTheDocument();
    expect(screen.getByText("100/50")).toBeInTheDocument();
    expect(screen.getByText("200ms")).toBeInTheDocument();
    expect(screen.getByText("$0.01")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("separa los hechos del código del texto del modelo etiquetado «Texto del modelo, no verificado»", () => {
    const structureOutput: components["schemas"]["MarketStructureReport"] = {
      symbol: "BTC/USDT",
      entry_timeframe: "1h",
      timeframes: [
        {
          timeframe: "1h",
          bias: "BULLISH",
          last_event: "BOS",
          key_levels: ["50000", "51000"],
          open_fvg_ts: [],
          comment: "Comentario de estructura",
        },
      ],
      htf_alignment: "BULLISH",
      zone_ts: null,
      invalidation_level: "49000",
      reasoning: "Análisis de estructura completado",
    };
    const guardsOutput: components["schemas"]["GuardDecision"] = {
      approved: true,
      reasons: [],
      messages: [],
      rr: "2.5",
      size: guardSize,
    };

    const state = stateWith({
      status: "completed",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      steps: [
        stepWith({
          step: "STRUCTURE",
          status: "completed",
          seq: 2,
          usage: structureUsage,
          output: structureOutput,
        }),
        stepWith({
          step: "GUARDS",
          status: "completed",
          seq: 5,
          usage: { ...structureUsage, input_tokens: 50, output_tokens: 25 },
          output: guardsOutput,
        }),
      ],
      outcome: "SIGNAL_APPROVED",
      report: reportWith({ outcome: "SIGNAL_APPROVED" }),
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    const factsBlocks = screen.getAllByTestId("code-facts");
    const proseBlocks = screen.getAllByTestId("model-prose");
    const factsText = factsBlocks.map((block) => block.textContent ?? "").join(" ");
    const proseText = proseBlocks.map((block) => block.textContent ?? "").join(" ");

    expect(screen.getAllByText("Hechos del código").length).toBeGreaterThan(0);
    expect(screen.getByText("Niveles clave:")).toBeInTheDocument();
    expect(screen.getByText("50000")).toBeInTheDocument();
    expect(screen.getByText("51000")).toBeInTheDocument();
    expect(screen.getByText("R:R:")).toBeInTheDocument();
    expect(screen.getByText("2.5")).toBeInTheDocument();
    expect(screen.getByText("Tamaño:")).toBeInTheDocument();
    expect(screen.getAllByText("1000").length).toBeGreaterThan(0);

    expect(screen.getAllByText("Texto del modelo, no verificado").length).toBeGreaterThan(0);
    expect(within(proseBlocks[0]).getByText("Análisis de estructura completado")).toBeInTheDocument();
    expect(within(proseBlocks[0]).getByText("Comentario de estructura")).toBeInTheDocument();
    expect(factsText).not.toContain("Análisis de estructura completado");
    expect(factsText).not.toContain("Comentario de estructura");
    expect(proseText).not.toContain("51000");
  });

  it("muestra el resultado final SIGNAL_APPROVED con sus niveles", () => {
    const state = stateWith({
      status: "completed",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      outcome: "SIGNAL_APPROVED",
      report: reportWith({ outcome: "SIGNAL_APPROVED", signal: approvedSignal }),
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    expect(screen.getByText("SIGNAL_APPROVED")).toBeInTheDocument();
    expect(screen.getByText("Señal aprobada")).toBeInTheDocument();
    expect(screen.getByText("50000")).toBeInTheDocument();
    expect(screen.getByText("49000")).toBeInTheDocument();
    expect(screen.getByText("52500")).toBeInTheDocument();
    expect(screen.getAllByText("Texto del modelo, no verificado").length).toBeGreaterThan(0);
  });

  it("muestra el resultado final SIGNAL_REJECTED con los motivos de veto", () => {
    const state = stateWith({
      status: "completed",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      outcome: "SIGNAL_REJECTED",
      report: reportWith({
        outcome: "SIGNAL_REJECTED",
        guards: {
          approved: false,
          messages: ["El R:R no alcanza el mínimo"],
          reasons: ["RR_BELOW_MIN"],
          rr: "1.2",
          size: null,
        },
      }),
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    expect(screen.getByText("SIGNAL_REJECTED")).toBeInTheDocument();
    expect(screen.getByText("Señal rechazada")).toBeInTheDocument();
    expect(screen.getByText("RR_BELOW_MIN")).toBeInTheDocument();
    expect(screen.getByText("El R:R no alcanza el mínimo")).toBeInTheDocument();
  });

  it("muestra el resultado final NO_TRADE con su motivo", () => {
    const state = stateWith({
      status: "completed",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      outcome: "NO_TRADE",
      report: reportWith({
        outcome: "NO_TRADE",
        quant: {
          symbol: "BTC/USDT",
          timeframe: "1h",
          regime: "HIGH_VOLATILITY_NOISE",
          stats: {
            adf_pvalue: 0.1,
            hurst: 0.6,
            n_obs: 100,
            volatility_ratio: 2.0,
            zscore: 1.5,
          },
          playbook: "NO_TRADE",
          kelly: null,
          reasoning: "Régimen no favorable",
        },
      }),
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    expect(screen.getAllByText("NO_TRADE").length).toBeGreaterThan(0);
    expect(screen.getByText("Sin operación")).toBeInTheDocument();
    expect(screen.getByText("Régimen no favorable")).toBeInTheDocument();
    expect(screen.getByText("HIGH_VOLATILITY_NOISE")).toBeInTheDocument();
  });

  it("muestra los avisos del análisis", () => {
    const state = stateWith({
      status: "completed",
      analysisId: "123",
      symbol: "BTC/USDT",
      timeframe: "1h",
      warnings: ["Aviso 1", "Aviso 2"],
      outcome: "NO_TRADE",
      report: reportWith({ outcome: "NO_TRADE", warnings: ["Aviso 1", "Aviso 2"] }),
    });

    render(<AnalysisFeed analysis={analysisReturn(state)} />);

    expect(screen.getByText("Avisos del análisis")).toBeInTheDocument();
    expect(screen.getByText("Aviso 1")).toBeInTheDocument();
    expect(screen.getByText("Aviso 2")).toBeInTheDocument();
  });

  it("muestra «Cancelado» al cancelar", () => {
    render(<AnalysisFeed analysis={analysisReturn(stateWith({ status: "cancelled" }))} />);

    expect(screen.getAllByText("Cancelado").length).toBeGreaterThan(0);
    expect(screen.getByText("Análisis cancelado por el usuario")).toBeInTheDocument();
  });
});

describe("components/agents - StepCard", () => {
  it("muestra paso con estado running/completed/failed", () => {
    render(
      <StepCard
        step="STRUCTURE"
        status="running"
        seq={2}
        usage={null}
        startedAt="2024-01-01T00:00:00Z"
      />,
    );
    expect(screen.getByText("STRUCTURE")).toBeInTheDocument();
    expect(screen.getByText("En curso")).toBeInTheDocument();

    render(
      <StepCard
        step="QUANT"
        status="completed"
        seq={3}
        usage={structureUsage}
        startedAt="2024-01-01T00:00:01Z"
      />,
    );
    expect(screen.getByText("QUANT")).toBeInTheDocument();
    expect(screen.getByText("Completado")).toBeInTheDocument();

    render(
      <StepCard
        step="PROPOSAL"
        status="failed"
        seq={4}
        usage={null}
        error="Error del modelo"
        startedAt="2024-01-01T00:00:02Z"
      />,
    );
    expect(screen.getByText("PROPOSAL")).toBeInTheDocument();
    expect(screen.getByText("Fallido")).toBeInTheDocument();
    expect(screen.getByText("Error del modelo")).toBeInTheDocument();
  });

  it("muestra modelo, tokens, latencia y coste (— si es null)", () => {
    render(
      <StepCard
        step="STRUCTURE"
        status="completed"
        seq={2}
        usage={structureUsage}
        startedAt="2024-01-01T00:00:00Z"
      />,
    );
    expect(screen.getByText("claude-sonnet")).toBeInTheDocument();
    expect(screen.getByText("100/50")).toBeInTheDocument();
    expect(screen.getByText("200ms")).toBeInTheDocument();
    expect(screen.getByText("$0.01")).toBeInTheDocument();

    render(
      <StepCard
        step="QUANT"
        status="running"
        seq={3}
        usage={null}
        startedAt="2024-01-01T00:00:01Z"
      />,
    );
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  });

  it("muestra — en el coste cuando usage existe pero cost_usd es null", () => {
    render(
      <StepCard
        step="QUANT"
        status="completed"
        seq={3}
        usage={{ ...structureUsage, cost_usd: null }}
        startedAt="2024-01-01T00:00:01Z"
      />,
    );

    expect(screen.getByText("100/50")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
