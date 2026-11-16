import { create } from "zustand";
import type { components } from "@/types/api";

type Timeframe = "5m" | "15m" | "1h" | "4h" | "1d";
type InstrumentSchema = components["schemas"]["InstrumentSchema"];

const VALID_TIMEFRAMES: Timeframe[] = ["5m", "15m", "1h", "4h", "1d"];

interface TerminalState {
  symbol: string;
  timeframe: Timeframe;
  instruments: InstrumentSchema[];
  setSymbol: (symbol: string) => void;
  setTimeframe: (timeframe: string) => void;
  setInstruments: (instruments: InstrumentSchema[]) => void;
}

export const useTerminalStore = create<TerminalState>()((set) => ({
  symbol: "BTC/USDT",
  timeframe: "1h",
  instruments: [],
  setSymbol: (symbol: string) => set({ symbol }),
  setTimeframe: (timeframe: string) => {
    if (!VALID_TIMEFRAMES.includes(timeframe as Timeframe)) {
      throw new Error(`Timeframe inválido: ${timeframe}. Valores permitidos: ${VALID_TIMEFRAMES.join(", ")}`);
    }
    set({ timeframe: timeframe as Timeframe });
  },
  setInstruments: (instruments: InstrumentSchema[]) => set({ instruments }),
}));