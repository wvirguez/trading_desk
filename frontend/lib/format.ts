function countDecimals(value: string): number {
  const dotIndex = value.indexOf(".");
  if (dotIndex === -1) return 0;
  return value.length - dotIndex - 1;
}

function roundString(value: string, decimals: number): string {
  const isNegative = value.startsWith("-");
  const absValue = isNegative ? value.slice(1) : value;

  const [intPart, fracPart = ""] = absValue.split(".");

  if (decimals === 0) {
    const lastDigit = parseInt(intPart.slice(-1) || "0", 10);
    const carry = lastDigit >= 5 ? 1 : 0;
    const roundedInt = (BigInt(intPart) + BigInt(carry)).toString();
    return (isNegative ? "-" : "") + roundedInt;
  }

  const paddedFrac = fracPart.padEnd(decimals + 1, "0");
  const keepFrac = paddedFrac.slice(0, decimals);
  const nextDigit = parseInt(paddedFrac[decimals] || "0", 10);

  if (nextDigit >= 5) {
    const fracAsInt = BigInt(keepFrac || "0") + BigInt(1);
    const carry = fracAsInt >= BigInt(10) ** BigInt(decimals) ? 1 : 0;
    const newFrac = (fracAsInt % (BigInt(10) ** BigInt(decimals)))
      .toString()
      .padStart(decimals, "0");
    const newInt = (BigInt(intPart) + BigInt(carry)).toString();
    return (isNegative ? "-" : "") + newInt + "." + newFrac;
  }

  return (isNegative ? "-" : "") + intPart + "." + keepFrac.padEnd(decimals, "0");
}

export function formatPrice(price: string, tickSize: string): string {
  const decimals = countDecimals(tickSize);
  return roundString(price, decimals);
}

export function formatQuantity(quantity: string, lotSize: string): string {
  const decimals = countDecimals(lotSize);
  return roundString(quantity, decimals);
}

const NULL_PLACEHOLDER = "—";
const PLAIN_DECIMAL = /^-?\d+(\.\d+)?$/;

/** Importe con decimales fijos y sin notación científica; `—` si es nulo. */
export function formatAmount(
  value: string | number | null | undefined,
  decimals: number = 2,
): string {
  if (value === null || value === undefined || value === "") return NULL_PLACEHOLDER;
  if (typeof value === "string" && PLAIN_DECIMAL.test(value)) {
    return roundString(value, decimals);
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return NULL_PLACEHOLDER;
  return numeric.toFixed(decimals);
}

/** Fracción del backend (0,05 = 5 %) mostrada como porcentaje; `—` si es nulo. */
export function formatPercent(
  value: number | null | undefined,
  decimals: number = 2,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NULL_PLACEHOLDER;
  }
  return `${(value * 100).toFixed(decimals)} %`;
}
