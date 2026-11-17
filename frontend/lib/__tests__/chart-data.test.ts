import { describe, it, expect } from "vitest";
import { candlesToSeries, applyTick, equityToSeries, type CandleSeriesItem } from "../chart-data";

describe("chart-data", () => {
  const sampleCandles = [
    {
      ts: "2024-01-01T00:00:00Z",
      open: "100.0",
      high: "105.0",
      low: "99.0",
      close: "103.0",
      volume: "1000",
      symbol: "BTC/USDT",
      timeframe: "1h" as const,
    },
    {
      ts: "2024-01-01T01:00:00Z",
      open: "103.0",
      high: "108.0",
      low: "102.0",
      close: "106.0",
      volume: "1100",
      symbol: "BTC/USDT",
      timeframe: "1h" as const,
    },
    {
      ts: "2024-01-01T02:00:00Z",
      open: "106.0",
      high: "110.0",
      low: "104.0",
      close: "108.0",
      volume: "1200",
      symbol: "BTC/USDT",
      timeframe: "1h" as const,
    },
  ];

  describe("candlesToSeries", () => {
    it("convierte velas ordenadas ascendente a series con timestamps en segundos UTC", () => {
      const result = candlesToSeries(sampleCandles);

      expect(result).toHaveLength(3);
      expect(result[0].time).toBe(1704067200); // 2024-01-01T00:00:00Z en segundos
      expect(result[1].time).toBe(1704070800); // 2024-01-01T01:00:00Z
      expect(result[2].time).toBe(1704074400); // 2024-01-01T02:00:00Z
    });

    it("convierte precios Decimal (string) a number para dibujar", () => {
      const result = candlesToSeries(sampleCandles);

      expect(result[0].open).toBe(100.0);
      expect(result[0].high).toBe(105.0);
      expect(result[0].low).toBe(99.0);
      expect(result[0].close).toBe(103.0);
      expect(typeof result[0].open).toBe("number");
    });

    it("descarta duplicados (mismo timestamp) manteniendo el último", () => {
      const candlesWithDuplicate = [
        ...sampleCandles,
        {
          ts: "2024-01-01T02:00:00Z",
          open: "107.0",
          high: "111.0",
          low: "105.0",
          close: "109.0",
          volume: "1300",
          symbol: "BTC/USDT",
          timeframe: "1h" as const,
        },
      ];

      const result = candlesToSeries(candlesWithDuplicate);

      expect(result).toHaveLength(3);
      expect(result[2].open).toBe(107.0);
      expect(result[2].close).toBe(109.0);
    });

    it("avisa de huecos (gap > 1.5x timeframe esperado) en metadata", () => {
      const candlesWithGap = [
        sampleCandles[0],
        {
          ts: "2024-01-01T03:00:00Z", // salto de 2 horas (gap de 1 vela de 1h)
          open: "108.0",
          high: "112.0",
          low: "107.0",
          close: "110.0",
          volume: "1300",
          symbol: "BTC/USDT",
          timeframe: "1h" as const,
        },
      ];

      const result = candlesToSeries(candlesWithGap, "1h");

      expect(result).toHaveLength(2);
      expect(result[1].gap).toBe(true);
    });

    it("ordena velas por timestamp aunque vengan desordenadas", () => {
      const unordered = [sampleCandles[2], sampleCandles[0], sampleCandles[1]];
      const result = candlesToSeries(unordered);

      expect(result[0].time).toBe(1704067200);
      expect(result[1].time).toBe(1704070800);
      expect(result[2].time).toBe(1704074400);
    });

    it("devuelve array vacío para input vacío", () => {
      const result = candlesToSeries([]);
      expect(result).toEqual([]);
    });

    it("maneja timeframe 5m correctamente (gap > 7.5 min)", () => {
      const candles5m = [
        {
          ts: "2024-01-01T00:00:00Z",
          open: "100.0",
          high: "101.0",
          low: "99.0",
          close: "100.5",
          volume: "100",
          symbol: "BTC/USDT",
          timeframe: "5m" as const,
        },
        {
          ts: "2024-01-01T00:10:00Z", // gap de 1 vela (5 min * 1.5 = 7.5 min)
          open: "100.5",
          high: "102.0",
          low: "100.0",
          close: "101.5",
          volume: "110",
          symbol: "BTC/USDT",
          timeframe: "5m" as const,
        },
      ];

      const result = candlesToSeries(candles5m, "5m");
      expect(result[1].gap).toBe(true);
    });
  });

  describe("applyTick", () => {
    const baseSeries: CandleSeriesItem[] = [
      { time: 1704067200, open: 100, high: 105, low: 99, close: 103, gap: false },
      { time: 1704070800, open: 103, high: 108, low: 102, close: 106, gap: false },
    ];

    it("actualiza la última vela ajustando high/low/close", () => {
      const tick = { ts: 1704070800, price: 107.5 };
      const result = applyTick(baseSeries, tick);

      expect(result).toHaveLength(2);
      expect(result[1].high).toBe(108); // max(108, 107.5)
      expect(result[1].low).toBe(102); // min(102, 107.5)
      expect(result[1].close).toBe(107.5);
      expect(result[1].open).toBe(103); // open no cambia
    });

    it("actualiza high si el precio es mayor", () => {
      const tick = { ts: 1704070800, price: 110 };
      const result = applyTick(baseSeries, tick);
      expect(result[1].high).toBe(110);
    });

    it("actualiza low si el precio es menor", () => {
      const tick = { ts: 1704070800, price: 100 };
      const result = applyTick(baseSeries, tick);
      expect(result[1].low).toBe(100);
    });

    it("abre nueva vela solo si ts es posterior al último", () => {
      const tick = { ts: 1704074400, price: 108 }; // 2024-01-01T02:00:00Z
      const result = applyTick(baseSeries, tick);

      expect(result).toHaveLength(3);
      expect(result[2].time).toBe(1704074400);
      expect(result[2].open).toBe(108);
      expect(result[2].high).toBe(108);
      expect(result[2].low).toBe(108);
      expect(result[2].close).toBe(108);
      expect(result[2].gap).toBe(false);
    });

    it("no abre nueva vela si ts es igual al último (actualiza)", () => {
      const tick = { ts: 1704070800, price: 107 };
      const result = applyTick(baseSeries, tick);

      expect(result).toHaveLength(2);
      expect(result[1].close).toBe(107);
    });

    it("no abre nueva vela si ts es anterior al último (actualiza última)", () => {
      const tick = { ts: 1704067200, price: 107 };
      const result = applyTick(baseSeries, tick);

      expect(result).toHaveLength(2);
      expect(result[1].close).toBe(107);
    });

    it("maneja series vacía creando la primera vela", () => {
      const tick = { ts: 1704067200, price: 100 };
      const result = applyTick([], tick);

      expect(result).toHaveLength(1);
      expect(result[0].time).toBe(1704067200);
      expect(result[0].open).toBe(100);
      expect(result[0].high).toBe(100);
      expect(result[0].low).toBe(100);
      expect(result[0].close).toBe(100);
    });

    it("detecta gap en nueva vela si hay salto de tiempo", () => {
      // última vela a las 02:00, tick a las 04:00 (gap de 1 vela de 1h)
      const seriesWithLastAt02: CandleSeriesItem[] = [
        { time: 1704067200, open: 100, high: 105, low: 99, close: 103, gap: false },
        { time: 1704074400, open: 106, high: 110, low: 104, close: 108, gap: false }, // 02:00
      ];
      const tick = { ts: 1704081600, price: 110 }; // 04:00
      const result = applyTick(seriesWithLastAt02, tick, "1h");

      expect(result).toHaveLength(3);
      expect(result[2].gap).toBe(true);
    });
  });
});

describe("equityToSeries", () => {
  it("convierte ts a segundos UTC y equity a number", () => {
    expect(equityToSeries([{ ts: "2024-01-01T00:00:00Z", equity: "10000.50" }])).toEqual([
      { time: 1704067200, value: 10000.5 },
    ]);
  });

  it("ordena por tiempo y descarta duplicados (gana el último)", () => {
    const result = equityToSeries([
      { ts: "2024-01-01T02:00:00Z", equity: "3" },
      { ts: "2024-01-01T00:00:00Z", equity: "1" },
      { ts: "2024-01-01T00:00:00Z", equity: "1.5" },
      { ts: "2024-01-01T01:00:00Z", equity: "2" },
    ]);
    expect(result.map((p) => p.value)).toEqual([1.5, 2, 3]);
    expect(result.map((p) => p.time)).toEqual([1704067200, 1704070800, 1704074400]);
  });

  it("devuelve [] sin puntos", () => {
    expect(equityToSeries([])).toEqual([]);
  });
});
