"use client";

import { getWsUrl } from "./env";

type ConnectionState = "Conectado" | "Reconectando..." | "Desconectado";

type StateChangeCallback = (state: ConnectionState) => void;

interface WsClientConfig {
  symbol: string;
  timeframe: string;
}

interface WebSocketLike {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send: (data: string | ArrayBufferLike | Blob | ArrayBufferView) => void;
  close: (code?: number, reason?: string) => void;
  addEventListener: (type: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions) => void;
  removeEventListener: (type: string, listener: EventListenerOrEventListenerObject, options?: boolean | EventListenerOptions) => void;
  dispatchEvent: (event: Event) => boolean;
  binaryType: string;
  bufferedAmount: number;
  extensions: string;
  protocol: string;
  CONNECTING: number;
  OPEN: number;
  CLOSING: number;
  CLOSED: number;
}

export interface WebSocketFactory {
  new (url: string): WebSocketLike;
}

const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30000;

export class WsClient {
  private ws: WebSocketLike | null = null;
  private config: WsClientConfig;
  private state: ConnectionState = "Desconectado";
  private stateCallbacks: StateChangeCallback[] = [];
  private backoffAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isClosed = false;
  private onMessageHandler: ((data: string) => void) | null = null;
  private WebSocketCtor: WebSocketFactory;

  constructor(symbol: string, timeframe: string, WebSocketCtor?: WebSocketFactory) {
    this.config = { symbol, timeframe };
    this.WebSocketCtor = WebSocketCtor ?? (globalThis.WebSocket as WebSocketFactory);
  }

  private getUrl(): string {
    const base = getWsUrl();
    const encodedSymbol = encodeURIComponent(this.config.symbol);
    return `${base}/stream/${encodedSymbol}?tf=${encodeURIComponent(this.config.timeframe)}`;
  }

  private setState(newState: ConnectionState): void {
    if (this.state !== newState) {
      this.state = newState;
      this.stateCallbacks.forEach((cb) => cb(newState));
    }
  }

  onStateChange(callback: StateChangeCallback): () => void {
    this.stateCallbacks.push(callback);
    return () => {
      const idx = this.stateCallbacks.indexOf(callback);
      if (idx >= 0) this.stateCallbacks.splice(idx, 1);
    };
  }

  onMessage(handler: (data: string) => void): void {
    this.onMessageHandler = handler;
  }

  connect(): void {
    if (this.ws?.readyState === 1 || this.ws?.readyState === 0) {
      return;
    }
    if (this.isClosed) {
      return;
    }

    const url = this.getUrl();
    this.ws = new this.WebSocketCtor(url);

    this.ws.onopen = () => {
      this.backoffAttempt = 0;
      this.setState("Conectado");
    };

    this.ws.onclose = (event: CloseEvent) => {
      if (this.isClosed) {
        this.setState("Desconectado");
        return;
      }

      if (event.code === 1000 || event.code === 1001) {
        this.setState("Desconectado");
        return;
      }

      this.setState("Reconectando...");
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // El evento onclose se disparará después con el código apropiado
    };

    this.ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string" && this.onMessageHandler) {
        this.onMessageHandler(event.data);
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    const delay = Math.min(
      BACKOFF_BASE_MS * Math.pow(2, this.backoffAttempt),
      BACKOFF_MAX_MS
    );

    this.backoffAttempt += 1;

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  disconnect(): void {
    this.isClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, "Client disconnected");
      this.ws = null;
    }
    this.setState("Desconectado");
  }

  close(): void {
    this.disconnect();
  }

  setSymbol(symbol: string): void {
    if (this.config.symbol !== symbol) {
      this.config.symbol = symbol;
      this.reconnect();
    }
  }

  setTimeframe(timeframe: string): void {
    if (this.config.timeframe !== timeframe) {
      this.config.timeframe = timeframe;
      this.reconnect();
    }
  }

  private reconnect(): void {
    this.disconnect();
    this.isClosed = false;
    this.connect();
  }

  getState(): ConnectionState {
    return this.state;
  }
}

export function createWsClient(symbol: string, timeframe: string, WebSocketCtor?: WebSocketFactory): WsClient {
  return new WsClient(symbol, timeframe, WebSocketCtor);
}