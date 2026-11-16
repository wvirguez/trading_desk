import type { Page, Route } from "@playwright/test";
import type { components } from "../../types/api";
import { loadFixture } from "./fixtures";

type Instrument = components["schemas"]["InstrumentSchema"];
type Candle = components["schemas"]["CandleSchema"];
type MarketStructureResult = components["schemas"]["MarketStructureResult"];
type TradeSignal = components["schemas"]["TradeSignalSchema"];
type AnalysisEvent = components["schemas"]["AnalysisEventEnvelope"];

const CORS_HEADERS: Record<string, string> = {
  "access-control-allow-origin": "*",
};

const PREFLIGHT_HEADERS: Record<string, string> = {
  ...CORS_HEADERS,
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,accept",
  "access-control-max-age": "600",
};

const instruments = loadFixture<Instrument[]>("instruments.json");
const structure = loadFixture<MarketStructureResult>("structure.json");
const signals = loadFixture<TradeSignal[]>("signals.json");
const analysisEvents = loadFixture<AnalysisEvent[]>("analysis-events.json");
const analyzeUnavailable = loadFixture<{ detail: string }>("analyze-503.json");

const candlesByKey: Record<string, Candle[]> = {
  "BTC/USDT|1h": loadFixture<Candle[]>("candles-btc-usdt-1h.json"),
  "BTC/USDT|4h": loadFixture<Candle[]>("candles-btc-usdt-4h.json"),
  "EUR/USD|1h": loadFixture<Candle[]>("candles-eur-usd-1h.json"),
  "EUR/USD|4h": loadFixture<Candle[]>("candles-eur-usd-4h.json"),
};

export interface RestMockOptions {
  analyze?: "success" | "unavailable";
}

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    headers: { ...CORS_HEADERS, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function installRestMocks(
  page: Page,
  options: RestMockOptions = {},
): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());

    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: PREFLIGHT_HEADERS });
      return;
    }

    if (url.pathname.endsWith("/market/instruments")) {
      await fulfillJson(route, 200, instruments);
      return;
    }

    if (url.pathname.endsWith("/market/ohlcv")) {
      const symbol = url.searchParams.get("symbol") ?? "BTC/USDT";
      const timeframe = url.searchParams.get("tf") ?? "1h";
      const series = candlesByKey[`${symbol}|${timeframe}`];
      if (!series) {
        await fulfillJson(route, 404, {
          detail: `Sin velas simuladas para ${symbol} ${timeframe}`,
        });
        return;
      }
      await fulfillJson(route, 200, series);
      return;
    }

    if (url.pathname.endsWith("/market/structure")) {
      await fulfillJson(route, 200, structure);
      return;
    }

    if (url.pathname.endsWith("/signals/active")) {
      await fulfillJson(route, 200, signals);
      return;
    }

    if (url.pathname.endsWith("/agents/analyze") && method === "POST") {
      if (options.analyze === "unavailable") {
        await fulfillJson(route, 503, analyzeUnavailable);
        return;
      }

      const body = analysisEvents
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join("");
      await route.fulfill({
        status: 200,
        headers: {
          ...CORS_HEADERS,
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
        },
        body,
      });
      return;
    }

    await fulfillJson(route, 404, {
      detail: `Ruta no simulada: ${method} ${url.pathname}`,
    });
  });
}