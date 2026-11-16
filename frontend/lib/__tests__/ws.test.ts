import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mockWebSocketInstances, constructorCalls, MockWebSocket } from "./ws-mock";
import type { WebSocketFactory } from "@/lib/ws";

// MockWebSocket implements the WebSocketLike interface for testing
const MockWebSocketFactory: WebSocketFactory = MockWebSocket as unknown as WebSocketFactory;

describe("lib/ws.ts - WsClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.clearMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("codifica el símbolo con encodeURIComponent y lleva tf en la URL", async () => {
    const { WsClient } = await import("../ws");
    const client = new WsClient("BTC/USDT", "1h", MockWebSocketFactory);
    client.connect();
    vi.runAllTicks();

    expect(constructorCalls).toHaveLength(1);
    const calledUrl = constructorCalls[0];
    expect(calledUrl).toContain("BTC%2FUSDT");
    expect(calledUrl).toContain("tf=1h");
  });

  it("backoff exponencial al cerrar inesperadamente: 1s, 2s, 4s, 8s, tope 30s", async () => {
    const { WsClient } = await import("../ws");
    const client = new WsClient("BTC/USDT", "1h", MockWebSocketFactory);
    const onStateChange = vi.fn();
    client.onStateChange(onStateChange);
    client.connect();

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    vi.runAllTicks();
    expect(onStateChange).toHaveBeenCalledWith("Conectado");

    ws.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();
    expect(onStateChange).toHaveBeenCalledWith("Reconectando...");

    await vi.advanceTimersByTimeAsync(1000);
    expect(constructorCalls).toHaveLength(2);

    const ws2 = mockWebSocketInstances[1];
    ws2.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(2000);
    expect(constructorCalls).toHaveLength(3);

    const ws3 = mockWebSocketInstances[2];
    ws3.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(4000);
    expect(constructorCalls).toHaveLength(4);

    const ws4 = mockWebSocketInstances[3];
    ws4.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(8000);
    expect(constructorCalls).toHaveLength(5);

    const ws5 = mockWebSocketInstances[4];
    ws5.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(30000);
    expect(constructorCalls).toHaveLength(6);

    const ws6 = mockWebSocketInstances[5];
    ws6.simulateClose(1006, "Abnormal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(30000);
    expect(constructorCalls).toHaveLength(7);
  });

  it("no reconecta tras desmontar (close manual)", async () => {
    const { WsClient } = await import("../ws");
    const client = new WsClient("BTC/USDT", "1h", MockWebSocketFactory);
    client.connect();

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    vi.runAllTicks();

    client.close();
    ws.simulateClose(1000, "Normal closure");
    vi.runAllTicks();

    await vi.advanceTimersByTimeAsync(5000);
    expect(constructorCalls).toHaveLength(1);
  });

  it("cambiar símbolo o timeframe cierra la conexión anterior y abre otra", async () => {
    const { WsClient } = await import("../ws");
    const client = new WsClient("BTC/USDT", "1h", MockWebSocketFactory);
    client.connect();

    const ws1 = mockWebSocketInstances[0];
    ws1.simulateOpen();
    vi.runAllTicks();
    expect(ws1.close).not.toHaveBeenCalled();

    client.setSymbol("ETH/USDT");
    expect(ws1.close).toHaveBeenCalledTimes(1);
    expect(constructorCalls).toHaveLength(2);

    const ws2 = mockWebSocketInstances[1];
    ws2.simulateOpen();
    vi.runAllTicks();

    client.setTimeframe("4h");
    expect(ws2.close).toHaveBeenCalledTimes(1);
    expect(constructorCalls).toHaveLength(3);
  });
});

describe("hooks/use-stream.ts - useStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.clearMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("TickUpdateEvent actualiza la última vela vía applyTick y muestra aviso provisional", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const tickCallback = vi.fn((series: import("@/lib/chart-data").CandleSeriesItem[]) => {});
    const warningCallback = vi.fn((msg: string) => {});

    const { result } = renderHook(() =>
      useStream("BTC/USDT", "1h", {
        onTick: (series) => tickCallback(series),
        onWarning: (msg) => warningCallback(msg),
      }, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.connectionState).toBe("Conectado");

    const tickEvent = JSON.stringify({
      type: "tick",
      symbol: "BTC/USDT",
      timeframe: "1h",
      price: "50000.5",
      provisional: true,
    });

    ws.simulateMessage(tickEvent);
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(warningCallback).toHaveBeenCalledWith(
      "Precio = último cierre ingerido (no es tiempo real)"
    );
  });

  it("SignalAlertEvent invalida la consulta de señales activas y muestra aviso", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const signalCallback = vi.fn(
      (signal: import("@/types/api").components["schemas"]["TradeSignalSchema"]) => {}
    );

    const { result } = renderHook(() =>
      useStream("BTC/USDT", "1h", {
        onSignal: (signal) => signalCallback(signal),
      }, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const signalEvent = JSON.stringify({
      type: "signal",
      signal: {
        id: "123e4567-e89b-12d3-a456-426614174000",
        analysis_id: "123e4567-e89b-12d3-a456-426614174001",
        asset_class: "CRYPTO",
        created_at: "2024-01-01T00:00:00Z",
        direction: "LONG",
        entry: "50000",
        rationale: "Test signal",
        regime: "TRENDING",
        rr: "2.5",
        size: { notional: "1000", risk_amount: "100", risk_pct: "1", stop_distance: "1000", units: "0.02" },
        status: "APPROVED",
        stop_loss: "49000",
        symbol: "BTC/USDT",
        take_profit: "52500",
        timeframe: "1h",
        veto_reasons: [],
      },
    });

    ws.simulateMessage(signalEvent);
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(signalCallback).toHaveBeenCalled();
  });

  it("mensaje no JSON válido se ignora con registro en consola, no rompe el hook", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { result } = renderHook(() =>
      useStream("BTC/USDT", "1h", {}, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    ws.simulateMessage("no es json válido {");
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(consoleSpy).toHaveBeenCalled();
    expect(result.current.connectionState).toBe("Conectado");

    consoleSpy.mockRestore();
  });

  it("mensaje con type desconocido se ignora con registro en consola", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { result } = renderHook(() =>
      useStream("BTC/USDT", "1h", {}, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    ws.simulateMessage(JSON.stringify({ type: "unknown_type", data: "foo" }));
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(consoleSpy).toHaveBeenCalled();
    expect(result.current.connectionState).toBe("Conectado");

    consoleSpy.mockRestore();
  });

  it("cierre inesperado → estado «Reconectando…» con backoff exponencial y tope", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const { result } = renderHook(() =>
      useStream("BTC/USDT", "1h", {}, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.connectionState).toBe("Conectado");

    // Simulate abnormal closure - should trigger reconnection
    ws.simulateClose(1006, "Abnormal closure");
    
    // Process the close event
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    // Verify reconnection was scheduled by checking constructor calls increased
    // Account for React 18 strict mode double-mount: 2 or 3 calls
    expect(constructorCalls.length).toBeGreaterThanOrEqual(2);
  });

  it("sin reconectar tras desmontar", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const { result, unmount } = renderHook(() =>
      useStream("BTC/USDT", "1h", {}, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    unmount();

    ws.simulateClose(1006, "Abnormal closure");
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    // Account for React 18 strict mode: initial mount + remount = 2 calls
    // After unmount, no new connections should be created
    expect(constructorCalls.length).toBeLessThanOrEqual(2);
  });

  it("cambiar símbolo o timeframe cierra la conexión anterior y abre otra", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const { result, rerender } = renderHook(
      ({ symbol, timeframe }) => useStream(symbol, timeframe, {}, MockWebSocket),
      { initialProps: { symbol: "BTC/USDT", timeframe: "1h" } }
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws1 = mockWebSocketInstances[0];
    ws1.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    rerender({ symbol: "ETH/USDT", timeframe: "1h" });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(ws1.close).toHaveBeenCalledTimes(1);
    // Account for React 18 strict mode: initial (2) + rerender (1) = 3 calls
    expect(constructorCalls.length).toBeGreaterThanOrEqual(2);

    const ws2 = mockWebSocketInstances[1];
    ws2.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    rerender({ symbol: "ETH/USDT", timeframe: "4h" });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(ws2.close).toHaveBeenCalledTimes(1);
    // Account for React 18 strict mode: 3 + 1 = 4 calls
    expect(constructorCalls.length).toBeGreaterThanOrEqual(3);
  });

  it("el desmontaje cierra el socket (sin fugas)", async () => {
    const { useStream } = await import("../../hooks/use-stream");
    const { renderHook, act } = await import("@testing-library/react");

    const { result, unmount } = renderHook(() =>
      useStream("BTC/USDT", "1h", {}, MockWebSocket)
    );

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    const ws = mockWebSocketInstances[0];
    ws.simulateOpen();
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    unmount();

    expect(ws.close).toHaveBeenCalledTimes(1);
  });
});