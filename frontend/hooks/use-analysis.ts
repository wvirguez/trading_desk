"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiUrl } from "@/lib/env";
import { parseSseStream } from "@/lib/sse";
import {
  initialAnalysisState,
  reduceAnalysisEvent,
  type AnalysisEvent,
  type AnalysisState,
} from "@/lib/analysis-reducer";
import type { components } from "@/types/api";

type AnalyzeRequest = components["schemas"]["AnalyzeRequest"];
type AnalysisEventEnvelope = components["schemas"]["AnalysisEventEnvelope"];

export interface UseAnalysisReturn {
  state: AnalysisState;
  start: (request: AnalyzeRequest) => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

const INTERRUPTED_MESSAGE =
  "Análisis interrumpido: el flujo terminó sin analysis_completed ni analysis_failed.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function extractDetail(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const { detail } = payload;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (isRecord(item) && typeof item.msg === "string" ? item.msg : null))
      .filter((item): item is string => item !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

export function useAnalysis(): UseAnalysisReturn {
  const [state, setState] = useState<AnalysisState>(initialAnalysisState);
  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
    };
  }, []);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setState(initialAnalysisState);
  }, []);

  const cancel = useCallback(() => {
    requestIdRef.current += 1;
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setState((prev) => ({
      ...prev,
      status: "cancelled",
      error: null,
      canRetry: true,
    }));
  }, []);

  const start = useCallback(async (request: AnalyzeRequest) => {
    abortControllerRef.current?.abort();
    requestIdRef.current += 1;
    const requestId = requestIdRef.current;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setState({
      ...initialAnalysisState,
      symbol: request.symbol,
      timeframe: request.timeframe,
      status: "running",
    });

    const url = `${getApiUrl()}/api/v1/agents/analyze`;
    let terminalEventReceived = false;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });

      if (requestId !== requestIdRef.current || !mountedRef.current) return;

      if (!response.ok) {
        let detail: string | null = null;
        try {
          detail = extractDetail(await response.json());
        } catch {
          detail = null;
        }
        setState((prev) => ({
          ...prev,
          status: "error",
          error: detail ?? `Error HTTP ${response.status}`,
          canRetry: true,
        }));
        return;
      }

      if (!response.body) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: "Respuesta vacía del servidor",
          canRetry: true,
        }));
        return;
      }

      for await (const sseEvent of parseSseStream(response.body as ReadableStream<Uint8Array>)) {
        if (requestId !== requestIdRef.current || controller.signal.aborted || !mountedRef.current) {
          return;
        }

        let envelope: AnalysisEventEnvelope;
        try {
          envelope = JSON.parse(sseEvent.data) as AnalysisEventEnvelope;
        } catch {
          continue;
        }

        if (envelope.event === "analysis_completed" || envelope.event === "analysis_failed") {
          terminalEventReceived = true;
        }

        setState((prev) => reduceAnalysisEvent(prev, envelope as AnalysisEvent));
      }

      if (requestId !== requestIdRef.current || controller.signal.aborted || !mountedRef.current) {
        return;
      }

      if (!terminalEventReceived) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: INTERRUPTED_MESSAGE,
          canRetry: true,
        }));
      }
    } catch (error) {
      if (requestId !== requestIdRef.current || !mountedRef.current) return;

      if (controller.signal.aborted || isAbortError(error)) {
        setState((prev) => ({
          ...prev,
          status: "cancelled",
          error: null,
          canRetry: true,
        }));
        return;
      }

      setState((prev) => ({
        ...prev,
        status: "error",
        error:
          error instanceof Error
            ? `No se pudo conectar con el backend: ${error.message}`
            : "No se pudo conectar con el backend.",
        canRetry: true,
      }));
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }, []);

  return { state, start, cancel, reset };
}
