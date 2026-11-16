"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { WsClient } from "@/lib/ws";
import { applyTick, type CandleSeriesItem } from "@/lib/chart-data";
import type { components } from "@/types/api";

type StreamEvent =
  | components["schemas"]["TickUpdateEvent"]
  | components["schemas"]["SignalAlertEvent"]
  | components["schemas"]["StreamErrorEvent"];

type ConnectionState = "Conectado" | "Reconectando..." | "Desconectado";

interface UseStreamCallbacks {
  onTick?: (series: CandleSeriesItem[]) => void;
  onSignal?: (signal: components["schemas"]["TradeSignalSchema"]) => void;
  onWarning?: (message: string) => void;
  onError?: (message: string) => void;
}

interface UseStreamReturn {
  connectionState: ConnectionState;
  lastTick: components["schemas"]["TickUpdateEvent"] | null;
  lastSignal: components["schemas"]["SignalAlertEvent"] | null;
}

interface WebSocketFactory {
  new (url: string): WebSocket;
}

export function useStream(
  symbol: string,
  timeframe: string,
  callbacks: UseStreamCallbacks = {},
  WebSocketCtor?: WebSocketFactory
): UseStreamReturn {
  const clientRef = useRef<WsClient | null>(null);
  const seriesRef = useRef<CandleSeriesItem[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("Desconectado");
  const [lastTick, setLastTick] = useState<components["schemas"]["TickUpdateEvent"] | null>(null);
  const [lastSignal, setLastSignal] = useState<components["schemas"]["SignalAlertEvent"] | null>(null);

  const applyTickToSeries = useCallback(
    (tick: components["schemas"]["TickUpdateEvent"]) => {
      const tickData = {
        ts: Math.floor(new Date().getTime() / 1000),
        price: parseFloat(tick.price),
      };
      seriesRef.current = applyTick(seriesRef.current, tickData, timeframe);
      callbacks.onTick?.(seriesRef.current);
    },
    [timeframe, callbacks]
  );

  useEffect(() => {
    const client = new WsClient(symbol, timeframe, WebSocketCtor);
    clientRef.current = client;

    const unsubscribeState = client.onStateChange((state) => {
      setConnectionState(state);
    });

    client.onMessage((rawData: string) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(rawData);
      } catch {
        console.warn("[WS] Mensaje no es JSON válido, ignorado:", rawData.slice(0, 100));
        return;
      }

      if (!("type" in event)) {
        console.warn("[WS] Mensaje sin campo type, ignorado:", rawData.slice(0, 100));
        return;
      }

      const eventType = event.type;
      switch (eventType) {
        case "tick": {
          setLastTick(event);
          callbacks.onWarning?.("Precio = último cierre ingerido (no es tiempo real)");
          applyTickToSeries(event);
          break;
        }
        case "signal": {
          setLastSignal(event);
          callbacks.onSignal?.(event.signal);
          callbacks.onWarning?.("Nueva señal aprobada recibida");
          break;
        }
        case "error": {
          callbacks.onError?.(event.message);
          break;
        }
        default: {
          console.warn("[WS] Tipo de evento desconocido, ignorado:", eventType);
        }
      }
    });

    client.connect();

    return () => {
      unsubscribeState();
      client.close();
      clientRef.current = null;
    };
  }, [symbol, timeframe, applyTickToSeries, callbacks, WebSocketCtor]);

  return {
    connectionState,
    lastTick,
    lastSignal,
  };
}