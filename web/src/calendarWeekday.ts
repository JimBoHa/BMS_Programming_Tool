/** Civil Gregorian weekday only; no current clock, locale or controller query. */
export function calendarMatchingWeekday(
  value: readonly string[],
): string | null {
  if (
    value.length !== 4 ||
    !/^[0-9]{4}$/.test(value[0]) ||
    !/^[1-9][0-9]?$/.test(value[1]) ||
    !/^[1-9][0-9]?$/.test(value[2])
  )
    return null;
  const year = Number(value[0]),
    month = Number(value[1]),
    day = Number(value[2]);
  if (year < 1900 || year > 2154 || month > 12 || day > 31) return null;
  // UTC avoids a computer timezone/DST dependency; it supplies no device timezone.
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  )
    return null;
  return String(date.getUTCDay() || 7);
}
