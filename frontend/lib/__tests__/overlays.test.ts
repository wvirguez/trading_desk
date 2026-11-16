import { describe, it, expect } from "vitest";
import type { components } from "@/types/api";

type TradeSignalSchema = components["schemas"]["TradeSignalSchema"];
type FairValueGap = components["schemas"]["FairValueGap"];

import { signalToOverlay, fvgToBox } from "../overlays";

describe("lib/overlays", () => {
  const createMockSignal = (overrides: Partial<TradeSignalSchema> = {}): TradeSignalSchema => ({
    id: "123e4567-e89b-12d3-a456-426614174000",
    analysis_id: "123e4567-e89b-12d3-a456-426614174001",
    symbol: "BTC/USDT",
    timeframe: "1h",
    direction: "LONG",
    entry: "50000.00",
    stop_loss: "49000.00",
    take_profit: "52000.00",
    rr: "2.0",
    status: "APPROVED",
    rationale: "Estructura alcista con BOS confirmado",
    regime: "TRENDING",
    asset_class: "CRYPTO",
    created_at: "2024-01-15T10:00:00Z",
    veto_reasons: [],
    ...overrides,
  });

  const createMockFvg = (overrides: Partial<FairValueGap> = {}): FairValueGap => ({
    direction: "LONG",
    high: "51000.00",
    low: "50500.00",
    ts: "2024-01-15T08:00:00Z",
    mitigated_at: null,
    ...overrides,
  });

  describe("signalToOverlay", () => {
    it("devuelve niveles de entrada, SL y TP con etiquetas correctas para LONG", () => {
      const signal = createMockSignal({ direction: "LONG" });
      const overlay = signalToOverlay(signal);

      expect(overlay.levels).toHaveLength(3);
      expect(overlay.levels[0]).toMatchObject({
        price: "50000.00",
        label: "Entrada",
      });
      expect(overlay.levels[1]).toMatchObject({
        price: "49000.00",
        label: "SL",
      });
      expect(overlay.levels[2]).toMatchObject({
        price: "52000.00",
        label: "TP",
      });
    });

    it("devuelve niveles de entrada, SL y TP con etiquetas correctas para SHORT", () => {
      const signal = createMockSignal({
        direction: "SHORT",
        entry: "50000.00",
        stop_loss: "51000.00",
        take_profit: "48000.00",
      });
      const overlay = signalToOverlay(signal);

      expect(overlay.levels).toHaveLength(3);
      expect(overlay.levels[0]).toMatchObject({ price: "50000.00", label: "Entrada" });
      expect(overlay.levels[1]).toMatchObject({ price: "51000.00", label: "SL" });
      expect(overlay.levels[2]).toMatchObject({ price: "48000.00", label: "TP" });
    });

    it("devuelve zona entre entrada y SL para LONG", () => {
      const signal = createMockSignal({ direction: "LONG", entry: "50000.00", stop_loss: "49000.00" });
      const overlay = signalToOverlay(signal);

      expect(overlay.zone).toMatchObject({
        top: "50000.00",
        bottom: "49000.00",
        direction: "LONG",
      });
    });

    it("devuelve zona entre entrada y SL para SHORT", () => {
      const signal = createMockSignal({ direction: "SHORT", entry: "50000.00", stop_loss: "51000.00" });
      const overlay = signalToOverlay(signal);

      expect(overlay.zone).toMatchObject({
        top: "51000.00",
        bottom: "50000.00",
        direction: "SHORT",
      });
    });

    it("incluye R:R tal cual del backend sin recalcular", () => {
      const signal = createMockSignal({ rr: "2.5" });
      const overlay = signalToOverlay(signal);

      expect(overlay.rr).toBe("2.5");
    });

    it("incluye el rationale del backend", () => {
      const signal = createMockSignal({ rationale: "Estructura alcista con BOS confirmado" });
      const overlay = signalToOverlay(signal);

      expect(overlay.rationale).toBe("Estructura alcista con BOS confirmado");
    });

    it("incluye el estado de la señal", () => {
      const signal = createMockSignal({ status: "APPROVED" });
      const overlay = signalToOverlay(signal);

      expect(overlay.status).toBe("APPROVED");
    });

    it("incluye la dirección de la señal", () => {
      const signal = createMockSignal({ direction: "LONG" });
      const overlay = signalToOverlay(signal);

      expect(overlay.direction).toBe("LONG");
    });

    it("incluye el símbolo y timeframe", () => {
      const signal = createMockSignal({ symbol: "ETH/USDT", timeframe: "4h" });
      const overlay = signalToOverlay(signal);

      expect(overlay.symbol).toBe("ETH/USDT");
      expect(overlay.timeframe).toBe("4h");
    });

    it("incluye el id de la señal", () => {
      const signal = createMockSignal({ id: "abc-123" });
      const overlay = signalToOverlay(signal);

      expect(overlay.id).toBe("abc-123");
    });
  });

  describe("fvgToBox", () => {

    it("devuelve rectángulo con color verde para FVG alcista (LONG)", () => {
      const fvg = createMockFvg({ direction: "LONG", high: "51000.00", low: "50500.00" });
      const box = fvgToBox(fvg);

      expect(box).not.toBeNull();
      expect(box!.top).toBe("51000.00");
      expect(box!.bottom).toBe("50500.00");
      expect(box!.direction).toBe("LONG");
      expect(box!.color).toContain("rgba(38, 166, 154"); // verde para LONG
    });

    it("devuelve rectángulo con color rojo para FVG bajista (SHORT)", () => {
      const fvg = createMockFvg({ direction: "SHORT", high: "49500.00", low: "49000.00" });
      const box = fvgToBox(fvg);

      expect(box).not.toBeNull();
      expect(box!.direction).toBe("SHORT");
      expect(box!.color).toContain("rgba(239, 83, 80"); // rojo para SHORT
    });

    it("aplica estilo atenuado si el FVG está mitigado", () => {
      const fvg = createMockFvg({
        direction: "LONG",
        high: "51000.00",
        low: "50500.00",
        mitigated_at: "2024-01-15T10:00:00Z",
      });
      const box = fvgToBox(fvg);

      expect(box).not.toBeNull();
      expect(box!.mitigated).toBe(true);
      expect(box!.color).toContain("0.3"); // opacidad reducida
    });

    it("incluye timestamp del FVG", () => {
      const fvg = createMockFvg({ ts: "2024-01-15T08:00:00Z" });
      const box = fvgToBox(fvg);

      expect(box).not.toBeNull();
      expect(box!.ts).toBe("2024-01-15T08:00:00Z");
    });

    it("devuelve null si el FVG no tiene high/low válidos", () => {
      const fvg = createMockFvg({ high: "", low: "" });
      const box = fvgToBox(fvg);

      expect(box).toBeNull();
    });
  });
});