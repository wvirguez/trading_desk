"use client";

import { useAnalysis, type UseAnalysisReturn } from "@/hooks/use-analysis";
import StepCard from "./step-card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AnalysisState, StepState, TotalUsage } from "@/lib/analysis-reducer";
import type { components } from "@/types/api";

type MarketStructureReport = components["schemas"]["MarketStructureReport"];
type QuantAlphaReport = components["schemas"]["QuantAlphaReport"];
type ProposedSignal = components["schemas"]["ProposedSignal"];
type GuardDecision = components["schemas"]["GuardDecision"];
type RiskVerdict = components["schemas"]["RiskVerdict"];
type AgentReportSchema = components["schemas"]["AgentReportSchema"];
type StepOutput = StepState["output"];

const STEP_ORDER: StepState["step"][] = [
  "STRUCTURE",
  "QUANT",
  "PROPOSAL",
  "GUARDS",
  "RISK_AUDIT",
];

const STEP_LABELS: Record<StepState["step"], string> = {
  STRUCTURE: "Estructura",
  QUANT: "Cuantitativo",
  PROPOSAL: "Propuesta",
  GUARDS: "Guardias",
  RISK_AUDIT: "Auditoría de riesgo",
};

const STATUS_LABELS: Record<AnalysisState["status"], string> = {
  idle: "Inactivo",
  running: "En curso",
  completed: "Completado",
  failed: "Fallido",
  cancelled: "Cancelado",
  error: "Error",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readMarketStructure(output: StepOutput): MarketStructureReport | null {
  if (
    !isRecord(output) ||
    !Array.isArray(output.timeframes) ||
    typeof output.reasoning !== "string"
  ) {
    return null;
  }
  return output as unknown as MarketStructureReport;
}

function readQuant(output: StepOutput): QuantAlphaReport | null {
  if (
    !isRecord(output) ||
    typeof output.playbook !== "string" ||
    typeof output.regime !== "string" ||
    !isRecord(output.stats) ||
    typeof output.reasoning !== "string"
  ) {
    return null;
  }
  return output as unknown as QuantAlphaReport;
}

function readProposal(output: StepOutput): ProposedSignal | null {
  if (
    !isRecord(output) ||
    typeof output.direction !== "string" ||
    typeof output.entry !== "string" ||
    typeof output.stop_loss !== "string" ||
    typeof output.take_profit !== "string" ||
    typeof output.rr !== "string"
  ) {
    return null;
  }
  return output as unknown as ProposedSignal;
}

function readGuard(output: StepOutput): GuardDecision | null {
  if (
    !isRecord(output) ||
    typeof output.approved !== "boolean" ||
    !Array.isArray(output.reasons) ||
    !Array.isArray(output.messages)
  ) {
    return null;
  }
  return output as unknown as GuardDecision;
}

function readRiskVerdict(output: StepOutput): RiskVerdict | null {
  if (
    !isRecord(output) ||
    typeof output.decision !== "string" ||
    !isRecord(output.deterministic) ||
    !Array.isArray(output.concerns) ||
    typeof output.rationale !== "string"
  ) {
    return null;
  }
  return output as unknown as RiskVerdict;
}

function formatCost(cost: string | null | undefined): string {
  if (cost === null || cost === undefined) return "—";
  const value = Number(cost);
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "$0.00";
  if (value < 0.01) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

function FactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="text-zinc-400 font-medium">{label}</span>
      <span className="text-zinc-200 font-mono break-words">{children}</span>
    </div>
  );
}

function ListRow({
  label,
  items,
  tone = "text-zinc-200",
}: {
  label: string;
  items: string[];
  tone?: string;
}) {
  return (
    <div className="text-sm">
      <span className="text-zinc-400 font-medium">{label}</span>
      <ul className="ml-4 mt-1 space-y-1 font-mono">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className={tone}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ModelProse({ texts }: { texts: (string | null | undefined)[] }) {
  const paragraphs = texts.filter(
    (text): text is string => typeof text === "string" && text.trim().length > 0,
  );
  if (paragraphs.length === 0) return null;

  return (
    <div data-testid="model-prose" className="mt-3 p-3 bg-zinc-900/50 border border-zinc-800 rounded">
      <div className="flex items-center gap-2 text-xs text-zinc-500 mb-2">
        <span className="text-orange-400">⚠</span>
        <span className="font-medium">Texto del modelo, no verificado</span>
      </div>
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          className="text-zinc-300 text-sm italic whitespace-pre-wrap"
        >
          {paragraph}
        </p>
      ))}
    </div>
  );
}

function SizeFacts({ size }: { size: NonNullable<GuardDecision["size"]> }) {
  return (
    <div className="text-sm">
      <span className="text-zinc-400 font-medium">Tamaño:</span>
      <ul className="ml-4 mt-1 space-y-1 font-mono text-zinc-200">
        <li>
          Nocional: <span>{size.notional}</span>
        </li>
        <li>
          Riesgo: <span>{size.risk_amount}</span> (<span>{size.risk_pct}</span>%)
        </li>
        <li>
          Distancia al stop: <span>{size.stop_distance}</span>
        </li>
        <li>
          Unidades: <span>{size.units}</span>
        </li>
      </ul>
    </div>
  );
}

function GuardFacts({ guard }: { guard: GuardDecision }) {
  return (
    <div className="space-y-2">
      <FactRow label="Aprobado:">
        <Badge variant={guard.approved ? "secondary" : "destructive"}>
          {guard.approved ? "Sí" : "No"}
        </Badge>
      </FactRow>
      {guard.rr !== null && guard.rr !== undefined && (
        <FactRow label="R:R:">{guard.rr}</FactRow>
      )}
      {guard.size && <SizeFacts size={guard.size} />}
      {guard.reasons.length > 0 && (
        <ListRow label="Motivos de veto:" items={guard.reasons} tone="text-red-400" />
      )}
      {guard.messages.length > 0 && (
        <ListRow label="Mensajes:" items={guard.messages} />
      )}
    </div>
  );
}

function StructureFacts({ report }: { report: MarketStructureReport }) {
  return (
    <div className="space-y-2">
      <FactRow label="Alineación HTF:">{report.htf_alignment}</FactRow>
      <FactRow label="Marco de entrada:">{report.entry_timeframe}</FactRow>
      {report.invalidation_level !== null && report.invalidation_level !== undefined && (
        <FactRow label="Invalidación:">{report.invalidation_level}</FactRow>
      )}
      {report.zone_ts !== null && report.zone_ts !== undefined && (
        <FactRow label="Zona FVG:">{report.zone_ts}</FactRow>
      )}
      {report.timeframes.map((item) => (
        <div key={item.timeframe} className="border-l border-zinc-800 pl-3 space-y-1">
          <FactRow label="Marco:">{item.timeframe}</FactRow>
          <FactRow label="Sesgo:">{item.bias}</FactRow>
          {item.last_event && <FactRow label="Último evento:">{item.last_event}</FactRow>}
          {item.key_levels.length > 0 && (
            <ListRow label="Niveles clave:" items={item.key_levels} />
          )}
        </div>
      ))}
    </div>
  );
}

function QuantFacts({ report }: { report: QuantAlphaReport }) {
  return (
    <div className="space-y-2">
      <FactRow label="Régimen:">{report.regime}</FactRow>
      <FactRow label="Playbook:">{report.playbook}</FactRow>
      <FactRow label="ADF p-valor:">{String(report.stats.adf_pvalue)}</FactRow>
      <FactRow label="Hurst:">{String(report.stats.hurst)}</FactRow>
      <FactRow label="Observaciones:">{String(report.stats.n_obs)}</FactRow>
      <FactRow label="Ratio de volatilidad:">{String(report.stats.volatility_ratio)}</FactRow>
      <FactRow label="Z-score:">{String(report.stats.zscore)}</FactRow>
      {report.kelly && (
        <FactRow label="Kelly:">
          {String(report.kelly.fraction)} ({report.kelly.capped ? "capped" : "full"})
        </FactRow>
      )}
    </div>
  );
}

function ProposalFacts({ proposal }: { proposal: ProposedSignal }) {
  return (
    <div className="space-y-2">
      <FactRow label="Dirección:">{proposal.direction}</FactRow>
      <FactRow label="Entrada:">{proposal.entry}</FactRow>
      <FactRow label="Stop Loss:">{proposal.stop_loss}</FactRow>
      <FactRow label="Take Profit:">{proposal.take_profit}</FactRow>
      <FactRow label="R:R:">{proposal.rr}</FactRow>
      <FactRow label="Fuente:">{proposal.source}</FactRow>
    </div>
  );
}

function RiskVerdictFacts({ verdict }: { verdict: RiskVerdict }) {
  return (
    <div className="space-y-2">
      <FactRow label="Decisión:">
        <Badge variant={verdict.decision === "APPROVE" ? "secondary" : "destructive"}>
          {verdict.decision}
        </Badge>
      </FactRow>
      <GuardFacts guard={verdict.deterministic} />
    </div>
  );
}

function renderCodeFacts(step: StepState["step"], output: StepOutput): React.ReactNode {
  switch (step) {
    case "STRUCTURE": {
      const report = readMarketStructure(output);
      return report ? <StructureFacts report={report} /> : null;
    }
    case "QUANT": {
      const report = readQuant(output);
      return report ? <QuantFacts report={report} /> : null;
    }
    case "PROPOSAL": {
      const proposal = readProposal(output);
      return proposal ? <ProposalFacts proposal={proposal} /> : null;
    }
    case "GUARDS": {
      const guard = readGuard(output);
      return guard ? <GuardFacts guard={guard} /> : null;
    }
    case "RISK_AUDIT": {
      const verdict = readRiskVerdict(output);
      return verdict ? <RiskVerdictFacts verdict={verdict} /> : null;
    }
  }
}

function modelProseTexts(step: StepState["step"], output: StepOutput): (string | null | undefined)[] {
  switch (step) {
    case "STRUCTURE": {
      const report = readMarketStructure(output);
      return report
        ? [report.reasoning, ...report.timeframes.map((item) => item.comment)]
        : [];
    }
    case "QUANT": {
      const report = readQuant(output);
      return report ? [report.reasoning] : [];
    }
    case "PROPOSAL":
      return [];
    case "GUARDS":
      return [];
    case "RISK_AUDIT": {
      const verdict = readRiskVerdict(output);
      return verdict ? [verdict.rationale, ...verdict.concerns] : [];
    }
  }
}

function OutcomeBlock({ report }: { report: AgentReportSchema }) {
  if (report.outcome === "SIGNAL_APPROVED") {
    const signal = report.signal;
    return (
      <div className="mt-4 p-4 bg-green-950/30 border border-green-900/50 rounded-lg space-y-2">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="secondary" className="text-lg">
            SIGNAL_APPROVED
          </Badge>
          <span className="text-green-400 font-medium">Señal aprobada</span>
        </div>
        {signal && (
          <>
            <FactRow label="Dirección:">{signal.direction}</FactRow>
            <FactRow label="Entrada:">{signal.entry}</FactRow>
            <FactRow label="Stop Loss:">{signal.stop_loss}</FactRow>
            <FactRow label="Take Profit:">{signal.take_profit}</FactRow>
            <FactRow label="R:R:">{signal.rr}</FactRow>
            {signal.size ? (
              <SizeFacts size={signal.size} />
            ) : (
              <FactRow label="Tamaño:">—</FactRow>
            )}
            <FactRow label="Motivos de veto:">{signal.veto_reasons.length}</FactRow>
          </>
        )}
        {signal && <ModelProse texts={[signal.rationale]} />}
      </div>
    );
  }

  if (report.outcome === "SIGNAL_REJECTED") {
    const guard = report.guards;
    const reasons = guard?.reasons ?? report.signal?.veto_reasons ?? [];
    const messages = guard?.messages ?? [];
    return (
      <div className="mt-4 p-4 bg-red-950/30 border border-red-900/50 rounded-lg space-y-2">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="destructive" className="text-lg">
            SIGNAL_REJECTED
          </Badge>
          <span className="text-red-400 font-medium">Señal rechazada</span>
        </div>
        {guard && <FactRow label="Aprobado:">{guard.approved ? "Sí" : "No"}</FactRow>}
        {guard?.rr !== null && guard?.rr !== undefined && (
          <FactRow label="R:R:">{guard.rr}</FactRow>
        )}
        {reasons.length > 0 ? (
          <ListRow label="Motivos de veto:" items={reasons} tone="text-red-400" />
        ) : (
          <p className="text-sm text-zinc-400">Sin motivos deterministas registrados.</p>
        )}
        {messages.length > 0 && <ListRow label="Mensajes:" items={messages} />}
        {report.signal?.rationale && <ModelProse texts={[report.signal.rationale]} />}
      </div>
    );
  }

  const reason = report.quant?.reasoning ?? report.structure?.reasoning ?? null;
  return (
    <div className="mt-4 p-4 bg-yellow-950/30 border border-yellow-900/50 rounded-lg space-y-2">
      <div className="flex items-center gap-2 mb-2">
        <Badge variant="outline" className="text-lg border-yellow-700 text-yellow-400">
          NO_TRADE
        </Badge>
        <span className="text-yellow-400 font-medium">Sin operación</span>
      </div>
      {report.quant && (
        <>
          <FactRow label="Playbook:">{report.quant.playbook}</FactRow>
          <FactRow label="Régimen:">{report.quant.regime}</FactRow>
        </>
      )}
      {reason ? (
        <ModelProse texts={[reason]} />
      ) : (
        <p className="text-sm text-zinc-400">El backend no registró un motivo textual.</p>
      )}
    </div>
  );
}

function TotalUsageBlock({ usage, hasUsage }: { usage: TotalUsage; hasUsage: boolean }) {
  return (
    <div className="mt-4 p-3 bg-zinc-900/50 border border-zinc-800 rounded-lg">
      <div className="text-sm font-medium text-zinc-300 mb-2">Uso total</div>
      <div className="grid grid-cols-4 gap-2 text-xs">
        <div>
          <span className="text-zinc-500">Tokens:</span>
          <span className="ml-1 text-zinc-300 font-mono">
            {hasUsage ? `${usage.inputTokens}/${usage.outputTokens}` : "—"}
          </span>
        </div>
        <div>
          <span className="text-zinc-500">Latencia:</span>
          <span className="ml-1 text-zinc-300 font-mono">
            {hasUsage ? `${usage.latencyMs}ms` : "—"}
          </span>
        </div>
        <div>
          <span className="text-zinc-500">Coste:</span>
          <span className="ml-1 text-zinc-300 font-mono">{formatCost(usage.costUsd)}</span>
        </div>
      </div>
    </div>
  );
}

interface AnalysisFeedProps {
  analysis?: UseAnalysisReturn;
}

export default function AnalysisFeed({ analysis }: AnalysisFeedProps) {
  const fallback = useAnalysis();
  const { state } = analysis ?? fallback;

  if (state.status === "idle") {
    return (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        <p>Configura los parámetros y pulsa «Analizar» para iniciar el análisis.</p>
      </div>
    );
  }

  const hasUsage = state.steps.some((step) => step.usage !== null) || state.report !== null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-4 border-b border-zinc-800 bg-zinc-950/50">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold">Feed de razonamiento</h2>
          <span className="text-sm text-zinc-400 font-mono">
            {state.symbol} · {state.timeframe}
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Badge
            variant={
              state.status === "running"
                ? "default"
                : state.status === "completed"
                  ? "secondary"
                  : state.status === "cancelled"
                    ? "outline"
                    : "destructive"
            }
          >
            {STATUS_LABELS[state.status]}
          </Badge>
          {state.analysisId && (
            <span className="text-zinc-500 font-mono text-xs">
              {state.analysisId.slice(0, 8)}…
            </span>
          )}
          {state.warnings.length > 0 && (
            <Badge variant="outline" className="text-yellow-400 border-yellow-700">
              {state.warnings.length} avisos
            </Badge>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {STEP_ORDER.map((step, index) => {
            const stepState: StepState = state.steps.find((item) => item.step === step) ?? {
              step,
              status: "pending",
              seq: index + 1,
              usage: null,
              output: null,
              error: null,
              startedAt: null,
            };

            return (
              <div key={step} className="space-y-3">
                <StepCard
                  step={stepState.step}
                  status={stepState.status}
                  seq={stepState.seq}
                  usage={stepState.usage}
                  error={stepState.error}
                  startedAt={stepState.startedAt}
                />
                {stepState.status === "completed" && stepState.output && (
                  <div className="ml-10 space-y-3">
                    <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
                      Hechos del código
                    </div>
                    <div data-testid="code-facts">
                      {renderCodeFacts(stepState.step, stepState.output)}
                    </div>
                    <ModelProse
                      texts={modelProseTexts(stepState.step, stepState.output)}
                    />
                  </div>
                )}
              </div>
            );
          })}

          {state.warnings.length > 0 && (
            <div className="p-3 bg-yellow-950/20 border border-yellow-900/40 rounded-lg">
              <div className="text-sm font-medium text-yellow-400 mb-1">Avisos del análisis</div>
              <ListRow label="" items={state.warnings} />
            </div>
          )}

          {state.status === "completed" && state.report && (
            <>
              <Separator />
              <OutcomeBlock report={state.report} />
              <TotalUsageBlock usage={state.totalUsage} hasUsage={hasUsage} />
            </>
          )}

          {(state.status === "failed" || state.status === "error") && state.error && (
            <div className="mt-4 p-4 bg-red-950/30 border border-red-900/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="destructive">{STATUS_LABELS[state.status]}</Badge>
                <span className="text-red-400 font-medium">{state.error}</span>
              </div>
              {state.failedStep && (
                <p className="text-sm text-zinc-400">
                  Paso fallido: {STEP_LABELS[state.failedStep]}
                </p>
              )}
            </div>
          )}

          {state.status === "cancelled" && (
            <div className="mt-4 p-4 bg-yellow-950/30 border border-yellow-900/50 rounded-lg">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="border-yellow-700 text-yellow-400">
                  Cancelado
                </Badge>
                <span className="text-yellow-400 font-medium">
                  Análisis cancelado por el usuario
                </span>
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
