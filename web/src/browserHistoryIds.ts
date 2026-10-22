const MAX_ID = BigInt(Number.MAX_SAFE_INTEGER);
const range = (zero: boolean) => `${zero ? 0 : 1}..${Number.MAX_SAFE_INTEGER}`;

/** Deliberately refuse unsupported browser identities before numeric coercion. */
export function parseHistoryId(
  text: string,
  label: string,
  zero = false,
): number {
  const token = text.trim();
  if (token.length > 16 || !/^(?:0|[1-9][0-9]*)$/.test(token))
    throw new Error(
      `${label} requires a plain decimal whole ID in ${range(zero)}; no signs, fractions or exponents.`,
    );
  const value = BigInt(token);
  if (value < (zero ? 0n : 1n) || value > MAX_ID)
    throw new Error(
      `${label} is outside the supported browser history ID range ${range(zero)}.`,
    );
  return Number(value);
}

/** Server-side SQLite IDs may be 64-bit; a projected unsafe Number is not identity. */
export function requireHistoryId(
  value: unknown,
  label: string,
  zero = false,
): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < (zero ? 0 : 1)
  )
    throw new Error(
      `${label} is not an exact supported browser history ID in ${range(zero)}. This page is unavailable; no rounded ID will be used.`,
    );
  return value;
}

export function showHistoryId(value: unknown, zero = false): string {
  try {
    return String(requireHistoryId(value, "History ID", zero));
  } catch {
    return "unsupported browser ID";
  }
}
