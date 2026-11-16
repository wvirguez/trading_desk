import { describe, expect, it, beforeEach } from "vitest";
import { useTerminalStore } from "../terminal";

describe("terminal store", () => {
  beforeEach(() => {
    useTerminalStore.setState({ symbol: "BTC/USDT", timeframe: "1h" });
  });

  it("valores por defecto BTC/USDT y 1h", () => {
    const state = useTerminalStore.getState();
    expect(state.symbol).toBe("BTC/USDT");
    expect(state.timeframe).toBe("1h");
  });

  it("setSymbol actualiza el símbolo", () => {
    useTerminalStore.getState().setSymbol("ETH/USDT");
    expect(useTerminalStore.getState().symbol).toBe("ETH/USDT");
  });

  it("setTimeframe actualiza el timeframe válido", () => {
    useTerminalStore.getState().setTimeframe("4h");
    expect(useTerminalStore.getState().timeframe).toBe("4h");
  });

  it("setTimeframe no acepta timeframe inválido", () => {
    expect(() => useTerminalStore.getState().setTimeframe("invalid")).toThrow();
    expect(useTerminalStore.getState().timeframe).toBe("1h");
  });

  it("setTimeframe acepta todos los timeframes válidos", () => {
    const valid = ["5m", "15m", "1h", "4h", "1d"] as const;
    for (const tf of valid) {
      useTerminalStore.getState().setTimeframe(tf);
      expect(useTerminalStore.getState().timeframe).toBe(tf);
    }
  });
});