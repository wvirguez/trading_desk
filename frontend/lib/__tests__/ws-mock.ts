import { vi } from "vitest";

export interface MockWebSocketInstance {
  url: string;
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  simulateOpen: () => void;
  simulateClose: (code?: number, reason?: string) => void;
  simulateMessage: (data: string) => void;
  simulateError: () => void;
  binaryType: string;
  bufferedAmount: number;
  extensions: string;
  protocol: string;
  CONNECTING: 0;
  OPEN: 1;
  CLOSING: 2;
  CLOSED: 3;
  addEventListener: (type: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions) => void;
  removeEventListener: (type: string, listener: EventListenerOrEventListenerObject, options?: boolean | EventListenerOptions) => void;
  dispatchEvent: (event: Event) => boolean;
}

export const mockWebSocketInstances: MockWebSocketInstance[] = [];
export const constructorCalls: string[] = [];

export class MockWebSocket implements MockWebSocketInstance {
  static instances: MockWebSocketInstance[] = [];
  
  url: string;
  readyState: number = 0;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  binaryType: "blob" | "arraybuffer" = "blob";
  bufferedAmount = 0;
  extensions = "";
  protocol = "";
  CONNECTING = 0 as const;
  OPEN = 1 as const;
  CLOSING = 2 as const;
  CLOSED = 3 as const;
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  dispatchEvent = vi.fn(() => true);

  simulateOpen = () => {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  };
  
  simulateClose = (code = 1000, reason = "") => {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close", { code, reason }));
  };
  
  simulateMessage = (data: string) => {
    this.onmessage?.(new MessageEvent("message", { data }));
  };
  
  simulateError = () => {
    this.onerror?.(new Event("error"));
  };

  constructor(url: string) {
    this.url = url;
    constructorCalls.push(url);
    
    MockWebSocket.instances.push(this);
    mockWebSocketInstances.push(this);
  }

  static clearMocks() {
    constructorCalls.length = 0;
    MockWebSocket.instances.length = 0;
    mockWebSocketInstances.length = 0;
  }
}

vi.stubGlobal("WebSocket", MockWebSocket);