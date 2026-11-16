import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { components } from "@/types/api";

type AnalyzeRequest = components["schemas"]["AnalyzeRequest"];

const mockFetch = vi.fn();
global.fetch = mockFetch;

interface FetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  signal?: AbortSignal;
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "Wrapper";
  return Wrapper;
}

function closedStream(events: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < events.length) {
        controller.enqueue(encoder.encode(events[index++]));
      } else {
        controller.close();
      }
    },
  });
}

function abortableStream(events: string[], signal: AbortSignal): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream<Uint8Array>({
    start(controller) {
      signal.addEventListener("abort", () => {
        try {
          controller.error(new DOMException("Aborted", "AbortError"));
        } catch {
          // El controlador ya está cerrado.
        }
      });
    },
    pull(controller) {
      if (index < events.length) {
        controller.enqueue(encoder.encode(events[index++]));
      }
    },
  });
}

function okResponse(stream: ReadableStream<Uint8Array>) {
  return {
    ok: true,
    status: 200,
    body: stream,
    headers: new Headers({ "content-type": "text/event-stream" }),
  };
}

const startedEvent =
  'data: {"event":"analysis_started","analysis_id":"123","seq":1,"started_at":"2024-01-01T00:00:00Z","symbol":"BTC/USDT","timeframe":"1h","timeframes":["1h"]}\n\n';

const completedStream = [
  startedEvent,
  'data: {"event":"step_started","analysis_id":"123","seq":2,"step":"STRUCTURE"}\n\n',
  'data: {"event":"step_completed","analysis_id":"123","seq":3,"step":"STRUCTURE","output":{},"usage":{"model":"claude-sonnet","input_tokens":100,"output_tokens":50,"latency_ms":200,"cost_usd":"0.01"}}\n\n',
  'data: {"event":"step_started","analysis_id":"123","seq":4,"step":"QUANT"}\n\n',
  'data: {"event":"step_completed","analysis_id":"123","seq":5,"step":"QUANT","output":{},"usage":{"model":"claude-sonnet","input_tokens":200,"output_tokens":100,"latency_ms":300,"cost_usd":"0.02"}}\n\n',
  'data: {"event":"analysis_completed","analysis_id":"123","seq":6,"report":{"analysis_id":"123","symbol":"BTC/USDT","timeframe":"1h","outcome":"SIGNAL_APPROVED","usage":{"model":"claude-sonnet","input_tokens":300,"output_tokens":150,"latency_ms":500,"cost_usd":"0.03"},"warnings":[]}}\n\n',
];

describe("hooks/use-analysis.ts - useAnalysis", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("start(request) hace POST /api/v1/agents/analyze con el cuerpo AnalyzeRequest y entrega los eventos en orden", async () => {
    const { useAnalysis } = await import("../use-analysis");

    mockFetch.mockResolvedValue(okResponse(closedStream(completedStream)));

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });
    const request: AnalyzeRequest = { symbol: "BTC/USDT", timeframe: "1h" };

    await act(async () => {
      await result.current.start(request);
    });

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents/analyze"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        }),
        body: JSON.stringify(request),
      }),
    );

    await waitFor(() => {
      expect(result.current.state.status).toBe("completed");
      expect(result.current.state.steps).toHaveLength(2);
      expect(result.current.state.steps.map((step) => step.step)).toEqual([
        "STRUCTURE",
        "QUANT",
      ]);
      expect(result.current.state.outcome).toBe("SIGNAL_APPROVED");
      expect(result.current.state.totalUsage).toEqual({
        inputTokens: 300,
        outputTokens: 150,
        latencyMs: 500,
        costUsd: "0.03",
      });
    });
  });

  it.each([
    [404, "Instrumento no encontrado: BTC/XXX"],
    [422, "Datos insuficientes: se necesitan 101 velas, hay 50"],
    [503, "El análisis con agentes no está configurado: falta ANTHROPIC_API_KEY."],
  ])(
    "%i antes del stream produce un error con el detail exacto del backend",
    async (status, detail) => {
      const { useAnalysis } = await import("../use-analysis");

      mockFetch.mockResolvedValue({
        ok: false,
        status,
        json: async () => ({ detail }),
      });

      const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

      await act(async () => {
        await result.current.start({ symbol: "BTC/XXX", timeframe: "1h" });
      });

      expect(result.current.state.status).toBe("error");
      expect(result.current.state.error).toBe(detail);
      expect(result.current.state.canRetry).toBe(true);
    },
  );

  it("tras un error el formulario sigue usable y permite lanzar otro análisis", async () => {
    const { useAnalysis } = await import("../use-analysis");

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Agentes no configurados" }),
    });
    mockFetch.mockResolvedValueOnce(okResponse(closedStream(completedStream)));

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
    });
    expect(result.current.state.status).toBe("error");

    await act(async () => {
      await result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
    });

    expect(result.current.state.status).toBe("completed");
  });

  it("analysis_failed durante el stream se muestra con el paso y el mensaje", async () => {
    const { useAnalysis } = await import("../use-analysis");

    mockFetch.mockResolvedValue(
      okResponse(
        closedStream([
          startedEvent,
          'data: {"event":"step_started","analysis_id":"123","seq":2,"step":"QUANT"}\n\n',
          'data: {"event":"analysis_failed","analysis_id":"123","seq":3,"error":"El paso QUANT superó el tiempo máximo","step":"QUANT"}\n\n',
        ]),
      ),
    );

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe("failed");
      expect(result.current.state.error).toBe("El paso QUANT superó el tiempo máximo");
      expect(result.current.state.failedStep).toBe("QUANT");
    });
  });

  it("cancel() aborta el fetch y deja el estado «Cancelado»", async () => {
    const { useAnalysis } = await import("../use-analysis");

    const capturedSignal: { current: AbortSignal | null } = { current: null };
    mockFetch.mockImplementation((_url: string, init: FetchInit) => {
      capturedSignal.current = init.signal ?? null;
      return Promise.resolve(
        okResponse(
          abortableStream(
            [
              startedEvent,
              'data: {"event":"step_started","analysis_id":"123","seq":2,"step":"STRUCTURE"}\n\n',
            ],
            init.signal as AbortSignal,
          ),
        ),
      );
    });

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

    await act(async () => {
      const promise = result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
      result.current.cancel();
      await promise;
    });

    expect(capturedSignal.current).not.toBeNull();
    expect(capturedSignal.current?.aborted).toBe(true);
    expect(result.current.state.status).toBe("cancelled");
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.canRetry).toBe(true);
  });

  it("desmontar aborta la petición", async () => {
    const { useAnalysis } = await import("../use-analysis");

    const capturedSignal: { current: AbortSignal | null } = { current: null };
    mockFetch.mockImplementation((_url: string, init: FetchInit) => {
      capturedSignal.current = init.signal ?? null;
      return Promise.resolve(
        okResponse(abortableStream([startedEvent], init.signal as AbortSignal)),
      );
    });

    const { result, unmount } = renderHook(() => useAnalysis(), {
      wrapper: createWrapper(),
    });

    let promise: Promise<void> = Promise.resolve();
    act(() => {
      promise = result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
    });

    unmount();
    await act(async () => {
      await promise;
    });

    expect(capturedSignal.current).not.toBeNull();
    expect(capturedSignal.current?.aborted).toBe(true);
  });

  it("aborta la petición anterior al iniciar otra", async () => {
    const { useAnalysis } = await import("../use-analysis");

    const signals: AbortSignal[] = [];
    mockFetch.mockImplementation((_url: string, init: FetchInit) => {
      const signal = init.signal as AbortSignal;
      signals.push(signal);
      if (signals.length === 1) {
        return Promise.resolve(okResponse(abortableStream([startedEvent], signal)));
      }
      return Promise.resolve(okResponse(closedStream(completedStream)));
    });

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

    let first: Promise<void> = Promise.resolve();
    await act(async () => {
      first = result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
      await result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
      await first;
    });

    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
    expect(result.current.state.status).toBe("completed");
  });

  it("marca el análisis como interrumpido si el stream cierra sin evento terminal", async () => {
    const { useAnalysis } = await import("../use-analysis");

    mockFetch.mockResolvedValue(
      okResponse(
        closedStream([
          startedEvent,
          'data: {"event":"step_started","analysis_id":"123","seq":2,"step":"STRUCTURE"}\n\n',
        ]),
      ),
    );

    const { result } = renderHook(() => useAnalysis(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.start({ symbol: "BTC/USDT", timeframe: "1h" });
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.error).toMatch(/Análisis interrumpido/);
    expect(result.current.state.canRetry).toBe(true);
  });
});
