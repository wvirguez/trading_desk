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