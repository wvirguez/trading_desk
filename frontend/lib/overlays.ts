import type { components } from "@/types/api";

type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];
type FairValueGap = components["schemas"]["FairValueGap"];
type Direction = components["schemas"]["Direction"];

export interface SignalOverlay {
  id: string;
  symbol: string;
  timeframe: string;
  direction: Direction;
  status: components["schemas"]["SignalStatus"];
  levels: Array<{ price: string; label: string }>;
  zone: { top: string; bottom: string; direction: Direction };
  rr: string;
  rationale: string;
}

export interface FvgBox {
  top: string;
  bottom: string;
  left: number;
  right: number;
  direction: Direction;
  color: string;
  borderWidth: number;
  borderStyle: number;
  borderColor: string;
  mitigated: boolean;
  ts: string;
}

export function signalToOverlay(signal: TradeSignalSchema): SignalOverlay {
  const entry = signal.entry;
  const stopLoss = signal.stop_loss;
  const takeProfit = signal.take_profit;

  const isLong = signal.direction === "LONG";

  const zoneTop = isLong ? entry : stopLoss;
  const zoneBottom = isLong ? stopLoss : entry;

  return {
    id: signal.id,
    symbol: signal.symbol,
    timeframe: signal.timeframe,
    direction: signal.direction,
    status: signal.status,
    levels: [
      { price: entry, label: "Entrada" },
      { price: stopLoss, label: "SL" },
      { price: takeProfit, label: "TP" },
    ],
    zone: {
      top: zoneTop,
      bottom: zoneBottom,
      direction: signal.direction,
    },
    rr: signal.rr,
    rationale: signal.rationale,
  };
}

export function fvgToBox(
  fvg: FairValueGap,
): FvgBox | null {
  if (fvg.direction === "LONG" && fvg.low && fvg.high) {
    const isMitigated = fvg.mitigated_at !== null && fvg.mitigated_at !== undefined;

    return {
      top: fvg.high,
      bottom: fvg.low,
      left: 0,
      right: 0,
      direction: "LONG",
      color: isMitigated
        ? "rgba(38, 166, 154, 0.3)"
        : "rgba(38, 166, 154, 0.5)",
      borderWidth: 1,
      borderStyle: isMitigated ? 2 : 0,
      borderColor: isMitigated
        ? "rgba(38, 166, 154, 0.8)"
        : "rgba(38, 166, 154, 0.8)",
      mitigated: isMitigated,
      ts: fvg.ts,
    };
  }

  if (fvg.direction === "SHORT" && fvg.low && fvg.high) {
    const isMitigated = fvg.mitigated_at !== null && fvg.mitigated_at !== undefined;

    return {
      top: fvg.high,
      bottom: fvg.low,
      left: 0,
      right: 0,
      direction: "SHORT",
      color: isMitigated
        ? "rgba(239, 83, 80, 0.3)"
        : "rgba(239, 83, 80, 0.5)",
      borderWidth: 1,
      borderStyle: isMitigated ? 2 : 0,
      borderColor: isMitigated
        ? "rgba(239, 83, 80, 0.8)"
        : "rgba(239, 83, 80, 0.8)",
      mitigated: isMitigated,
      ts: fvg.ts,
    };
  }

  return null;
}