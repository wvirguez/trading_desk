import { describe, expect, it } from "vitest";
import { formatAmount, formatPercent, formatPrice, formatQuantity } from "@/lib/format";

describe("format", () => {
  describe("formatPrice", () => {
    it("formatea precio con decimales según tick_size", () => {
      expect(formatPrice("50000.12345678", "0.01")).toBe("50000.12");
      expect(formatPrice("50000.12345678", "0.1")).toBe("50000.1");
      expect(formatPrice("50000.12345678", "1")).toBe("50000");
      expect(formatPrice("0.00012345", "0.00000001")).toBe("0.00012345");
    });

    it("no usa float para el texto final", () => {
      // Verifica que no hay pérdida de precisión por pasar por float
      const result = formatPrice("999999999999999999.99", "0.01");
      expect(result).toBe("999999999999999999.99");
    });

    it("maneja tick_size con más decimales que el precio", () => {
      expect(formatPrice("100", "0.001")).toBe("100.000");
    });

    it("redondea correctamente", () => {
      expect(formatPrice("100.126", "0.01")).toBe("100.13");
      expect(formatPrice("100.124", "0.01")).toBe("100.12");
    });
  });

  describe("formatQuantity", () => {
    it("formatea cantidad con decimales según lot_size", () => {
      expect(formatQuantity("1.12345678", "0.001")).toBe("1.123");
      expect(formatQuantity("1.12345678", "0.01")).toBe("1.12");
      expect(formatQuantity("1.12345678", "1")).toBe("1");
    });

    it("no usa float para el texto final", () => {
      const result = formatQuantity("999999999999999999.999", "0.001");
      expect(result).toBe("999999999999999999.999");
    });
  });
});

describe("formatPercent y formatAmount", () => {
  it("formatea fracciones como porcentaje", () => {
    expect(formatPercent(0.1234)).toBe("12.34 %");
    expect(formatPercent(-0.05, 1)).toBe("-5.0 %");
    expect(formatPercent(0)).toBe("0.00 %");
  });

  it("devuelve — para nulos", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
    expect(formatAmount(null)).toBe("—");
    expect(formatAmount(undefined)).toBe("—");
  });

  it("formatea importes sin notación científica", () => {
    expect(formatAmount("10234.567")).toBe("10234.57");
    expect(formatAmount("10000")).toBe("10000.00");
    expect(formatAmount("1E+4")).toBe("10000.00");
    expect(formatAmount(0.0000001, 2)).toBe("0.00");
    expect(formatAmount(1.5)).toBe("1.50");
    expect(formatAmount("123456789012345678901.239")).toBe("123456789012345678901.24");
  });
});
