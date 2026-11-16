import type { Page } from "@playwright/test";
import type { components } from "../../types/api";
import { loadFixture } from "./fixtures";

type TickUpdateEvent = components["schemas"]["TickUpdateEvent"];
type SignalAlertEvent = components["schemas"]["SignalAlertEvent"];

interface WsEventsFixture {
  tick: TickUpdateEvent;
  signal: SignalAlertEvent;
}

const events = loadFixture<WsEventsFixture>("ws-events.json");

export interface StreamMockOptions {
  tick?: boolean;
  signal?: boolean;
  delayMs?: number;
}

export async function installStreamMock(
  page: Page,
  options: StreamMockOptions = {},
): Promise<void> {
  await page.routeWebSocket(/\/api\/v1\/ws\/stream\//, (ws) => {
    ws.onMessage(() => undefined);

    const delay = options.delayMs ?? 800;
    const send = (payload: unknown) => {
      try {
        ws.send(JSON.stringify(payload));
      } catch {
        return;
      }
    };

    if (options.tick) {
      setTimeout(() => send(events.tick), delay);
    }
    if (options.signal) {
      setTimeout(() => send(events.signal), delay + 400);
    }
  });
}